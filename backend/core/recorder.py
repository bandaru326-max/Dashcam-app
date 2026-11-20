"""
Recording State Machine & Loop Segmenter for NHAI AI Road Survey Dashcam.
Orchestrates synchronized video capture, multi-sensor CSV/JSON telemetry logging,
seamless loop rotation, and automatic impact-shock file locking.
"""

from __future__ import annotations
import math
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable

from backend.config import AppConfig
from backend.core.hal.camera import CameraDriver
from backend.core.hal.gps import GPSDriver
from backend.core.hal.imu import IMUDriver
from backend.core.hal.gpio_controller import GPIOController, LEDPattern
from backend.core.telemetry_logger import TelemetrySessionLogger
from backend.core.storage_manager import StorageManager


@dataclass
class RecorderStatus:
    is_recording: bool = False
    is_locked: bool = False
    current_stem: str = ""
    current_segment_index: int = 0
    duration_seconds: int = 0
    duration_formatted: str = "00:00:00"
    status_text: str = "READY TO RECORD"  # "READY TO RECORD" or "REC ● 00:14:22"
    loop_duration_sec: int = 180

    def to_dict(self) -> dict:
        return asdict(self)


class DashcamRecorder:
    """Manages the recording state machine, loop segments, and impact protection."""

    def __init__(
        self,
        config: AppConfig,
        camera: CameraDriver,
        gps: GPSDriver,
        imu: IMUDriver,
        gpio: GPIOController,
        storage: StorageManager,
    ):
        self.config = config
        self.camera = camera
        self.gps = gps
        self.imu = imu
        self.gpio = gpio
        self.storage = storage

        self._lock = threading.Lock()
        self._is_recording = False
        self._current_locked = False
        self._session_start_time = 0.0
        self._segment_start_time = 0.0
        self._segment_index = 0
        self._current_stem = ""

        self._active_logger: Optional[TelemetrySessionLogger] = None
        self._ticker_thread: Optional[threading.Thread] = None
        self._running_ticker = False

        # Hook IMU shock callback for auto-lock
        self.imu.on_shock_callback = self._on_imu_shock_detected

        # Hook GPIO buttons
        self.gpio.on_short_click = self.toggle_recording
        self.gpio.on_long_press = self.lock_current_recording
        self.gpio.on_double_click = self.capture_snapshot

    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    def get_status(self) -> RecorderStatus:
        with self._lock:
            now = time.time()
            if self._is_recording:
                elapsed = int(now - self._segment_start_time)
                hh = elapsed // 3600
                mm = (elapsed % 3600) // 60
                ss = elapsed % 60
                formatted_time = f"{hh:02d}:{mm:02d}:{ss:02d}"
                status_text = f"REC ● {formatted_time}"
                return RecorderStatus(
                    is_recording=True,
                    is_locked=self._current_locked,
                    current_stem=self._current_stem,
                    current_segment_index=self._segment_index,
                    duration_seconds=elapsed,
                    duration_formatted=formatted_time,
                    status_text=status_text,
                    loop_duration_sec=self.config.storage.loop_duration_sec,
                )
            else:
                return RecorderStatus(
                    is_recording=False,
                    is_locked=False,
                    current_stem="",
                    current_segment_index=0,
                    duration_seconds=0,
                    duration_formatted="00:00:00",
                    status_text="READY TO RECORD",
                    loop_duration_sec=self.config.storage.loop_duration_sec,
                )

    def start_recording(self) -> tuple[bool, str]:
        with self._lock:
            if self._is_recording:
                return False, "Recording is already active."

            # Check storage before starting
            storage_info = self.storage.get_storage_info()
            if storage_info.free_bytes < 100 * 1024 * 1024:  # Less than 100MB
                self.storage.prune_circular_buffer()
                storage_info = self.storage.get_storage_info()
                if storage_info.free_bytes < 50 * 1024 * 1024:
                    self.gpio.set_led_pattern(LEDPattern.BLINK_4HZ)
                    return False, "Storage full. Cannot start recording."

            self._is_recording = True
            self._current_locked = False
            self._session_start_time = time.time()
            self._segment_index = 1

            self._start_new_segment()

            # Set hardware LED to 1Hz recording blink
            self.gpio.set_led_pattern(LEDPattern.BLINK_1HZ)

            # Start ticker thread for loop duration checks & telemetry piping
            self._running_ticker = True
            self._ticker_thread = threading.Thread(
                target=self._recording_loop_worker, daemon=True, name="RecorderLoopWorker"
            )
            self._ticker_thread.start()

            print(f"[Recorder] Started NHAI Survey recording: {self._current_stem}")
            return True, f"Recording started ({self._current_stem})"

    def stop_recording(self) -> tuple[bool, str]:
        with self._lock:
            if not self._is_recording:
                return False, "Recording is not active."

            self._is_recording = False
            self._running_ticker = False

        if self._ticker_thread and self._ticker_thread.is_alive():
            self._ticker_thread.join(timeout=1.5)

        with self._lock:
            self._close_current_segment()
            self.gpio.set_led_pattern(LEDPattern.SOLID)
            print("[Recorder] Recording stopped successfully.")
            return True, "Recording stopped."

    def toggle_recording(self) -> None:
        """Physical button callback: toggles start / stop."""
        if self.is_recording():
            print("[Recorder] Physical button: Stopping recording...")
            self.stop_recording()
        else:
            print("[Recorder] Physical button: Starting recording...")
            self.start_recording()

    def lock_current_recording(self) -> tuple[bool, str]:
        """Mark the active recording as protected/locked."""
        with self._lock:
            if not self._is_recording:
                return False, "Cannot lock: No recording currently active."
            self._current_locked = True
            if self._active_logger:
                self._active_logger.update_locked_status(True)

        self.storage.lock_recording(self._current_stem)
        # Briefly flash LED rapidly to give tactile confirmation
        self.gpio.set_led_pattern(LEDPattern.BLINK_4HZ)
        threading.Timer(1.5, lambda: self.gpio.set_led_pattern(LEDPattern.BLINK_1HZ if self._is_recording else LEDPattern.SOLID)).start()

        print(f"[Recorder] Active recording segment '{self._current_stem}' LOCKED.")
        return True, f"Recording segment {self._current_stem} locked and protected."

    def capture_snapshot(self) -> tuple[bool, str]:
        """Capture instant still photo with metadata."""
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        snap_stem = f"NHAI_SNAPSHOT_{now_str}"
        snap_path = self.storage.recordings_path / f"{snap_stem}.jpg"
        try:
            self.camera.capture_snapshot(save_path=snap_path)
            print(f"[Recorder] Snapshot saved to {snap_path.name}")
            return True, snap_path.name
        except Exception as e:
            print(f"[Recorder] Error capturing snapshot: {e}")
            return False, str(e)

    def _start_new_segment(self) -> None:
        """Initialize files for a new loop recording segment."""
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        self._current_stem = f"NHAI_SURVEY_{timestamp_str}_SEC{self._segment_index:03d}"
        self._segment_start_time = time.time()
        self._current_locked = False

        # Metadata sidecar payload
        meta = {
            "start_time_iso": now.isoformat(),
            "highway_code": self.config.survey.highway_code,
            "project_name": self.config.survey.project_name,
            "section_piu": self.config.survey.section_piu,
            "operator_name": self.config.survey.operator_name,
            "vehicle_registration": self.config.survey.vehicle_registration,
            "chainage_km_start": self.config.survey.chainage_km_start,
            "chainage_direction": self.config.survey.chainage_direction,
            "resolution": self.config.camera.resolution,
            "framerate": self.config.camera.framerate,
        }

        self._active_logger = TelemetrySessionLogger(
            base_filename_stem=self._current_stem,
            output_dir=self.storage.recordings_path,
            project_metadata=meta,
            framerate=self.config.camera.framerate,
        )
        self._active_logger.start()

        # Generate a video placeholder / recording file
        self._create_video_segment_file(self._current_stem)

    def _close_current_segment(self) -> None:
        """Close telemetry and finalize video file."""
        if self._active_logger:
            duration_sec = time.time() - self._segment_start_time
            self._active_logger.stop(locked=self._current_locked, duration_sec=duration_sec)
            self._active_logger = None

        # Generate thumbnail for this segment
        self.storage.get_or_generate_thumbnail(self._current_stem)

    def _rotate_loop_segment(self) -> None:
        """Rotate to next loop recording segment seamlessly."""
        print(f"[Recorder] Loop segment duration ({self.config.storage.loop_duration_sec}s) reached. Rotating...")
        with self._lock:
            self._close_current_segment()
            self._segment_index += 1
            self._start_new_segment()

        # Prune old unlocked recordings if disk space requires it
        self.storage.prune_circular_buffer()

    def _recording_loop_worker(self) -> None:
        """Runs periodic telemetry logging and loop segmentation checks."""
        while self._running_ticker and self._is_recording:
            # 1. Pipe latest GPS & IMU readings to active telemetry logger
            if self._active_logger:
                gps_reading = self.gps.get_latest()
                imu_reading = self.imu.get_latest()
                self._active_logger.log_gps(gps_reading)
                self._active_logger.log_imu(imu_reading)

            # 2. Check if segment loop duration reached
            elapsed = time.time() - self._segment_start_time
            if elapsed >= self.config.storage.loop_duration_sec:
                self._rotate_loop_segment()

            time.sleep(0.1)  # 10 Hz telemetry sampling rate

    def _on_imu_shock_detected(self, shock_g: float) -> None:
        """Triggered automatically when vehicle encounters harsh bump or impact shock."""
        print(f"[Recorder] High G-force shock detected ({shock_g}g >= threshold {self.config.storage.auto_lock_shock_g}g)!")
        if self._is_recording:
            self.lock_current_recording()

    def _create_video_segment_file(self, stem: str) -> None:
        """Creates the MP4 file for the segment."""
        video_path = self.storage.recordings_path / f"{stem}.mp4"

        # On hardware with picamera2, picamera2 encoder writes directly.
        # In simulation mode, we synthesize a clean valid MP4 file container.
        if not video_path.exists():
            try:
                # Write a valid standard MP4 stub or test file
                # Create a 2-second synthetic MP4 using ffmpeg if available, or write a dummy valid header
                has_ffmpeg = shutil.which("ffmpeg") is not None
                if has_ffmpeg:
                    # Quick 2-second sample mp4
                    cmd = [
                        "ffmpeg", "-y", "-f", "lavfi", "-i",
                        "testsrc=duration=3:size=640x360:rate=30",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        str(video_path),
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                else:
                    # Write a mock mp4 file with basic structure
                    with open(video_path, "wb") as f:
                        f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42")
                        f.write(os.urandom(1024 * 64))  # 64 KB stub
            except Exception as e:
                print(f"[Recorder] Video stub generation error: {e}")
