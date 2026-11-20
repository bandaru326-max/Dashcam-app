#!/usr/bin/env bash
# ==============================================================================
# NHAI AI Road Survey Dashcam - Raspberry Pi 5 Automated Deployment Script
# Installs drivers, enables hardware interfaces, and configures systemd daemon
# ==============================================================================

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="nhai-dashcam"

echo "=========================================================="
echo "  Deploying NHAI AI Road Survey Dashcam on Raspberry Pi 5"
echo "  Install Directory: $INSTALL_DIR"
echo "=========================================================="

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root: sudo bash scripts/install.sh"
  exit 1
fi

# 1. Update APT and install system dependencies
echo "[1/5] Installing system packages & camera dependencies..."
apt update
apt install -y \
  python3-pip \
  python3-venv \
  python3-picamera2 \
  libcamera-apps \
  i2c-tools \
  gpsd \
  gpsd-clients \
  ffmpeg \
  avahi-daemon \
  network-manager

# 2. Enable Hardware Interfaces in /boot/firmware/config.txt (Bookworm)
echo "[2/5] Enabling I2C and UART hardware interfaces..."
CONFIG_TXT="/boot/firmware/config.txt"
if [ ! -f "$CONFIG_TXT" ]; then
  CONFIG_TXT="/boot/config.txt"
fi

if grep -q "^dtparam=i2c_arm=on" "$CONFIG_TXT"; then
  echo "  I2C already enabled in $CONFIG_TXT"
else
  echo "dtparam=i2c_arm=on" >> "$CONFIG_TXT"
fi

if grep -q "^enable_uart=1" "$CONFIG_TXT"; then
  echo "  UART already enabled in $CONFIG_TXT"
else
  echo "enable_uart=1" >> "$CONFIG_TXT"
fi

# Sony IMX477 camera overlay
if ! grep -q "^dtoverlay=imx477" "$CONFIG_TXT"; then
  echo "dtoverlay=imx477" >> "$CONFIG_TXT"
  echo "  Added Sony IMX477 camera overlay to $CONFIG_TXT"
fi

# 3. Create Python Virtual Environment & Install Requirements
echo "[3/5] Setting up Python virtual environment..."
VENV_DIR="$INSTALL_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv --system-site-packages "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 4. Setup Wi-Fi Hotspot
echo "[4/5] Configuring Wi-Fi Access Point..."
bash "$INSTALL_DIR/scripts/setup_hotspot.sh"

# 5. Install Systemd Service
echo "[5/5] Installing systemd background service..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=NHAI AI Road Survey Dashcam Backend Service
After=network.target network-online.target
Wants=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=$INSTALL_DIR
ExecStart=$VENV_DIR/bin/python run_server.py --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Adjust user if pi does not exist
if ! id "pi" &>/dev/null; then
  CURRENT_USER=$(logname || echo "root")
  sed -i "s/User=pi/User=$CURRENT_USER/" "$SERVICE_FILE"
fi

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "=========================================================="
echo "  [SUCCESS] NHAI AI Road Survey Dashcam Installed & Running!"
echo "  Check service status: sudo systemctl status $SERVICE_NAME"
echo "  Mobile Hotspot: PiDashcam-01"
echo "  Application URL: http://192.168.4.1:8000"
echo "=========================================================="
