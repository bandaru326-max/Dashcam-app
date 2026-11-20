/**
 * NHAI AI Road Survey Dashcam - Live View Controller
 * Handles 16:9 low-latency preview, alignment guides with dynamic IMU horizon leveling,
 * digital zoom, recording toggles with safety confirmation, and telemetry HUD overlays.
 */

let alignmentModeActive = false;
let currentZoom = 1.0;

// Update Live View from 10Hz Telemetry Stream
window.updateLiveViewTelemetry = function (packet) {
  const { recorder, gps, imu } = packet;

  // 1. Update Video HUD Overlays
  if (gps) {
    const speedEl = document.getElementById("hudSpeedTag");
    if (speedEl) speedEl.innerText = `${gps.speed_kmh.toFixed(1)} KM/H`;

    const quickSpeedEl = document.getElementById("quickSpeedVal");
    if (quickSpeedEl) quickSpeedEl.innerHTML = `${gps.speed_kmh.toFixed(1)} <small>km/h</small>`;

    const chainageEl = document.getElementById("hudChainageTag");
    if (chainageEl) chainageEl.innerText = `KM ${gps.chainage_km.toFixed(3)}`;

    const quickChainageEl = document.getElementById("quickChainageVal");
    if (quickChainageEl) quickChainageEl.innerHTML = `${gps.chainage_km.toFixed(3)} <small>km</small>`;

    const coordsEl = document.getElementById("hudCoordsTag");
    if (coordsEl) {
      coordsEl.innerText = `${Math.abs(gps.latitude).toFixed(4)}° ${gps.latitude >= 0 ? "N" : "S"}, ${Math.abs(gps.longitude).toFixed(4)}° ${gps.longitude >= 0 ? "E" : "W"}`;
    }

    const gpsFixEl = document.getElementById("hudGpsFixTag");
    const quickGpsEl = document.getElementById("quickGpsVal");
    if (gpsFixEl) gpsFixEl.innerText = `${gps.fix_type.toUpperCase()} (${gps.satellites} SATS)`;
    if (quickGpsEl) quickGpsEl.innerText = `${gps.fix_type.toUpperCase()} (${gps.satellites})`;
  }

  // 2. Update IMU Quick Telemetry
  if (imu) {
    const quickGEl = document.getElementById("quickGVal");
    if (quickGEl) quickGEl.innerHTML = `${imu.total_g.toFixed(2)} <small>g</small>`;

    // Update Bubble Level in Alignment Mode
    if (alignmentModeActive) {
      updateBubbleLevel(imu.roll_deg, imu.pitch_deg);
    }
  }

  // 3. Update Recording State Card & Buttons
  if (recorder) {
    appState.recordingStatus = recorder;
    const isRec = recorder.is_recording;

    const stateCard = document.getElementById("recordingStateCard");
    const statusTitle = document.getElementById("recStatusTitle");
    const timerEl = document.getElementById("recDurationTimer");
    const segmentTag = document.getElementById("recSegmentTag");
    const btnRecord = document.getElementById("btnRecordToggle");
    const btnRecText = document.getElementById("btnRecText");
    const btnLock = document.getElementById("btnLockRecording");

    if (stateCard) stateCard.classList.toggle("is-recording", isRec);
    if (statusTitle) statusTitle.innerText = isRec ? "RECORDING ACTIVE" : "READY TO RECORD";
    if (timerEl) timerEl.innerText = isRec ? recorder.duration_formatted : "00:00:00";

    if (segmentTag) {
      if (isRec && recorder.current_segment_index > 0) {
        segmentTag.style.display = "inline-block";
        segmentTag.innerText = `SEG ${String(recorder.current_segment_index).padStart(2, "0")}`;
      } else {
        segmentTag.style.display = "none";
      }
    }

    if (btnRecord) {
      btnRecord.classList.toggle("is-recording", isRec);
      btnRecText.innerText = isRec ? "STOP RECORDING" : "START RECORDING";
    }

    if (btnLock) {
      btnLock.classList.toggle("is-locked", recorder.is_locked);
      const lockText = document.getElementById("btnLockText");
      if (lockText) {
        lockText.innerText = recorder.is_locked ? "LOCKED (PROTECTED)" : "LOCK SEGMENT";
      }
    }
  }
};

// Alignment Mode Toggle
function toggleAlignmentMode() {
  alignmentModeActive = !alignmentModeActive;
  const overlay = document.getElementById("alignmentOverlay");
  const btn = document.getElementById("toggleAlignmentBtn");

  if (overlay) overlay.style.display = alignmentModeActive ? "block" : "none";
  if (btn) btn.classList.toggle("active", alignmentModeActive);

  if (alignmentModeActive) {
    showToast("Camera Alignment Mode: Align green line to road horizon");
  }
}

