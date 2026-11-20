"""
FastAPI Application & REST/WebSocket Server for NHAI AI Road Survey Dashcam.
Serves live low-latency preview stream, high-frequency telemetry WebSocket,
recording state management, gallery downloads, and the offline PWA.
"""

from __future__ import annotations
import asyncio
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import AppConfig, settings
from backend.core.hal.camera import CameraDriver
from backend.core.hal.gps import GPSDriver
from backend.core.hal.imu import IMUDriver
from backend.core.hal.gpio_controller import GPIOController
from backend.core.storage_manager import StorageManager
from backend.core.recorder import DashcamRecorder

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
RECORDINGS_DIR = Path(settings.storage.storage_path).resolve()
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="NHAI AI Road Survey Dashcam API",
    version="2.4.0-nhai",
    description="Offline-first Raspberry Pi 5 backend system for NHAI road surveys.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Hardware Abstraction Layers
storage_mgr = StorageManager(
    recordings_dir=settings.storage.storage_path,
    max_usage_percent=settings.storage.max_storage_usage_percent,
    low_warning_percent=settings.storage.low_storage_warning_percent,
)

gps_driver = GPSDriver(
    port=settings.hardware.gps_port,
    baudrate=settings.hardware.gps_baudrate,
    simulated=settings.hardware.simulated_mode or (platform.system() != "Linux"),
    start_chainage_km=settings.survey.chainage_km_start,
    chainage_direction=settings.survey.chainage_direction,
)

imu_driver = IMUDriver(
    i2c_bus=settings.hardware.imu_i2c_bus,
    i2c_address=settings.hardware.imu_i2c_address,
    simulated=settings.hardware.simulated_mode or (platform.system() != "Linux"),
    shock_threshold_g=settings.storage.auto_lock_shock_g,
)

camera_driver = CameraDriver(
    resolution=settings.camera.resolution,
    framerate=settings.camera.framerate,
    bitrate_mbps=settings.camera.bitrate_mbps,
    exposure_mode=settings.camera.exposure_mode,
    simulated=settings.hardware.simulated_mode or (platform.system() != "Linux"),
)

gpio_controller = GPIOController(
    button_pin=settings.hardware.gpio_button_pin,
    led_pin=settings.hardware.gpio_led_pin,
    simulated=settings.hardware.simulated_mode or (platform.system() != "Linux"),
)

recorder = DashcamRecorder(
    config=settings,
    camera=camera_driver,
    gps=gps_driver,
    imu=imu_driver,
    gpio=gpio_controller,
    storage=storage_mgr,
)


@app.on_event("startup")
async def on_startup():
    print("[App] Starting NHAI Dashcam HAL drivers...")
    gps_driver.start()
    imu_driver.start()
    camera_driver.start()
    gpio_controller.start()

    # Auto start recording on boot if enabled
    if settings.storage.auto_start_on_boot:
        print("[App] Auto-start on boot enabled: starting recording...")
        recorder.start_recording()


@app.on_event("shutdown")
async def on_shutdown():
    print("[App] Shutting down NHAI Dashcam HAL drivers...")
    if recorder.is_recording():
        recorder.stop_recording()
    camera_driver.stop()
    gps_driver.stop()
    imu_driver.stop()
    gpio_controller.stop()


# ---------------- SYSTEM STATUS & TELEMETRY ---------------- #

def get_pi_temperature() -> float:
    """Read CPU temperature from Raspberry Pi thermal zone or simulate cooler temp."""
    thermal_file = Path("/sys/class/thermal/thermal_zone0/temp")
    if thermal_file.exists():
        try:
            with open(thermal_file, "r") as f:
                return round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass
    # Simulated Raspberry Pi 5 Active Cooler temperature (typically 42-48°C)
    base_temp = 43.5 + 2.0 * ((time.time() % 60) / 60.0)
    return round(base_temp, 1)


