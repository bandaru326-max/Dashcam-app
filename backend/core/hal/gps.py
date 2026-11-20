"""
NEO-M8N GPS HAL Driver & Simulator for NHAI Dashcam.
Parses NMEA sentences from hardware UART or generates realistic Indian highway survey tracks.
"""

from __future__ import annotations
import math
import re
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class GPSReading:
    timestamp_iso: str = ""
    epoch_ms: int = 0
    latitude: float = 0.0
    longitude: float = 0.0
    altitude_m: float = 0.0
    speed_kmh: float = 0.0
    heading_deg: float = 0.0
    satellites: int = 0
    fix_type: str = "No Fix"  # "No Fix", "Searching", "2D Fix", "3D Fix"
    hdop: float = 99.9
    chainage_km: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


class GPSDriver:
    """Thread-safe GPS driver supporting hardware UART and high-fidelity simulation."""

    def __init__(
        self,
        port: str = "/dev/ttyAMA0",
        baudrate: int = 9600,
        simulated: bool = False,
        start_chainage_km: float = 120.000,
        chainage_direction: str = "Ascending",
    ):
        self.port = port
        self.baudrate = baudrate
        self.simulated = simulated
        self.start_chainage_km = start_chainage_km
        self.chainage_direction = chainage_direction

        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._latest_reading = GPSReading()

        # Simulation state (NH-44 Corridor: Agra to Dholpur/Gwalior)
        self._sim_lat = 27.1767  # Near Agra Outer Ring Road
        self._sim_lon = 78.0081
        self._sim_speed_kmh = 68.5
        self._sim_heading = 175.0  # Southbound
        self._sim_altitude = 169.0
        self._sim_satellites = 14
        self._sim_hdop = 0.85
        self._distance_traveled_km = 0.0
        self._last_sim_time = time.time()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="GPSWorker")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def get_latest(self) -> GPSReading:
        with self._lock:
            return self._latest_reading

    def _worker_loop(self) -> None:
        serial_conn = None
        if not self.simulated:
            try:
                import serial
                serial_conn = serial.Serial(self.port, self.baudrate, timeout=1.0)
                print(f"[GPS] Connected to hardware UART on {self.port} at {self.baudrate} baud.")
            except Exception as e:
                print(f"[GPS] Could not open {self.port}: {e}. Falling back to simulation mode.")
                self.simulated = True

        while self._running:
            if self.simulated or serial_conn is None:
                self._update_simulated()
                time.sleep(0.1)  # 10 Hz telemetry loop
            else:
                try:
                    line = serial_conn.readline().decode("ascii", errors="replace").strip()
                    if line.startswith("$"):
                        self._parse_nmea(line)
                except Exception as e:
                    print(f"[GPS] Serial read error: {e}")
                    time.sleep(0.5)

        if serial_conn:
            try:
                serial_conn.close()
            except Exception:
                pass

    def _parse_nmea(self, sentence: str) -> None:
        """Parse NMEA sentences ($GPRMC, $GPGGA, $GPVTG, $GPGSA)."""
        parts = sentence.split(",")
        if not parts:
            return
        header = parts[0][3:]  # strip $GP or $GN

        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        epoch_ms = int(now_utc.timestamp() * 1000)

        with self._lock:
            reading = self._latest_reading
            reading.timestamp_iso = iso_str
            reading.epoch_ms = epoch_ms

            if header == "RMC" and len(parts) >= 10:
                # Status: A=valid, V=void
                status = parts[2]
                if status == "A":
                    lat = self._nmea_to_decimal(parts[3], parts[4])
                    lon = self._nmea_to_decimal(parts[5], parts[6])
                    speed_knots = float(parts[7]) if parts[7] else 0.0
                    heading = float(parts[8]) if parts[8] else 0.0

                    if lat is not None:
                        reading.latitude = lat
                    if lon is not None:
                        reading.longitude = lon
                    reading.speed_kmh = round(speed_knots * 1.852, 1)
                    reading.heading_deg = round(heading, 1)

            elif header == "GGA" and len(parts) >= 10:
                quality = parts[6]
                satellites = int(parts[7]) if parts[7] else 0
                hdop = float(parts[8]) if parts[8] else 99.9
                altitude = float(parts[9]) if parts[9] else 0.0

                reading.satellites = satellites
                reading.hdop = round(hdop, 2)
                reading.altitude_m = round(altitude, 1)

                if quality in ("1", "2"):
                    reading.fix_type = "3D Fix" if satellites >= 4 else "2D Fix"
                elif quality == "0":
                    reading.fix_type = "Searching" if satellites > 0 else "No Fix"

            elif header == "GSA" and len(parts) >= 3:
                mode = parts[2]
                if mode == "1":
                    reading.fix_type = "No Fix"
                elif mode == "2":
                    reading.fix_type = "2D Fix"
                elif mode == "3":
                    reading.fix_type = "3D Fix"

            elif header == "VTG" and len(parts) >= 8:
                speed_kmh = float(parts[7]) if parts[7] else 0.0
                reading.speed_kmh = round(speed_kmh, 1)

            # Update chainage
            delta_chainage = self._distance_traveled_km
            if self.chainage_direction == "Ascending":
                reading.chainage_km = round(self.start_chainage_km + delta_chainage, 3)
            else:
                reading.chainage_km = round(self.start_chainage_km - delta_chainage, 3)

    def _update_simulated(self) -> None:
        now = time.time()
        dt = now - self._last_sim_time
        self._last_sim_time = now

        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        epoch_ms = int(now_utc.timestamp() * 1000)

        # Smooth highway driving dynamics (speed between 55 and 82 km/h, road curves)
        t = now * 0.2
        target_speed = 68.0 + 12.0 * math.sin(t * 0.3) + 3.0 * math.sin(t * 1.5)
        self._sim_speed_kmh += (target_speed - self._sim_speed_kmh) * min(dt * 0.8, 1.0)
        self._sim_speed_kmh = max(35.0, min(95.0, self._sim_speed_kmh))

        # Heading gently fluctuates around 175° (southbound)
        self._sim_heading = 175.0 + 8.0 * math.sin(t * 0.1)

        # Convert speed to distance
        speed_mps = (self._sim_speed_kmh * 1000.0) / 3600.0
        distance_m = speed_mps * dt
        self._distance_traveled_km += distance_m / 1000.0

        # Move lat / lon on Earth sphere
        heading_rad = math.radians(self._sim_heading)
        # 1 deg lat ~ 111,000 meters
        delta_lat = (distance_m * math.cos(heading_rad)) / 111000.0
        delta_lon = (distance_m * math.sin(heading_rad)) / (
            111000.0 * math.cos(math.radians(self._sim_lat))
        )

        self._sim_lat += delta_lat
        self._sim_lon += delta_lon

        # Altitude slight gradient
        self._sim_altitude = 169.0 + 5.0 * math.sin(t * 0.05)

        with self._lock:
            chainage = (
                self.start_chainage_km + self._distance_traveled_km
                if self.chainage_direction == "Ascending"
                else self.start_chainage_km - self._distance_traveled_km
            )

            self._latest_reading = GPSReading(
                timestamp_iso=iso_str,
                epoch_ms=epoch_ms,
                latitude=round(self._sim_lat, 6),
                longitude=round(self._sim_lon, 6),
                altitude_m=round(self._sim_altitude, 1),
                speed_kmh=round(self._sim_speed_kmh, 1),
                heading_deg=round(self._sim_heading, 1),
                satellites=self._sim_satellites,
                fix_type="3D Fix",
                hdop=self._sim_hdop,
                chainage_km=round(chainage, 3),
            )

    @staticmethod
    def _nmea_to_decimal(coord_str: str, dir_char: str) -> Optional[float]:
        """Convert NMEA ddmm.mmmm format to decimal degrees."""
        if not coord_str or not dir_char:
            return None
        try:
            dot_pos = coord_str.find(".")
            if dot_pos < 2:
                return None
            deg = float(coord_str[: dot_pos - 2])
            minutes = float(coord_str[dot_pos - 2 :])
            decimal = deg + (minutes / 60.0)
            if dir_char in ("S", "W"):
                decimal = -decimal
            return round(decimal, 6)
        except Exception:
            return None