// Dynamic Horizon Bubble Level using IMU Roll & Pitch
function updateBubbleLevel(rollDeg, pitchDeg) {
  const bubble = document.getElementById("bubbleIndicator");
  if (!bubble) return;

  // Max pixel offset within 70px ring is +/- 24px
  const maxOffset = 24;
  // Sensitivity: 15 degrees tilt corresponds to full deviation
  const offsetX = Math.max(-maxOffset, Math.min(maxOffset, (rollDeg / 15.0) * maxOffset));
  const offsetY = Math.max(-maxOffset, Math.min(maxOffset, (pitchDeg / 15.0) * maxOffset));

  bubble.style.transform = `translate(${offsetX}px, ${offsetY}px)`;

  // Change color to green if perfectly leveled within +/- 1.5 degrees
  const isLeveled = Math.abs(rollDeg) < 1.5 && Math.abs(pitchDeg) < 1.5;
  bubble.style.backgroundColor = isLeveled ? "#10b981" : "#3b82f6";
  bubble.style.boxShadow = isLeveled ? "0 0 10px #10b981" : "0 0 8px #3b82f6";
}

// Digital Zoom Selector (1x, 2x, 4x)
async function setZoom(zoomFactor) {
  currentZoom = zoomFactor;
  document.querySelectorAll(".zoom-btn").forEach((b) => {
    b.classList.toggle("active", parseFloat(b.getAttribute("data-zoom")) === zoomFactor);
  });

  try {
    const res = await fetch("/api/camera/zoom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ zoom: zoomFactor }),
    });
    if (res.ok) {
      showToast(`Digital Zoom: ${zoomFactor}x`);
    }
  } catch (e) {
    console.error("Zoom set error:", e);
  }
}

// Fullscreen Video Toggle
function toggleFullscreen() {
  const container = document.getElementById("videoContainer");
  if (!document.fullscreenElement) {
    if (container.requestFullscreen) {
      container.requestFullscreen();
    } else if (container.webkitRequestFullscreen) {
      container.webkitRequestFullscreen();
    }
  } else {
    if (document.exitFullscreen) {
      document.exitFullscreen();
    }
  }
}

// Record Toggle Button Handler (with confirmation modal for Stop)
function handleRecordToggle() {
  if (appState.recordingStatus.is_recording) {
    // Show safety confirmation dialog
    showConfirmModal(
      "Stop Recording?",
      "Are you sure you want to stop the active road survey recording segment? All telemetry will be finalized.",
      async () => {
        try {
          const res = await fetch("/api/recorder/stop", { method: "POST" });
          const data = await res.json();
          if (res.ok) {
            showToast("Recording stopped and saved.");
          } else {
            showToast(`Error: ${data.detail || "Failed to stop recording"}`);
          }
        } catch (e) {
          showToast("Network error stopping recording");
        }
      }
    );
  } else {
    // Start Recording immediately
    startRecordingAction();
  }
}

async function startRecordingAction() {
  try {
    const res = await fetch("/api/recorder/start", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("Recording started! Synchronizing telemetry.");
    } else {
      showToast(`Error: ${data.detail || "Failed to start recording"}`);
    }
  } catch (e) {
    showToast("Network error starting recording");
  }
}

// Capture Snapshot Action
async function captureSnapshot() {
  try {
    const res = await fetch("/api/recorder/snapshot", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast(`Snapshot captured: ${data.filename}`);
    } else {
      showToast(`Snapshot failed: ${data.detail}`);
    }
  } catch (e) {
    showToast("Error capturing snapshot");
  }
}

// Lock Current Active Segment Action
async function lockActiveRecording() {
  if (!appState.recordingStatus.is_recording) {
    showToast("No active recording to lock. Start recording first.");
    return;
  }

  try {
    const res = await fetch("/api/recorder/lock", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("🔒 Segment LOCKED! Protected from auto-deletion.");
    } else {
      showToast(`Lock failed: ${data.detail}`);
    }
  } catch (e) {
    showToast("Error locking segment");
  }
}

// Stream Image Error / Reconnect Handler
function handleStreamError(img) {
  setTimeout(() => {
    img.src = `/api/camera/stream?t=${Date.now()}`;
  }, 1500);
}

function handleStreamLoaded(img) {
  // Preview stream running cleanly
}

// Physical Button Simulator (for development & QA)
async function testHardwareButton(action) {
  try {
    const res = await fetch("/api/recorder/test-button", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (res.ok) {
      showToast(`Physical Button: ${action.replace("_", " ").toUpperCase()}`);
    }
  } catch (e) {
    showToast("Error simulating hardware button");
  }
}

// Generic Modal Confirmation
let confirmCallback = null;

function showConfirmModal(title, message, onConfirm) {
  document.getElementById("confirmModalTitle").innerText = title;
  document.getElementById("confirmModalMessage").innerText = message;
  confirmCallback = onConfirm;

  const actionBtn = document.getElementById("confirmModalActionBtn");
  actionBtn.onclick = () => {
    if (confirmCallback) confirmCallback();
    closeConfirmModal();
  };

  document.getElementById("confirmModal").style.display = "flex";
}

function closeConfirmModal() {
  document.getElementById("confirmModal").style.display = "none";
  confirmCallback = null;
}
