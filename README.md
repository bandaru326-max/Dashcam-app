# Custom NHAI AI Road Survey Dashcam System

A complete, modern, mobile-first dashcam control application and Raspberry Pi 5 backend system engineered for real-world National Highways Authority of India (NHAI) AI road condition surveys.

---

## 1. System Hardware Architecture

| Component | Specification | Connection Interface |
| :--- | :--- | :--- |
| **SBC** | Raspberry Pi 5 (4GB RAM) + Active Cooler | Host System |
| **Camera** | Raspberry Pi HQ Camera (Sony IMX477 12.3MP) | 22-pin to 15-pin FFC to Pi 5 CAM0/CAM1 |
| **Lens** | M12 4mm Wide-Angle Lens + C/CS-to-M12 Adapter | Optical Mount (76.3° Horizontal FOV) |
| **GPS** | u-blox NEO-M8N GPS Module (Concurrent GNSS) | Hardware UART (`/dev/ttyAMA0`, 9600 baud) |
| **IMU** | InvenSense MPU6050 (3-Axis Accel + 3-Axis Gyro) | Hardware I2C1 (`0x68`, `/dev/i2c-1`) |
| **Push Button** | Momentary Tactile Push Button | GPIO 17 (Internal Pull-Up) to GND |
| **Status LED** | 5mm High-Intensity Red/Green LED | GPIO 22 via 330Ω Current Limiting Resistor to GND |
| **Storage** | MicroSD / NVMe SSD | `/recordings` (Loop segment buffer) |

---

## 2. Hardware Wiring Diagram

```
Raspberry Pi 5 40-Pin GPIO Header:
=========================================================
Pin 01: 3.3V Power  -------> MPU6050 VCC
Pin 02: 5.0V Power  -------> NEO-M8N GPS VCC
Pin 03: GPIO 02 (SDA) -----> MPU6050 SDA
Pin 05: GPIO 03 (SCL) -----> MPU6050 SCL
Pin 06: Ground       -------> NEO-M8N GPS GND
Pin 08: GPIO 14 (TX) -------> NEO-M8N GPS RXD
Pin 09: Ground       -------> MPU6050 GND & AD0 (Sets I2C address to 0x68)
Pin 10: GPIO 15 (RX) <------- NEO-M8N GPS TXD
Pin 11: GPIO 17 (BTN) ------> Tactile Button Terminal A
Pin 14: Ground       -------> Tactile Button Terminal B
Pin 15: GPIO 22 (LED) ------> 330Ω Resistor -> LED Anode (+)
Pin 20: Ground       -------> LED Cathode (-)
=========================================================
```

