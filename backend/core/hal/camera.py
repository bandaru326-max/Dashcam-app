"""
Raspberry Pi HQ Camera (Sony IMX477) HAL Driver & Road Survey Scene Simulator.
Provides dual-stream pipeline (High-Res H.264 recording + Low-latency MJPEG preview)
and full simulated synthetic highway stream fallback.
"""

from __future__ import annotations
import io
import math
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional
from PIL import Image, ImageDraw, ImageFont


@dataclass
class CameraStatus:
    is_recording: bool = False
    current_resolution: str = "1080p"
    current_fps: int = 30
    exposure_mode: str = "auto"
    digital_zoom: float = 1.0
    preview_clients_count: int = 0
    hardware_active: bool = False


class CameraDriver:
    """Thread-safe dual-stream camera manager for Sony IMX477 HQ Camera."""

    RESOLUTIONS = {
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "1440p": (2560, 1440),
        "4k": (3840, 2160),
    }

    PREVIEW_RES = (640, 360)  # 16:9 optimized low-bandwidth mobile preview

    def __init__(
        self,
        resolution: str = "1080p",
        framerate: int = 30,
        bitrate_mbps: int = 15,
        exposure_mode: str = "auto",
        simulated: bool = False,
    ):
        self.resolution_name = resolution
        self.framerate = framerate
        self.bitrate_mbps = bitrate_mbps
        self.exposure_mode = exposure_mode
        self.simulated = simulated
        self.digital_zoom = 1.0

        self.width, self.height = self.RESOLUTIONS.get(resolution, (1920, 1080))
        self._lock = threading.Lock()
        self._running = False
        self._preview_thread: Optional[threading.Thread] = None
        self._current_jpeg_bytes: bytes = b""
        self._is_hardware = False
        self._picam2 = None

        # Simulated highway scene state
        self._sim_offset = 0.0
        self._last_frame_time = time.time()

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        if not self.simulated:
            self._try_init_hardware()

        # Start preview generator thread
        self._preview_thread = threading.Thread(
            target=self._preview_loop, daemon=True, name="CameraPreviewWorker"
        )
        self._preview_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._picam2:
            try:
                self._picam2.stop_recording()
                self._picam2.stop()
                self._picam2.close()
            except Exception:
                pass
        if self._preview_thread and self._preview_thread.is_alive():
            self._preview_thread.join(timeout=1.0)

    def _try_init_hardware(self) -> None:
        """Attempt to initialize picamera2 on Raspberry Pi 5."""
        try:
            from picamera2 import Picamera2
            picam2 = Picamera2()
            # Configure dual stream: main recording stream + preview stream
            config = picam2.create_video_configuration(
                main={"size": (self.width, self.height), "format": "YUV420"},
                lores={"size": self.PREVIEW_RES, "format": "RGB888"},
                controls={"FrameRate": self.framerate},
            )
            picam2.configure(config)
            self._set_picam_exposure(picam2, self.exposure_mode)
            picam2.start()
            self._picam2 = picam2
            self._is_hardware = True
            print(f"[Camera] Picamera2 initialized successfully for IMX477 ({self.width}x{self.height} @ {self.framerate}fps).")
        except Exception as e:
            print(f"[Camera] Picamera2 initialization failed: {e}. Running in high-fidelity road survey simulation mode.")
            self._is_hardware = False
            self.simulated = True

    def _set_picam_exposure(self, picam2, mode: str) -> None:
        try:
            from picamera2.controls import ExposureMode, AeMeteringMode
            if mode == "sports":
                picam2.set_controls({"AeExposureMode": 1, "ExposureTime": 5000})  # 1/200s for road motion
            elif mode == "night":
                picam2.set_controls({"AeExposureMode": 0, "AnalogueGain": 8.0})
            elif mode == "shutter_priority":
                picam2.set_controls({"ExposureTime": 10000})  # 1/100s
            else:
                picam2.set_controls({"AeExposureMode": 0})
        except Exception:
            pass

    def set_digital_zoom(self, zoom: float) -> None:
        with self._lock:
            self.digital_zoom = max(1.0, min(4.0, zoom))

    def set_exposure_mode(self, mode: str) -> None:
        with self._lock:
            self.exposure_mode = mode
            if self._picam2:
                self._set_picam_exposure(self._picam2, mode)

    def capture_snapshot(self, save_path: Optional[Path] = None) -> bytes:
        """Capture high-resolution still image."""
        if self._is_hardware and self._picam2:
            try:
                frame = self._picam2.capture_array("main")
                img = Image.fromarray(frame)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                jpeg_bytes = buf.getvalue()
                if save_path:
                    save_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(save_path, "wb") as f:
                        f.write(jpeg_bytes)
                return jpeg_bytes
            except Exception as e:
                print(f"[Camera] Hardware snapshot error: {e}")

        # Simulated high-res snapshot
        img = self._generate_simulated_road_frame(
            width=self.width, height=self.height, is_high_res=True
        )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        jpeg_bytes = buf.getvalue()
        if save_path:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            with open(save_path, "wb") as f:
                f.write(jpeg_bytes)
        return jpeg_bytes

    def get_latest_preview_frame(self) -> bytes:
        with self._lock:
            return self._current_jpeg_bytes

    def preview_stream_generator(self) -> Generator[bytes, None, None]:
        """Yield multipart MJPEG stream chunks for web streaming."""
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while self._running:
            frame_bytes = self.get_latest_preview_frame()
            if frame_bytes:
                yield boundary + frame_bytes + b"\r\n"
            time.sleep(1.0 / 15.0)  # 15 fps preview throttle to prevent mobile Wi-Fi saturation

    def _preview_loop(self) -> None:
        """Background loop updating latest JPEG frame."""
        while self._running:
            start_t = time.time()
            if self._is_hardware and self._picam2:
                try:
                    lores_frame = self._picam2.capture_array("lores")
                    img = Image.fromarray(lores_frame)
                    if self.digital_zoom > 1.0:
                        img = self._apply_zoom_crop(img, self.digital_zoom)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=75)
                    with self._lock:
                        self._current_jpeg_bytes = buf.getvalue()
                except Exception as e:
                    print(f"[Camera] Lores capture error: {e}")
                    time.sleep(0.1)
            else:
                img = self._generate_simulated_road_frame(
                    width=self.PREVIEW_RES[0], height=self.PREVIEW_RES[1], is_high_res=False
                )
                if self.digital_zoom > 1.0:
                    img = self._apply_zoom_crop(img, self.digital_zoom)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=75)
                with self._lock:
                    self._current_jpeg_bytes = buf.getvalue()

            elapsed = time.time() - start_t
            sleep_needed = (1.0 / 15.0) - elapsed
            if sleep_needed > 0:
                time.sleep(sleep_needed)

    def _apply_zoom_crop(self, img: Image.Image, zoom: float) -> Image.Image:
        w, h = img.size
        crop_w = int(w / zoom)
        crop_h = int(h / zoom)
        x1 = (w - crop_w) // 2
        y1 = (h - crop_h) // 2
        cropped = img.crop((x1, y1, x1 + crop_w, y1 + crop_h))
        return cropped.resize((w, h), Image.Resampling.BILINEAR)

    def _generate_simulated_road_frame(
        self, width: int, height: int, is_high_res: bool = False
    ) -> Image.Image:
        """Generate high-fidelity road survey camera frame (NHAI 4-lane highway perspective)."""
        now = time.time()
        self._sim_offset = (self._sim_offset + (now - self._last_frame_time) * 12.0) % 40.0
        self._last_frame_time = now

        img = Image.new("RGB", (width, height), color=(14, 20, 32))
        draw = ImageDraw.Draw(img)

        horizon_y = int(height * 0.46)

        # 1. Sky & distant landscape
        for y in range(0, horizon_y):
            ratio = y / horizon_y
            # Gradient from deep dusk blue to warm haze near horizon
            r = int(25 + ratio * 35)
            g = int(35 + ratio * 45)
            b = int(60 + ratio * 40)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Distant terrain / hills silhouette
        hills = [
            (0, horizon_y),
            (int(width * 0.15), horizon_y - int(height * 0.05)),
            (int(width * 0.35), horizon_y - int(height * 0.02)),
            (int(width * 0.5), horizon_y - int(height * 0.06)),
            (int(width * 0.75), horizon_y - int(height * 0.03)),
            (int(width * 0.9), horizon_y - int(height * 0.05)),
            (width, horizon_y),
        ]
        draw.polygon(hills, fill=(28, 38, 52))

        # 2. Road surface (perspective trapezoid)
        vanishing_x = width // 2
        vanishing_y = horizon_y

        left_bottom = int(width * 0.05)
        right_bottom = int(width * 0.95)
        left_top = vanishing_x - int(width * 0.04)
        right_top = vanishing_x + int(width * 0.04)

        # Road asphalt
        road_poly = [
            (left_top, vanishing_y),
            (right_top, vanishing_y),
            (right_bottom, height),
            (left_bottom, height),
        ]
        draw.polygon(road_poly, fill=(45, 48, 55))

        # Shoulders / greenery
        left_shoulder = [(0, vanishing_y), (left_top, vanishing_y), (left_bottom, height), (0, height)]
        right_shoulder = [(right_top, vanishing_y), (width, vanishing_y), (width, height), (right_bottom, height)]
        draw.polygon(left_shoulder, fill=(30, 42, 32))
        draw.polygon(right_shoulder, fill=(30, 42, 32))

        # 3. Road lane markings (center dashed lines and solid yellow edge lines)
        # Left edge line (white/yellow)
        draw.line([(left_top, vanishing_y), (left_bottom, height)], fill=(230, 230, 210), width=max(1, width // 320))
        # Right edge line (white/yellow)
        draw.line([(right_top, vanishing_y), (right_bottom, height)], fill=(230, 230, 210), width=max(1, width // 320))

        # Center dashed line with motion
        dash_steps = 14
        for i in range(dash_steps):
            t1 = (i * 3.0 + (self._sim_offset * 0.1)) % 15.0 / 15.0
            t2 = t1 + 0.04
            if t2 > 1.0 or t1 < 0.02:
                continue

            y_start = int(vanishing_y + (height - vanishing_y) * (t1**1.8))
            y_end = int(vanishing_y + (height - vanishing_y) * (t2**1.8))
            x_mid = vanishing_x

            w_stroke = max(1, int((y_end - vanishing_y) * 0.02))
            draw.line([(x_mid, y_start), (x_mid, y_end)], fill=(245, 245, 245), width=w_stroke)

        # 4. NHAI Highway Overhead Gantry / Mile Marker (every few seconds)
        gantry_cycle = (time.time() * 0.1) % 1.0
        if 0.2 < gantry_cycle < 0.9:
            gt = (gantry_cycle - 0.2) / 0.7  # 0 to 1
            gy = int(vanishing_y + (height - vanishing_y) * (gt**1.5))
            if gy < height - 20:
                gw = int(width * 0.65 * gt)
                gh = int(height * 0.3 * gt)
                gx1 = vanishing_x - gw // 2
                gx2 = vanishing_x + gw // 2
                draw.rectangle([(gx1, gy - gh), (gx2, gy - gh + max(2, int(10 * gt)))], fill=(16, 88, 56))  # NHAI Green sign
                # White sign border
                draw.rectangle([(gx1, gy - gh), (gx2, gy - gh + max(2, int(10 * gt)))], outline=(255, 255, 255), width=1)

        # 5. On-screen telemetry watermark
        ts_str = time.strftime("%Y-%m-%d %H:%M:%S IST")
        draw.rectangle([(10, 10), (min(width - 10, 360), 32)], fill=(0, 0, 0, 160))
        draw.text(
            (15, 14),
            f"NHAI AI SURVEY | {ts_str} | 4mm M12",
            fill=(255, 255, 255),
        )

        return img
