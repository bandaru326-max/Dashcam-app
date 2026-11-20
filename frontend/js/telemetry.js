/**
 * NHAI AI Road Survey Dashcam - Telemetry Dashboard Controller
 * Real-time GPS & IMU instrument readouts and ultra-lightweight Canvas waveform charts.
 */

// Ring buffers for live charts (120 points @ 10Hz = 12 seconds history)
const MAX_CHART_POINTS = 120;
const chartData = {
  accelX: new Array(MAX_CHART_POINTS).fill(0),
  accelY: new Array(MAX_CHART_POINTS).fill(0),
  accelZ: new Array(MAX_CHART_POINTS).fill(1.0),
  gyroX: new Array(MAX_CHART_POINTS).fill(0),
  gyroY: new Array(MAX_CHART_POINTS).fill(0),
  gyroZ: new Array(MAX_CHART_POINTS).fill(0),
};

let accelCanvas, accelCtx;
let gyroCanvas, gyroCtx;

document.addEventListener("DOMContentLoaded", () => {
  accelCanvas = document.getElementById("accelCanvas");
  if (accelCanvas) accelCtx = accelCanvas.getContext("2d");

  gyroCanvas = document.getElementById("gyroCanvas");
  if (gyroCanvas) gyroCtx = gyroCanvas.getContext("2d");

  // Initial draw
  drawWaveform(accelCanvas, accelCtx, [chartData.accelX, chartData.accelY, chartData.accelZ], [-2.5, 2.5], ["#ef4444", "#10b981", "#3b82f6"]);
  drawWaveform(gyroCanvas, gyroCtx, [chartData.gyroX, chartData.gyroY, chartData.gyroZ], [-100, 100], ["#ef4444", "#10b981", "#3b82f6"]);
});

// Update Telemetry Dashboard from 10Hz WebSocket packet
window.updateTelemetryDashboard = function (packet) {
  const { gps, imu } = packet;

  // 1. Update GPS Instruments
  if (gps) {
    const speedNum = document.getElementById("telemSpeedNumber");
    if (speedNum) speedNum.innerText = gps.speed_kmh.toFixed(1);

    const fixBadge = document.getElementById("telemFixBadge");
    if (fixBadge) {
      fixBadge.innerText = gps.fix_type.toUpperCase();
      fixBadge.style.color = gps.fix_type === "3D Fix" ? "#10b981" : gps.fix_type === "2D Fix" ? "#60a5fa" : "#f59e0b";
      fixBadge.style.borderColor = fixBadge.style.color;
    }

    const headingEl = document.getElementById("telemHeading");
    if (headingEl) headingEl.innerText = `Heading: ${gps.heading_deg.toFixed(1)}° (${getCardinalDirection(gps.heading_deg)})`;

    const latEl = document.getElementById("telemLat");
    const lonEl = document.getElementById("telemLon");
    if (latEl) latEl.innerText = `${Math.abs(gps.latitude).toFixed(6)}° ${gps.latitude >= 0 ? "N" : "S"}`;
    if (lonEl) lonEl.innerText = `${Math.abs(gps.longitude).toFixed(6)}° ${gps.longitude >= 0 ? "E" : "W"}`;

    const satsEl = document.getElementById("telemSats");
    if (satsEl) satsEl.innerText = `${gps.satellites} Satellites`;

    const altEl = document.getElementById("telemAlt");
    if (altEl) altEl.innerText = `${gps.altitude_m.toFixed(1)} m`;

    const hdopEl = document.getElementById("telemHdop");
    if (hdopEl) hdopEl.innerText = `${gps.hdop.toFixed(2)}`;

    const chainageEl = document.getElementById("telemChainage");
    if (chainageEl) chainageEl.innerText = `KM ${gps.chainage_km.toFixed(3)}`;
  }

  // 2. Update IMU Instruments
  if (imu) {
    const totalGEl = document.getElementById("telemTotalG");
    if (totalGEl) {
      totalGEl.innerText = imu.total_g.toFixed(2);
      totalGEl.style.color = imu.shock_detected ? "#ef4444" : "#f8fafc";
    }

    const roughEl = document.getElementById("telemRoughness");
    if (roughEl) {
      const state = imu.roughness_index > 1.2 ? "Rough (Bumpy)" : imu.roughness_index > 0.5 ? "Moderate" : "Smooth";
      roughEl.innerText = `Roughness: ${imu.roughness_index.toFixed(2)} (${state})`;
    }

    const pitchEl = document.getElementById("telemPitch");
    const rollEl = document.getElementById("telemRoll");
    if (pitchEl) pitchEl.innerText = `${imu.pitch_deg.toFixed(1)}°`;
    if (rollEl) rollEl.innerText = `${imu.roll_deg.toFixed(1)}°`;

    const accelEl = document.getElementById("telemAccel");
    if (accelEl) accelEl.innerText = `${imu.accel_x_g.toFixed(2)}, ${imu.accel_y_g.toFixed(2)}, ${imu.accel_z_g.toFixed(2)} g`;

    const gyroEl = document.getElementById("telemGyro");
    if (gyroEl) gyroEl.innerText = `${imu.gyro_x_dps.toFixed(1)}, ${imu.gyro_y_dps.toFixed(1)}, ${imu.gyro_z_dps.toFixed(1)} °/s`;

    const calibBadge = document.getElementById("telemImuCalibBadge");
    if (calibBadge) {
      calibBadge.innerText = imu.calibrated ? "CALIBRATED" : "UNCALIBRATED";
      calibBadge.style.color = imu.calibrated ? "#10b981" : "#f59e0b";
    }

    // 3. Push to waveform buffers
    chartData.accelX.shift();
    chartData.accelX.push(imu.accel_x_g);
    chartData.accelY.shift();
    chartData.accelY.push(imu.accel_y_g);
    chartData.accelZ.shift();
    chartData.accelZ.push(imu.accel_z_g);

    chartData.gyroX.shift();
    chartData.gyroX.push(imu.gyro_x_dps);
    chartData.gyroY.shift();
    chartData.gyroY.push(imu.gyro_y_dps);
    chartData.gyroZ.shift();
    chartData.gyroZ.push(imu.gyro_z_dps);

    // Redraw charts
    drawWaveform(accelCanvas, accelCtx, [chartData.accelX, chartData.accelY, chartData.accelZ], [-2.5, 2.5], ["#ef4444", "#10b981", "#3b82f6"]);
    drawWaveform(gyroCanvas, gyroCtx, [chartData.gyroX, chartData.gyroY, chartData.gyroZ], [-100, 100], ["#ef4444", "#10b981", "#3b82f6"]);
  }
};