### Lens FOV & Road Survey Calibration
- **Sensor Dimensions**: Sony IMX477 = 6.287 mm (H) × 4.712 mm (V), 7.857 mm diagonal (1/2.3" optical format).
- **Focal Length**: 4.0 mm.
- **Horizontal Field of View (HFOV)**:
  $$\text{HFOV} = 2 \times \arctan\left(\frac{6.287}{2 \times 4.0}\right) = 2 \times \arctan(0.7858) \approx 76.3^\circ$$
- **Diagonal FOV**: $\approx 88.9^\circ$.
- In the PWA **Camera Alignment Mode**, the horizontal green guideline aligns with the road horizon at 46% vertical height, while the live IMU roll & pitch bubble level provides instant plumb verification to ensure the camera is mounted level to the highway.

---

## 3. Physical Controls & Autonomous Operation

The physical controls operate autonomously via a background daemon. **The recording push button and status LED function 100% reliably even when the mobile phone is disconnected or turned off.**

### Push Button Gestures:
- **Single Short Click (< 1.5s)**: Starts recording if idle; stops recording if active.
- **Long Press (> 2.5s)**: Locks current recording segment (marks protected from auto-deletion).
- **Double Click (< 400ms)**: Captures instant high-resolution snapshot still.

### Status LED Patterns:
- **Solid ON**: System Ready / Standby.
- **1 Hz Blink (500ms ON / 500ms OFF)**: Recording actively in progress.
- **4 Hz Rapid Blink (125ms ON / 125ms OFF)**: Lock event acknowledged or storage full alert.
- **Slow Breathing (2s period)**: System booting / Wi-Fi discovery beacon.

---

## 4. Offline Connectivity & Direct Wi-Fi Hotspot

The Raspberry Pi 5 runs its own standalone Wi-Fi Access Point using NetworkManager (`nmcli`):
- **Hotspot SSID**: `PiDashcam-01`
- **Dashcam IP**: `192.168.4.1`
- **Application Address**: `http://192.168.4.1:8000`
- **Local Hostname**: `http://dashcam.local:8000`

### Zero Cloud & Offline Guarantee:
- No internet connection required.
- No cloud account or external registration.
- No App Store installation required.
- The Progressive Web App (PWA) is served directly from the Pi's internal storage and caches 100% of its application shell via its Service Worker (`sw.js`).

### Installing PWA to Smartphone Home Screen:
1. Connect mobile phone Wi-Fi to **`PiDashcam-01`**.
2. Open mobile browser (Chrome on Android, Safari on iOS) and navigate to **`http://192.168.4.1:8000`**.
3. **On Android (Chrome)**: Tap the 3-dot menu $\rightarrow$ tap **"Install app"** or **"Add to Home screen"**.
4. **On iOS (Safari)**: Tap the Share button $\rightarrow$ tap **"Add to Home Screen"**.

---

## 5. Synchronized Telemetry Data Formats

For every survey recording segment (e.g. 3-minute loop), four synchronized files are created:

### A. Video Recording
- **File**: `NHAI_SURVEY_YYYYMMDD_HHMMSS_SEC001.mp4`
- 1080p / 1440p / 4K H.264 video at 30/60 fps with telemetry watermark.

### B. GPS Telemetry CSV
- **File**: `NHAI_SURVEY_YYYYMMDD_HHMMSS_SEC001_gps.csv`
- **Columns**:
  ```csv
  timestamp_iso,epoch_ms,video_frame_approx,latitude,longitude,altitude_m,speed_kmh,heading_deg,satellites,fix_type,hdop,chainage_km
  2026-11-20T11:20:01.120Z,1795155601120,33,27.176722,78.008145,169.2,68.4,175.2,14,3D Fix,0.85,120.065
  ```

### C. IMU Telemetry CSV
- **File**: `NHAI_SURVEY_YYYYMMDD_HHMMSS_SEC001_imu.csv`
- **Columns**:
  ```csv
  timestamp_iso,epoch_ms,accel_x_g,accel_y_g,accel_z_g,gyro_x_dps,gyro_y_dps,gyro_z_dps,total_g,pitch_deg,roll_deg,roughness_index
  2026-11-20T11:20:01.120Z,1795155601120,0.021,-0.015,1.024,0.42,-0.18,0.85,1.02,0.8,-0.4,0.14
  ```

### D. Combined Telemetry JSON
- **File**: `NHAI_SURVEY_YYYYMMDD_HHMMSS_SEC001_telemetry.json`
- Contains complete survey session metadata (Project name, highway code, PIU section, vehicle registration, chainage start and direction, peak G-forces, shock events, and unified GPS/IMU sample streams).

---

## 6. Circular Buffer & Protection Guarantee

- The system continuously audits storage space.
- When disk usage exceeds the configured threshold (e.g., 90%), the storage manager automatically purges the oldest **unlocked** recording files.
- **Strict Protection Guarantee**: Recordings marked as **Locked** (either manually via the app, via the physical button long-press, or automatically by the high G-force pothole/collision detector) are **NEVER deleted by the circular buffer**.

---

## 7. Quick Start & Deployment

### On Raspberry Pi 5 (One-Command Deployment):
```bash
git clone https://github.com/nhai/nhai-dashcam.git /home/pi/nhai-dashcam
cd /home/pi/nhai-dashcam
sudo bash scripts/install.sh
```

### On Development PC (Simulation Mode):
The system includes automatic hardware detection and high-fidelity road survey simulation. Run:
```bash
pip install -r requirements.txt
python run_server.py --port 8000
```
Open **`http://localhost:8000`** in your browser.