@app.get("/api/status")
async def get_system_status():
    storage_info = storage_mgr.get_storage_info()
    rec_status = recorder.get_status()
    gps_reading = gps_driver.get_latest()
    imu_reading = imu_driver.get_latest()

    return {
        "device": {
            "name": settings.hardware.device_name,
            "version": settings.hardware.firmware_version,
            "model": settings.hardware.hardware_model,
            "temperature_c": get_pi_temperature(),
            "uptime_sec": int(time.time() - recorder._session_start_time) if recorder._session_start_time > 0 else 0,
            "is_simulated": camera_driver.simulated,
        },
        "network": {
            "hotspot_ssid": settings.hardware.hotspot_ssid,
            "hotspot_ip": settings.hardware.hotspot_ip,
            "connected_clients": 1,
            "status": "Online (Direct AP)",
        },
        "storage": storage_info.__dict__,
        "recorder": rec_status.to_dict(),
        "camera": {
            "resolution": camera_driver.resolution_name,
            "framerate": camera_driver.framerate,
            "exposure_mode": camera_driver.exposure_mode,
            "digital_zoom": camera_driver.digital_zoom,
            "lens_hfov_deg": settings.camera.lens_hfov_deg,
        },
        "gps": gps_reading.to_dict(),
        "imu": imu_reading.to_dict(),
        "survey": settings.survey.model_dump(),
    }


# ---------------- CAMERA & STREAMING ---------------- #

@app.get("/api/camera/stream")
async def camera_preview_stream():
    """Low-latency multipart MJPEG preview stream for mobile browser."""
    return StreamingResponse(
        camera_driver.preview_stream_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/camera/snapshot")
async def camera_snapshot():
    """Capture instant JPEG snapshot."""
    jpeg_bytes = camera_driver.capture_snapshot()
    return Response(content=jpeg_bytes, media_type="image/jpeg")


class ZoomRequest(BaseModel):
    zoom: float


@app.post("/api/camera/zoom")
async def set_camera_zoom(req: ZoomRequest):
    camera_driver.set_digital_zoom(req.zoom)
    return {"status": "success", "zoom": camera_driver.digital_zoom}


class ExposureRequest(BaseModel):
    mode: str


@app.post("/api/camera/exposure")
async def set_camera_exposure(req: ExposureRequest):
    camera_driver.set_exposure_mode(req.mode)
    settings.camera.exposure_mode = req.mode  # type: ignore
    settings.save()
    return {"status": "success", "exposure_mode": req.mode}


# ---------------- RECORDER CONTROLS ---------------- #

@app.get("/api/recorder/status")
async def get_recorder_status():
    return recorder.get_status().to_dict()


@app.post("/api/recorder/start")
async def start_recording():
    success, message = recorder.start_recording()
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message, "recorder": recorder.get_status().to_dict()}


@app.post("/api/recorder/stop")
async def stop_recording():
    success, message = recorder.stop_recording()
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message, "recorder": recorder.get_status().to_dict()}


@app.post("/api/recorder/lock")
async def lock_active_recording():
    success, message = recorder.lock_current_recording()
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


@app.post("/api/recorder/snapshot")
async def take_snapshot_action():
    success, filename = recorder.capture_snapshot()
    if not success:
        raise HTTPException(status_code=500, detail=filename)
    return {"status": "success", "filename": filename}


class TestButtonRequest(BaseModel):
    action: str  # "click", "long_press", "double_click"


@app.post("/api/recorder/test-button")
async def test_gpio_button(req: TestButtonRequest):
    """Simulates physical button actions for testing & QA."""
    if req.action == "click":
        gpio_controller.simulate_button_click()
    elif req.action == "long_press":
        gpio_controller.simulate_button_long_press()
    elif req.action == "double_click":
        gpio_controller.simulate_button_double_click()
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
    return {"status": "success", "action": req.action}


# ---------------- GALLERY & DOWNLOADS ---------------- #

@app.get("/api/gallery")
async def get_gallery(filter: str = Query("all", enum=["all", "locked", "today"])):
    recordings = storage_mgr.list_recordings(filter_mode=filter)
    storage_info = storage_mgr.get_storage_info()
    return {
        "recordings": recordings,
        "count": len(recordings),
        "storage": storage_info.__dict__,
    }


@app.get("/api/gallery/{stem}/thumbnail")
async def get_recording_thumbnail(stem: str):
    thumb_bytes = storage_mgr.get_or_generate_thumbnail(stem)
    if not thumb_bytes:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return Response(content=thumb_bytes, media_type="image/jpeg")


@app.get("/api/gallery/{stem}/video")
async def stream_recording_video(stem: str):
    """Streams video file with byte-range support for mobile scrubbing."""
    video_path = storage_mgr.recordings_path / f"{stem}.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(video_path, media_type="video/mp4", filename=f"{stem}.mp4")


