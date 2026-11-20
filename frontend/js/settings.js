/**
 * NHAI AI Road Survey Dashcam - Settings Controller
 * Handles configuration reading, form updating, persistence,
 * and Raspberry Pi power management (reboot/shutdown).
 */

let cachedSettings = null;

// Load Configuration from Backend
async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) throw new Error("Failed to load settings");
    const config = await res.json();
    cachedSettings = config;

    // A. Camera
    if (config.camera) {
      setVal("setResolution", config.camera.resolution);
      setVal("setFramerate", String(config.camera.framerate));
      setVal("setBitrate", String(config.camera.bitrate_mbps));
      setVal("setExposure", config.camera.exposure_mode);
    }

    // B. NHAI Survey
    if (config.survey) {
      setVal("setProjectName", config.survey.project_name);
      setVal("setHighwayCode", config.survey.highway_code);
      setVal("setSectionPiu", config.survey.section_piu);
      setVal("setOperatorName", config.survey.operator_name);
      setVal("setVehicleReg", config.survey.vehicle_registration);
      setVal("setStartChainage", String(config.survey.chainage_km_start));
      setVal("setChainageDir", config.survey.chainage_direction);
    }

    // C. Storage & Recording
    if (config.storage) {
      setVal("setLoopDuration", String(config.storage.loop_duration_sec));
      setVal("setAutoLockShock", String(config.storage.auto_lock_shock_g));
      setCheck("setAutoStartBoot", config.storage.auto_start_on_boot);
      setCheck("setAutoDeleteUnlocked", config.storage.auto_delete_old_unlocked);
    }
  } catch (err) {
    console.error("Settings load error:", err);
    showToast("Error loading dashcam configuration");
  }
}

// Save Configuration to Backend
async function saveAllSettings() {
  if (!cachedSettings) cachedSettings = {};

  const payload = {
    camera: {
      resolution: getVal("setResolution"),
      framerate: parseInt(getVal("setFramerate")),
      bitrate_mbps: parseInt(getVal("setBitrate")),
      exposure_mode: getVal("setExposure"),
      white_balance: "auto",
      lens_focal_length_mm: 4.0,
      lens_hfov_deg: 76.3,
      preview_resolution: "640x360",
      preview_framerate: 15,
      digital_zoom: 1.0,
    },
    survey: {
      project_name: getVal("setProjectName"),
      highway_code: getVal("setHighwayCode"),
      section_piu: getVal("setSectionPiu"),
      operator_name: getVal("setOperatorName"),
      vehicle_registration: getVal("setVehicleReg"),
      chainage_km_start: parseFloat(getVal("setStartChainage")),
      chainage_direction: getVal("setChainageDir"),
      overlay_watermark: true,
    },
    storage: {
      storage_path: "./recordings",
      loop_duration_sec: parseInt(getVal("setLoopDuration")),
      auto_start_on_boot: getCheck("setAutoStartBoot"),
      auto_lock_shock_g: parseFloat(getVal("setAutoLockShock")),
      low_storage_warning_percent: 15,
      auto_delete_old_unlocked: getCheck("setAutoDeleteUnlocked"),
      max_storage_usage_percent: 90,
    },
    hardware: cachedSettings.hardware || {
      device_name: "NHAI-SurveyCam-01",
      firmware_version: "2.4.0-nhai",
      hardware_model: "Raspberry Pi 5 (4GB) + Sony IMX477 HQ",
      gpio_button_pin: 17,
      gpio_led_pin: 22,
      gps_port: "/dev/ttyAMA0",
      gps_baudrate: 9600,
      imu_i2c_bus: 1,
      imu_i2c_address: 104,
      hotspot_ssid: "PiDashcam-01",
      hotspot_ip: "192.168.4.1",
      simulated_mode: false,
    },
  };

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      showToast("Configuration saved successfully!");
      cachedSettings = payload;
    } else {
      const err = await res.json();
      showToast(`Save failed: ${err.detail || "Validation error"}`);
    }
  } catch (e) {
    showToast("Network error saving configuration");
  }
}

// System Power Actions
function confirmSystemAction(actionType) {
  const isReboot = actionType === "reboot";
  const title = isReboot ? "Reboot Raspberry Pi?" : "Safe Power Off?";
  const msg = isReboot
    ? "Are you sure you want to reboot the dashcam SBC? Active recordings will be finalized before restart."
    : "Are you sure you want to shut down the dashcam system? The Pi can be safely unplugged once the LED turns off.";

  showConfirmModal(title, msg, async () => {
    try {
      const endpoint = isReboot ? "/api/system/reboot" : "/api/system/shutdown";
      await fetch(endpoint, { method: "POST" });
      showToast(isReboot ? "Rebooting system... Reconnect in 30 seconds." : "System powering down safely.");
    } catch (e) {
      showToast("Error initiating power action.");
    }
  });
}

// Form Helpers
function setVal(id, val) {
  const el = document.getElementById(id);
  if (el && val !== undefined) el.value = val;
}

function getVal(id) {
  const el = document.getElementById(id);
  return el ? el.value : "";
}

function setCheck(id, checked) {
  const el = document.getElementById(id);
  if (el) el.checked = Boolean(checked);
}

function getCheck(id) {
  const el = document.getElementById(id);
  return el ? el.checked : false;
}
