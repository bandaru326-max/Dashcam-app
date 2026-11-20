/**
 * NHAI AI Road Survey Dashcam - Core App Controller
 * Manages WebSocket connectivity, reactive auto-reconnect,
 * tab navigation, PWA service worker registration, and global state.
 */

// Global State
const appState = {
  currentTab: "live",
  connected: false,
  reconnectAttempts: 0,
  maxReconnectAttempts: 100,
  ws: null,
  wsUrl: `ws://${window.location.host}/ws`,
  latestTelemetry: null,
  recordingStatus: {
    is_recording: false,
    duration_seconds: 0,
    duration_formatted: "00:00:00",
    is_locked: false,
    current_stem: "",
  },
};

// Register PWA Service Worker for offline execution
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("./sw.js")
      .then((reg) => console.log("[PWA] Service Worker registered:", reg.scope))
      .catch((err) => console.warn("[PWA] Service Worker registration failed:", err));
  });
}

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  initWebSocket();
  initGlobalStatusPoller();
  // Set initial tab from hash or default to live
  const hashTab = window.location.hash.replace("#", "");
  if (["live", "gallery", "telemetry", "settings"].includes(hashTab)) {
    switchTab(hashTab);
  }
});

// Tab Navigation
function switchTab(tabName) {
  appState.currentTab = tabName;
  window.location.hash = tabName;

  // Update Bottom Nav UI
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.getAttribute("data-tab") === tabName);
  });

  // Update Views UI
  document.querySelectorAll(".tab-view").forEach((view) => {
    view.classList.toggle("active", view.id === `view-${tabName}`);
  });

  // Tab specific refreshes
  if (tabName === "gallery") {
    loadGalleryRecordings();
  } else if (tabName === "settings") {
    loadSettings();
  }
}

// WebSocket Connection Manager with Resilient Auto-Reconnect
function initWebSocket() {
  if (appState.ws && (appState.ws.readyState === WebSocket.OPEN || appState.ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    appState.ws = new WebSocket(appState.wsUrl);

    appState.ws.onopen = () => {
      console.log("[WebSocket] Connected to Dashcam server.");
      appState.connected = true;
      appState.reconnectAttempts = 0;
      updateConnectionUI(true);
      hideOfflineBanner();
    };

    appState.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === "telemetry") {
          handleIncomingTelemetry(data);
        }
      } catch (e) {
        console.error("[WebSocket] Parse error:", e);
      }
    };

    appState.ws.onclose = () => {
      console.warn("[WebSocket] Connection lost.");
      appState.connected = false;
      updateConnectionUI(false);
      showOfflineBanner();
      scheduleReconnect();
    };

    appState.ws.onerror = (err) => {
      console.error("[WebSocket] Error:", err);
      appState.ws.close();
    };
  } catch (err) {
    console.error("[WebSocket] Init exception:", err);
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  appState.reconnectAttempts++;
  const countEl = document.getElementById("reconnectCount");
  if (countEl) countEl.innerText = appState.reconnectAttempts;

  // Exponential backoff capped at 4 seconds
  const backoffMs = Math.min(1000 * Math.pow(1.3, appState.reconnectAttempts), 4000);
  setTimeout(() => {
    console.log(`[WebSocket] Attempting reconnect #${appState.reconnectAttempts}...`);
    initWebSocket();
  }, backoffMs);
}

function updateConnectionUI(isConnected) {
  const pill = document.getElementById("connectionStatusPill");
  const text = document.getElementById("connectionStatusText");

  if (isConnected) {
    pill.className = "status-pill status-connected";
    text.innerText = "WI-FI DIRECT";
  } else {
    pill.className = "status-pill status-disconnected";
    text.innerText = "RECONNECTING...";
  }
}

function showOfflineBanner() {
  const banner = document.getElementById("offlineBanner");
  if (banner) banner.style.display = "flex";
}

function hideOfflineBanner() {
  const banner = document.getElementById("offlineBanner");
  if (banner) banner.style.display = "none";
}

// High-frequency telemetry dispatcher
function handleIncomingTelemetry(packet) {
  appState.latestTelemetry = packet;

  // 1. Update Header Badges
  if (packet.system) {
    const tempEl = document.getElementById("headerTempText");
    if (tempEl && packet.system.temperature_c !== undefined) {
      tempEl.innerText = `${packet.system.temperature_c.toFixed(1)}°C`;
    }

    const storageEl = document.getElementById("headerStorageText");
    if (storageEl && packet.system.storage) {
      storageEl.innerText = `${packet.system.storage.used_percent}%`;
    }
  }

  // 2. Dispatch to Live View
  if (window.updateLiveViewTelemetry) {
    window.updateLiveViewTelemetry(packet);
  }

  // 3. Dispatch to Telemetry Dashboard
  if (window.updateTelemetryDashboard && appState.currentTab === "telemetry") {
    window.updateTelemetryDashboard(packet);
  }
}

// Background HTTP Poller fallback (runs every 5s to sync system status)
function initGlobalStatusPoller() {
  setInterval(async () => {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        if (!appState.connected) {
          appState.connected = true;
          updateConnectionUI(true);
          hideOfflineBanner();
        }
        if (data.device && data.device.name) {
          const devNameEl = document.getElementById("deviceName");
          if (devNameEl) devNameEl.innerText = data.device.name;
        }
      }
    } catch (e) {
      if (appState.connected) {
        appState.connected = false;
        updateConnectionUI(false);
        showOfflineBanner();
      }
    }
  }, 4000);
}

// Toast notification helper
function showToast(message, durationMs = 2800) {
  const toast = document.getElementById("toastPopup");
  if (!toast) return;
  toast.innerText = message;
  toast.classList.add("show");
  setTimeout(() => {
    toast.classList.remove("show");
  }, durationMs);
}
