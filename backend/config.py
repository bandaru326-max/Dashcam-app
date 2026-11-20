"""
Configuration module for NHAI AI Road Survey Dashcam.
Handles device settings, camera parameters, survey metadata, and persistence.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

CONFIG_FILE_PATH = Path(__file__).resolve().parent / "data" / "config.json"


class CameraConfig(BaseModel):
    resolution: Literal["720p", "1080p", "1440p", "4k"] = "1080p"
    framerate: int = Field(default=30, ge=15, le=60)
    bitrate_mbps: int = Field(default=15, ge=5, le=50)
    exposure_mode: Literal["auto", "sports", "night", "shutter_priority"] = "auto"
    white_balance: Literal["auto", "daylight", "cloudy", "tungsten"] = "auto"
    lens_focal_length_mm: float = 4.0
    lens_hfov_deg: float = 76.3
    preview_resolution: str = "640x360"
    preview_framerate: int = 15
    digital_zoom: float = Field(default=1.0, ge=1.0, le=4.0)


class SurveyConfig(BaseModel):
    project_name: str = "NHAI Road Surface AI Survey"
    highway_code: str = "NH-44"
    section_piu: str = "PIU North-South Corridor"
    operator_name: str = "Field Survey Team 1"
    vehicle_registration: str = "IND-NHAI-01"
    chainage_km_start: float = 120.000
    chainage_direction: Literal["Ascending", "Descending"] = "Ascending"
    overlay_watermark: bool = True


class StorageConfig(BaseModel):
    storage_path: str = "./recordings"
    loop_duration_sec: int = Field(default=180, ge=60, le=900)  # 3 min default
    auto_start_on_boot: bool = False
    auto_lock_shock_g: float = Field(default=2.5, ge=1.2, le=5.0)
    low_storage_warning_percent: int = Field(default=15, ge=5, le=30)
    auto_delete_old_unlocked: bool = True
    max_storage_usage_percent: int = Field(default=90, ge=50, le=98)


class HardwareConfig(BaseModel):
    device_name: str = "NHAI-SurveyCam-01"
    firmware_version: str = "2.4.0-nhai"
    hardware_model: str = "Raspberry Pi 5 (4GB) + Sony IMX477 HQ"
    gpio_button_pin: int = 17
    gpio_led_pin: int = 22
    gps_port: str = "/dev/ttyAMA0"
    gps_baudrate: int = 9600
    imu_i2c_bus: int = 1
    imu_i2c_address: int = 0x68
    hotspot_ssid: str = "PiDashcam-01"
    hotspot_ip: str = "192.168.4.1"
    simulated_mode: bool = False  # Auto-detects if Pi hardware not present


class AppConfig(BaseModel):
    camera: CameraConfig = Field(default_factory=CameraConfig)
    survey: SurveyConfig = Field(default_factory=SurveyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)

    def save(self, filepath: Path | None = None) -> None:
        target = filepath or CONFIG_FILE_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, filepath: Path | None = None) -> AppConfig:
        target = filepath or CONFIG_FILE_PATH
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return cls(**data)
            except Exception as e:
                print(f"[Config] Error loading existing config: {e}. Using defaults.")
        conf = cls()
        conf.save(target)
        return conf


# Global singleton configuration
settings = AppConfig.load()