// Ultra-fast HTML5 Canvas Oscilloscope Waveform Renderer
function drawWaveform(canvas, ctx, seriesList, yRange, colors) {
  if (!canvas || !ctx) return;

  const w = canvas.width;
  const h = canvas.height;
  const [minY, maxY] = yRange;

  ctx.clearRect(0, 0, w, h);

  // Background Grid Lines
  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.lineWidth = 1;

  // Horizontal Center line (Zero Level)
  const zeroY = h - ((0 - minY) / (maxY - minY)) * h;
  ctx.beginPath();
  ctx.moveTo(0, zeroY);
  ctx.lineTo(w, zeroY);
  ctx.stroke();

  // Grid subdivisions
  for (let i = 1; i < 4; i++) {
    const gy = (h / 4) * i;
    ctx.beginPath();
    ctx.moveTo(0, gy);
    ctx.lineTo(w, gy);
    ctx.stroke();
  }

  // Draw each series line
  seriesList.forEach((series, sIndex) => {
    ctx.strokeStyle = colors[sIndex];
    ctx.lineWidth = 1.5;
    ctx.beginPath();

    const stepX = w / (MAX_CHART_POINTS - 1);
    for (let i = 0; i < series.length; i++) {
      const val = Math.max(minY, Math.min(maxY, series[i]));
      const x = i * stepX;
      const y = h - ((val - minY) / (maxY - minY)) * h;

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  });
}

// IMU Zero-Point Calibration Action
async function calibrateIMU() {
  showToast("Calibrating IMU... Keep vehicle stationary.");
  try {
    const res = await fetch("/api/telemetry/calibrate", { method: "POST" });
    const data = await res.json();
    if (res.ok) {
      showToast("IMU calibrated successfully! Offsets saved.");
    } else {
      showToast("Calibration failed.");
    }
  } catch (e) {
    showToast("Error during calibration.");
  }
}

// Road Pothole / Shock Simulator
async function triggerTestShock() {
  try {
    const res = await fetch("/api/telemetry/test-shock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ magnitude_g: 3.2 }),
    });
    if (res.ok) {
      showToast("💥 3.2g Pothole Shock Triggered! Auto-lock checked.");
    }
  } catch (e) {
    showToast("Error triggering shock test.");
  }
}

function getCardinalDirection(deg) {
  const directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  const index = Math.round(((deg %= 360) < 0 ? deg + 360 : deg) / 45) % 8;
  return directions[index];
}