@app.get("/api/gallery/{stem}/download/{file_type}")
async def download_recording_asset(stem: str, file_type: str):
    """Download individual survey assets: mp4, gps, imu, or combined telemetry json."""
    file_map = {
        "mp4": (storage_mgr.recordings_path / f"{stem}.mp4", "video/mp4", f"{stem}.mp4"),
        "gps": (storage_mgr.recordings_path / f"{stem}_gps.csv", "text/csv", f"{stem}_gps.csv"),
        "imu": (storage_mgr.recordings_path / f"{stem}_imu.csv", "text/csv", f"{stem}_imu.csv"),
        "telemetry": (
            storage_mgr.recordings_path / f"{stem}_telemetry.json",
            "application/json",
            f"{stem}_telemetry.json",
        ),
    }

    if file_type not in file_map:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {file_type}")

    target_path, mime_type, filename = file_map[file_type]
    if not target_path.exists():
        raise HTTPException(status_code=404, detail=f"File {filename} not found.")

    return FileResponse(
        path=target_path,
        media_type=mime_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/gallery/{stem}/lock")
async def lock_gallery_item(stem: str):
    success = storage_mgr.lock_recording(stem)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to lock recording.")
    return {"status": "success", "stem": stem, "locked": True}


@app.post("/api/gallery/{stem}/unlock")
async def unlock_gallery_item(stem: str):
    success = storage_mgr.unlock_recording(stem)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to unlock recording.")
    return {"status": "success", "stem": stem, "locked": False}


@app.delete("/api/gallery/{stem}")
async def delete_gallery_item(stem: str):
    success, message = storage_mgr.delete_recording(stem)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"status": "success", "message": message}


# ---------------- TELEMETRY & CALIBRATION ---------------- #

@app.get("/api/telemetry/latest")
async def get_latest_telemetry():
    return {
        "gps": gps_driver.get_latest().to_dict(),
        "imu": imu_driver.get_latest().to_dict(),
    }


@app.post("/api/telemetry/calibrate")
async def calibrate_imu_sensor():
    res = imu_driver.calibrate()
    return res


class TestShockRequest(BaseModel):
    magnitude_g: float = 3.2


@app.post("/api/telemetry/test-shock")
async def trigger_test_shock(req: TestShockRequest):
    imu_driver.trigger_test_shock(req.magnitude_g)
    return {"status": "shock_triggered", "magnitude_g": req.magnitude_g}


# ---------------- SETTINGS ---------------- #

@app.get("/api/settings")
async def get_settings():
    return settings.model_dump()


@app.post("/api/settings")
async def update_settings(new_config: AppConfig):
    global settings
    settings = new_config
    settings.save()

    # Apply camera parameters
    camera_driver.exposure_mode = settings.camera.exposure_mode
    camera_driver.set_digital_zoom(settings.camera.digital_zoom)
    # Apply storage parameters
    storage_mgr.max_usage_percent = settings.storage.max_storage_usage_percent
    storage_mgr.low_warning_percent = settings.storage.low_storage_warning_percent
    # Apply IMU shock threshold
    imu_driver.shock_threshold_g = settings.storage.auto_lock_shock_g
    # Apply survey chainage
    gps_driver.start_chainage_km = settings.survey.chainage_km_start
    gps_driver.chainage_direction = settings.survey.chainage_direction

    return {"status": "success", "settings": settings.model_dump()}


# ---------------- SYSTEM POWER CONTROLS ---------------- #

@app.post("/api/system/reboot")
async def reboot_system():
    if platform.system() == "Linux":
        subprocess.Popen(["sudo", "reboot"])
    return {"status": "rebooting"}


@app.post("/api/system/shutdown")
async def shutdown_system():
    if platform.system() == "Linux":
        subprocess.Popen(["sudo", "shutdown", "-h", "now"])
    return {"status": "shutting_down"}


# ---------------- WEBSOCKET BROADCAST (10Hz) ---------------- #

class WebSocketManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: dict):
        if not self.active_connections:
            return
        # Send to all clients concurrently
        payload = json.dumps(data)
        stale = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception:
                stale.append(connection)
        for dead in stale:
            self.disconnect(dead)


ws_manager = WebSocketManager()


@app.websocket("/ws")
async def websocket_telemetry_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Gather high-frequency telemetry packet (10 Hz)
            payload = {
                "type": "telemetry",
                "timestamp_ms": int(time.time() * 1000),
                "recorder": recorder.get_status().to_dict(),
                "gps": gps_driver.get_latest().to_dict(),
                "imu": imu_driver.get_latest().to_dict(),
                "system": {
                    "temperature_c": get_pi_temperature(),
                    "storage": storage_mgr.get_storage_info().__dict__,
                },
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)  # 10 Hz refresh
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# ---------------- STATIC FRONTEND FILES (PWA) ---------------- #

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
