"""
Verification script for NHAI AI Road Survey Dashcam API.
"""

import sys
import io
import time
import urllib.request
import json

# Ensure utf-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_URL = "http://localhost:8088"

def req(path, method="GET", body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode("utf-8"))

print("=== VERIFYING NHAI DASHCAM SYSTEM ===")

# 1. System Status
status = req("/api/status")
print(f"1. Status Check: Device={status['device']['name']}, Temp={status['device']['temperature_c']}°C")
print(f"   GPS: Lat={status['gps']['latitude']}, Lon={status['gps']['longitude']}, Speed={status['gps']['speed_kmh']} km/h, Fix={status['gps']['fix_type']}")
print(f"   IMU: TotalG={status['imu']['total_g']}g, Pitch={status['imu']['pitch_deg']}°, Roll={status['imu']['roll_deg']}°")

# 2. Check Recorder Status
rec_status = req("/api/recorder/status")
print(f"2. Recorder Status: IsRec={rec_status['is_recording']}, Text='{rec_status['status_text']}', Duration={rec_status['duration_seconds']}s")

if not rec_status["is_recording"]:
    print("3. Starting Recording...")
    start_res = req("/api/recorder/start", method="POST", body={})
    print(f"   Start Result: {start_res['message']}")
    time.sleep(2.0)
    rec_status = req("/api/recorder/status")
    print(f"   Now Recording: {rec_status['status_text']}")

# 4. Lock Active Recording
print("4. Locking Active Recording Segment...")
lock_res = req("/api/recorder/lock", method="POST", body={})
print(f"   Lock Result: {lock_res['message']}")

# 5. Snapshot Still
print("5. Capturing Snapshot...")
snap_res = req("/api/recorder/snapshot", method="POST", body={})
print(f"   Snapshot Filename: {snap_res['filename']}")

time.sleep(1.0)

# 6. Stop Recording
print("6. Stopping Recording...")
stop_res = req("/api/recorder/stop", method="POST", body={})
print(f"   Stop Result: {stop_res['message']}")

# 7. Check Gallery
print("7. Inspecting Gallery Index...")
gallery = req("/api/gallery")
print(f"   Total Recordings: {gallery['count']}")
for item in gallery["recordings"][:3]:
    print(f"   - {item['filename_video']} | Dur: {item['duration_formatted']} | Locked: {item['locked']} | GPS: {item['has_gps']} | IMU: {item['has_imu']}")

print("=== ALL SYSTEM API VERIFICATIONS SUCCESSFUL! ===")
