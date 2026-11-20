"""
MPU6050 6-DOF IMU HAL Driver & Simulator for NHAI Dashcam.
Handles 3-axis accelerometer and gyroscope sampling over I2C with zero-calibration and shock detection.
"""

from __future__ import annotations
import math
import random
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Optional, Callable

CALIBRATION_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "imu_calib.json"


@dataclass
class IMUReading:
    timestamp_iso: str = ""
    epoch_ms: int = 0
    accel_x_g: float = 0.0
    accel_y_g: float = 0.0
    accel_z_g: float = 1.0
    gyro_x_dps: float = 0.0
    gyro_y_dps: float = 0.0
    gyro_z_dps: float = 0.0
    total_g: float = 1.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    roughness_index: float = 0.0  # RMS variance of vertical acceleration (road condition metric)
    shock_detected: bool = False
    calibrated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class IMUDriver:
    """Thread-safe MPU6050 driver with real-time shock detection and simulated fallback."""

    # MPU6050 Register Map
    PWR_MGMT_1 = 0x6B
    SMPLRT_DIV = 0x19
    CONFIG = 0x1A
    GYRO_CONFIG = 0x1B
    ACCEL_CONFIG = 0x1C
    ACCEL_XOUT_H = 0x3B
    TEMP_OUT_H = 0x41
    GYRO_XOUT_H = 0x43

    # Scale Factors (for ±4g and ±500 deg/s)
    ACCEL_SCALE_4G = 8192.0  # LSB / g
    GYRO_SCALE_500DPS = 65.5  # LSB / (deg/s)

    def __init__(
        self,
        i2c_bus: int = 1,
        i2c_address: int = 0x68,
        simulated: bool = False,
        shock_threshold_g: float = 2.5,
        on_shock_callback: Optional[Callable[[float], None]] = None,
    ):
        self.i2c_bus_num = i2c_bus
        self.i2c_address = i2c_address
        self.simulated = simulated
        self.shock_threshold_g = shock_threshold_g
        self.on_shock_callback = on_shock_callback

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_reading = IMUReading()

        # Calibration offsets
        self.offset_ax = 0.0
        self.offset_ay = 0.0
        self.offset_az = 0.0
        self.offset_gx = 0.0
        self.offset_gy = 0.0
        self.offset_gz = 0.0
        self.calibrated = False
        self._load_calibration()

        # Rolling window for roughness calculation (last 20 samples)
        self._z_history: list[float] = []

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="IMUWorker")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def get_latest(self) -> IMUReading:
        with self._lock:
            return self._latest_reading

    def calibrate(self, num_samples: int = 50) -> dict:
        """Calibrate zero-offsets while vehicle is stationary on level surface."""
        print("[IMU] Starting zero-point calibration...")
        samples_ax, samples_ay, samples_az = [], [], []
        samples_gx, samples_gy, samples_gz = [], [], []

        for _ in range(num_samples):
            reading = self.get_latest()
            samples_ax.append(reading.accel_x_g + self.offset_ax)
            samples_ay.append(reading.accel_y_g + self.offset_ay)
            samples_az.append(reading.accel_z_g + self.offset_az)
            samples_gx.append(reading.gyro_x_dps + self.offset_gx)
            samples_gy.append(reading.gyro_y_dps + self.offset_gy)
            samples_gz.append(reading.gyro_z_dps + self.offset_gz)
            time.sleep(0.02)

        # Level ground expects X=0g, Y=0g, Z=1.0g; Gyros=0 dps
        self.offset_ax = sum(samples_ax) / len(samples_ax)
        self.offset_ay = sum(samples_ay) / len(samples_ay)
        self.offset_az = (sum(samples_az) / len(samples_az)) - 1.0
        self.offset_gx = sum(samples_gx) / len(samples_gx)
        self.offset_gy = sum(samples_gy) / len(samples_gy)
        self.offset_gz = sum(samples_gz) / len(samples_gz)
        self.calibrated = True

        self._save_calibration()
        return {
            "status": "success",
            "offsets": {
                "ax": round(self.offset_ax, 4),
                "ay": round(self.offset_ay, 4),
                "az": round(self.offset_az, 4),
                "gx": round(self.offset_gx, 4),
                "gy": round(self.offset_gy, 4),
                "gz": round(self.offset_gz, 4),
            },
        }

    def trigger_test_shock(self, g_magnitude: float = 3.2) -> None:
        """Manually trigger a simulated road shock for testing."""
        if self.on_shock_callback:
            self.on_shock_callback(g_magnitude)

    def _worker_loop(self) -> None:
        bus = None
        if not self.simulated:
            try:
                import smbus2
                bus = smbus2.SMBus(self.i2c_bus_num)
                # Wake up MPU6050
                bus.write_byte_data(self.i2c_address, self.PWR_MGMT_1, 0x00)
                time.sleep(0.05)
                # Set DLPF to 44Hz filter
                bus.write_byte_data(self.i2c_address, self.CONFIG, 0x03)
                # Set Gyro to ±500 deg/s
                bus.write_byte_data(self.i2c_address, self.GYRO_CONFIG, 0x08)
                # Set Accel to ±4g
                bus.write_byte_data(self.i2c_address, self.ACCEL_CONFIG, 0x08)
                print(f"[IMU] MPU6050 initialized on I2C bus {self.i2c_bus_num} (0x{self.i2c_address:02x}).")
            except Exception as e:
                print(f"[IMU] Could not open MPU6050: {e}. Switching to simulated IMU.")
                self.simulated = True

        while self._running:
            if self.simulated or bus is None:
                self._update_simulated()
                time.sleep(0.05)  # 20 Hz IMU update
            else:
                try:
                    # Read 14 bytes: 6 accel, 2 temp, 6 gyro
                    data = bus.read_i2c_block_data(self.i2c_address, self.ACCEL_XOUT_H, 14)
                    raw_ax = self._to_int16(data[0], data[1])
                    raw_ay = self._to_int16(data[2], data[3])
                    raw_az = self._to_int16(data[4], data[5])
                    raw_gx = self._to_int16(data[8], data[9])
                    raw_gy = self._to_int16(data[10], data[11])
                    raw_gz = self._to_int16(data[12], data[13])

                    ax = (raw_ax / self.ACCEL_SCALE_4G) - self.offset_ax
                    ay = (raw_ay / self.ACCEL_SCALE_4G) - self.offset_ay
                    az = (raw_az / self.ACCEL_SCALE_4G) - self.offset_az
                    gx = (raw_gx / self.GYRO_SCALE_500DPS) - self.offset_gx
                    gy = (raw_gy / self.GYRO_SCALE_500DPS) - self.offset_gy
                    gz = (raw_gz / self.GYRO_SCALE_500DPS) - self.offset_gz

                    self._process_reading(ax, ay, az, gx, gy, gz)
                    time.sleep(0.05)
                except Exception as e:
                    print(f"[IMU] I2C read error: {e}")
                    time.sleep(0.2)

        if bus:
            try:
                bus.close()
            except Exception:
                pass

    def _process_reading(
        self, ax: float, ay: float, az: float, gx: float, gy: float, gz: float
    ) -> None:
        total_g = math.sqrt(ax**2 + ay**2 + az**2)

        # Calculate Pitch (forward/back tilt) and Roll (left/right tilt)
        pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
        roll = math.degrees(math.atan2(ay, az if az != 0 else 0.0001))

        # Update roughness sliding window
        self._z_history.append(az)
        if len(self._z_history) > 20:
            self._z_history.pop(0)

        mean_z = sum(self._z_history) / len(self._z_history)
        roughness = math.sqrt(sum((z - mean_z) ** 2 for z in self._z_history) / len(self._z_history)) * 100.0

        # Check for shock / pothole
        shock = total_g >= self.shock_threshold_g
        if shock and self.on_shock_callback:
            try:
                self.on_shock_callback(total_g)
            except Exception as e:
                print(f"[IMU] Shock callback error: {e}")

        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        epoch_ms = int(now_utc.timestamp() * 1000)

        with self._lock:
            self._latest_reading = IMUReading(
                timestamp_iso=iso_str,
                epoch_ms=epoch_ms,
                accel_x_g=round(ax, 3),
                accel_y_g=round(ay, 3),
                accel_z_g=round(az, 3),
                gyro_x_dps=round(gx, 2),
                gyro_y_dps=round(gy, 2),
                gyro_z_dps=round(gz, 2),
                total_g=round(total_g, 2),
                pitch_deg=round(pitch, 1),
                roll_deg=round(roll, 1),
                roughness_index=round(roughness, 2),
                shock_detected=shock,
                calibrated=self.calibrated,
            )

    def _update_simulated(self) -> None:
        t = time.time()
        # Highway cruising vibration: 1g gravity on Z, small vehicle oscillations
        noise = lambda scale: (random.random() - 0.5) * scale

        # Base engine / pavement vibration
        ax = 0.03 * math.sin(t * 1.2) + noise(0.04)
        ay = 0.02 * math.sin(t * 0.8) + noise(0.03)
        az = 1.0 + 0.05 * math.sin(t * 2.5) + noise(0.06)

        # Occasional road expansion joint or bump every ~15 seconds
        if int(t) % 15 == 0 and (t - int(t)) < 0.2:
            bump = 0.45 * math.sin((t - int(t)) * math.pi * 5)
            az += bump
            ax += bump * 0.3

        gx = 0.8 * math.sin(t * 0.5) + noise(0.4)
        gy = 0.6 * math.cos(t * 0.7) + noise(0.4)
        gz = 1.2 * math.sin(t * 0.2) + noise(0.3)

        self._process_reading(ax, ay, az, gx, gy, gz)

    @staticmethod
    def _to_int16(high: int, low: int) -> int:
        val = (high << 8) | low
        return val - 65536 if val > 32767 else val

    def _load_calibration(self) -> None:
        if CALIBRATION_FILE.exists():
            try:
                with open(CALIBRATION_FILE, "r") as f:
                    data = json.load(f)
                self.offset_ax = data.get("ax", 0.0)
                self.offset_ay = data.get("ay", 0.0)
                self.offset_az = data.get("az", 0.0)
                self.offset_gx = data.get("gx", 0.0)
                self.offset_gy = data.get("gy", 0.0)
                self.offset_gz = data.get("gz", 0.0)
                self.calibrated = True
                print("[IMU] Loaded stored calibration offsets.")
            except Exception:
                pass

    def _save_calibration(self) -> None:
        try:
            CALIBRATION_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CALIBRATION_FILE, "w") as f:
                json.dump(
                    {
                        "ax": self.offset_ax,
                        "ay": self.offset_ay,
                        "az": self.offset_az,
                        "gx": self.offset_gx,
                        "gy": self.offset_gy,
                        "gz": self.offset_gz,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            print(f"[IMU] Error saving calibration: {e}")
