"""
Telemetry Logger for NHAI AI Road Survey Dashcam.
Synchronizes GPS, IMU, and Video frame telemetry into CSV and JSON formats.
"""

from __future__ import annotations
import csv
import json
import threading
import time
from pathlib import Path
from typing import Optional
from backend.core.hal.gps import GPSReading
from backend.core.hal.imu import IMUReading


class TelemetrySessionLogger:
    """Logs synchronized GPS and IMU streams for an active recording segment."""

    def __init__(
        self,
        base_filename_stem: str,
        output_dir: Path,
        project_metadata: dict,
        framerate: int = 30,
    ):
        self.stem = base_filename_stem
        self.output_dir = output_dir
        self.metadata = project_metadata
        self.framerate = framerate

        self.gps_csv_path = output_dir / f"{self.stem}_gps.csv"
        self.imu_csv_path = output_dir / f"{self.stem}_imu.csv"
        self.meta_json_path = output_dir / f"{self.stem}_meta.json"
        self.combined_json_path = output_dir / f"{self.stem}_telemetry.json"

        self._lock = threading.Lock()
        self._is_active = False
        self._start_epoch_ms = 0
        self._frame_counter = 0

        # File handles & CSV writers
        self._gps_file = None
        self._imu_file = None
        self._gps_writer = None
        self._imu_writer = None

        # In-memory samples for combined JSON export and statistics
        self._gps_records: list[dict] = []
        self._imu_records: list[dict] = []
        self._max_g_force = 1.0
        self._shock_events_count = 0

    def start(self) -> None:
        with self._lock:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._start_epoch_ms = int(time.time() * 1000)
            self._is_active = True

            # Open GPS CSV
            self._gps_file = open(self.gps_csv_path, "w", newline="", encoding="utf-8")
            self._gps_writer = csv.writer(self._gps_file)
            self._gps_writer.writerow([
                "timestamp_iso",
                "epoch_ms",
                "video_frame_approx",
                "latitude",
                "longitude",
                "altitude_m",
                "speed_kmh",
                "heading_deg",
                "satellites",
                "fix_type",
                "hdop",
                "chainage_km",
            ])
            self._gps_file.flush()

            # Open IMU CSV
            self._imu_file = open(self.imu_csv_path, "w", newline="", encoding="utf-8")
            self._imu_writer = csv.writer(self._imu_file)
            self._imu_writer.writerow([
                "timestamp_iso",
                "epoch_ms",
                "accel_x_g",
                "accel_y_g",
                "accel_z_g",
                "gyro_x_dps",
                "gyro_y_dps",
                "gyro_z_dps",
                "total_g",
                "pitch_deg",
                "roll_deg",
                "roughness_index",
            ])
            self._imu_file.flush()

            # Write initial metadata JSON
            self._write_meta_json(locked=False, duration_sec=0)

    def log_gps(self, reading: GPSReading) -> None:
        if not self._is_active:
            return
        with self._lock:
            if not self._gps_writer:
                return
            now_ms = int(time.time() * 1000)
            elapsed_sec = (now_ms - self._start_epoch_ms) / 1000.0
            approx_frame = int(elapsed_sec * self.framerate)

            row = [
                reading.timestamp_iso,
                reading.epoch_ms,
                approx_frame,
                reading.latitude,
                reading.longitude,
                reading.altitude_m,
                reading.speed_kmh,
                reading.heading_deg,
                reading.satellites,
                reading.fix_type,
                reading.hdop,
                reading.chainage_km,
            ]
            self._gps_writer.writerow(row)
            self._gps_file.flush()
            self._gps_records.append(reading.to_dict())

    def log_imu(self, reading: IMUReading) -> None:
        if not self._is_active:
            return
        with self._lock:
            if not self._imu_writer:
                return
            row = [
                reading.timestamp_iso,
                reading.epoch_ms,
                reading.accel_x_g,
                reading.accel_y_g,
                reading.accel_z_g,
                reading.gyro_x_dps,
                reading.gyro_y_dps,
                reading.gyro_z_dps,
                reading.total_g,
                reading.pitch_deg,
                reading.roll_deg,
                reading.roughness_index,
            ]
            self._imu_writer.writerow(row)
            self._imu_file.flush()

            if reading.total_g > self._max_g_force:
                self._max_g_force = reading.total_g
            if reading.shock_detected:
                self._shock_events_count += 1

            self._imu_records.append(reading.to_dict())

    def stop(self, locked: bool = False, duration_sec: float = 0.0) -> None:
        with self._lock:
            self._is_active = False

            if self._gps_file:
                try:
                    self._gps_file.flush()
                    self._gps_file.close()
                except Exception:
                    pass
                self._gps_file = None

            if self._imu_file:
                try:
                    self._imu_file.flush()
                    self._imu_file.close()
                except Exception:
                    pass
                self._imu_file = None

            # Finalize metadata
            self._write_meta_json(locked=locked, duration_sec=duration_sec)
            self._write_combined_telemetry_json(duration_sec=duration_sec)

    def update_locked_status(self, locked: bool) -> None:
        with self._lock:
            self._write_meta_json(locked=locked, duration_sec=0.0)

    def _write_meta_json(self, locked: bool, duration_sec: float) -> None:
        payload = {
            "stem": self.stem,
            "filename_video": f"{self.stem}.mp4",
            "filename_gps_csv": f"{self.stem}_gps.csv",
            "filename_imu_csv": f"{self.stem}_imu.csv",
            "filename_telemetry_json": f"{self.stem}_telemetry.json",
            "locked": locked,
            "duration_sec": round(duration_sec, 1),
            "start_time_iso": self.metadata.get("start_time_iso", ""),
            "highway_code": self.metadata.get("highway_code", "NH-44"),
            "project_name": self.metadata.get("project_name", "NHAI AI Survey"),
            "section_piu": self.metadata.get("section_piu", ""),
            "operator_name": self.metadata.get("operator_name", ""),
            "vehicle_registration": self.metadata.get("vehicle_registration", ""),
            "chainage_start_km": self.metadata.get("chainage_km_start", 0.0),
            "chainage_direction": self.metadata.get("chainage_direction", "Ascending"),
            "resolution": self.metadata.get("resolution", "1080p"),
            "framerate": self.framerate,
            "max_g_force": round(self._max_g_force, 2),
            "shock_events_count": self._shock_events_count,
            "gps_samples_count": len(self._gps_records),
            "imu_samples_count": len(self._imu_records),
        }
        try:
            with open(self.meta_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"[Telemetry] Meta JSON write error: {e}")

    def _write_combined_telemetry_json(self, duration_sec: float) -> None:
        """Export comprehensive combined telemetry JSON for GIS / AI defect processing."""
        payload = {
            "survey_session": self.metadata,
            "summary": {
                "duration_sec": round(duration_sec, 1),
                "max_g_force": round(self._max_g_force, 2),
                "shock_events_count": self._shock_events_count,
                "gps_samples": len(self._gps_records),
                "imu_samples": len(self._imu_records),
            },
            "gps_timeline": self._gps_records,
            "imu_timeline": self._imu_records,
        }
        try:
            with open(self.combined_json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"[Telemetry] Combined JSON write error: {e}")
