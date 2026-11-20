#!/usr/bin/env bash
# ==============================================================================
# NHAI AI Road Survey Dashcam - Wi-Fi Direct Hotspot Setup Script
# Configures Raspberry Pi 5 NetworkManager Access Point (192.168.4.1)
# ==============================================================================

set -euo pipefail

HOTSPOT_SSID="PiDashcam-01"
HOTSPOT_IP="192.168.4.1/24"
CON_NAME="PiDashcamHotspot"

echo "=========================================================="
echo "  Setting up NHAI Dashcam Direct Wi-Fi Hotspot"
echo "  SSID: $HOTSPOT_SSID"
echo "  IP Address: 192.168.4.1"
echo "=========================================================="

if [ "$EUID" -ne 0 ]; then
  echo "[-] Please run as root: sudo bash scripts/setup_hotspot.sh"
  exit 1
fi

# Ensure NetworkManager is installed and running (standard on RPi OS Bookworm)
if ! command -v nmcli &> /dev/null; then
  echo "[+] Installing NetworkManager..."
  apt update && apt install -y network-manager
  systemctl enable --now NetworkManager
fi

# Remove existing hotspot connection if present
if nmcli connection show "$CON_NAME" &> /dev/null; then
  echo "[+] Removing existing $CON_NAME connection..."
  nmcli connection delete "$CON_NAME"
fi

echo "[+] Creating Wi-Fi Access Point connection..."
nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME" autoconnect yes ssid "$HOTSPOT_SSID"
nmcli connection modify "$CON_NAME" 802-11-wireless.mode ap 802-11-wireless.band bg
nmcli connection modify "$CON_NAME" ipv4.method shared ipv4.addresses "$HOTSPOT_IP"
nmcli connection modify "$CON_NAME" wifi-sec.key-mgmt none  # Open hotspot for instant vehicle field connection (or wpa-psk if password desired)

echo "[+] Activating hotspot connection..."
nmcli connection up "$CON_NAME"

# Enable mDNS (avahi) so dashcam.local resolves automatically
echo "[+] Ensuring Avahi mDNS daemon is active for http://dashcam.local..."
apt install -y avahi-daemon
systemctl enable --now avahi-daemon

echo "=========================================================="
echo "  [SUCCESS] Wi-Fi Hotspot Active!"
echo "  SSID: $HOTSPOT_SSID"
echo "  Connect your mobile phone to '$HOTSPOT_SSID'"
echo "  Open browser to: http://192.168.4.1:8000 or http://dashcam.local:8000"
echo "=========================================================="
