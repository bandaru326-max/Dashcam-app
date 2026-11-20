/**
 * NHAI AI Road Survey Dashcam - Gallery Controller
 * Manages survey recordings, filter tabs, video playback modal,
 * lock/unlock state, CSV/JSON telemetry downloads, and storage auditing.
 */

let currentFilter = "all";

// Load Recordings List from Backend
async function loadGalleryRecordings() {
  const container = document.getElementById("recordingsList");
  if (!container) return;

  container.innerHTML = `<div class="empty-state">Loading survey recordings...</div>`;

  try {
    const res = await fetch(`/api/gallery?filter=${currentFilter}`);
    if (!res.ok) throw new Error("Failed to load gallery");
    const data = await res.json();

    // 1. Update Storage Summary Bar
    updateStorageSummary(data.storage);

    // 2. Render Recording Cards
    renderRecordings(data.recordings);
  } catch (err) {
    console.error("Gallery load error:", err);
    container.innerHTML = `<div class="empty-state">Failed to load recordings. Check dashcam connection.</div>`;
  }
}

function updateStorageSummary(storage) {
  if (!storage) return;

  const bar = document.getElementById("storageProgressBar");
  const percentText = document.getElementById("storagePercentText");
  const usedText = document.getElementById("storageUsedText");
  const freeText = document.getElementById("storageFreeText");
  const totalText = document.getElementById("storageTotalText");

  if (bar) bar.style.width = `${storage.used_percent}%`;
  if (percentText) percentText.innerText = `${storage.used_percent}% Used`;
  if (usedText) usedText.innerText = `${storage.used_formatted} Used`;
  if (freeText) freeText.innerText = `${storage.free_formatted} Free`;
  if (totalText) totalText.innerText = `Total: ${storage.total_formatted}`;

  if (storage.low_storage_warning && bar) {
    bar.style.background = "#ef4444";
  }
}

function renderRecordings(recordings) {
  const container = document.getElementById("recordingsList");
  if (!container) return;

  if (!recordings || recordings.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom: 8px; color: #64748b;">
          <rect x="2" y="2" width="20" height="20" rx="2" ry="2"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
        <p>No survey recordings found for this filter.</p>
      </div>`;
    return;
  }

  container.innerHTML = recordings
    .map((item) => {
      const lockIcon = item.locked ? "🔒" : "🔓";
      const lockClass = item.locked ? "is-locked" : "";
      const lockActionText = item.locked ? "Unlock" : "Lock";
      const lockActionFn = item.locked ? `unlockRecording('${item.stem}')` : `lockRecording('${item.stem}')`;

      return `
      <div class="recording-card ${lockClass}" id="card-${item.stem}">
        <div class="card-top-row">
          <div class="card-thumb-wrap" onclick="playRecording('${item.stem}')">
            <img class="card-thumb-img" src="/api/gallery/${item.stem}/thumbnail" alt="Thumb" onerror="this.src='data:image/svg+xml;utf8,<svg xmlns=\'http://www.w3.org/2000/svg\' width=\'110\' height=\'62\'><rect width=\'100%\' height=\'100%\' fill=\'%23111827\'/></svg>'">
            <span class="card-thumb-dur">${item.duration_formatted}</span>
          </div>
          <div class="card-meta-wrap">
            <div class="card-file-name" title="${item.filename_video}">${item.filename_video}</div>
            <div class="card-sub-info">${item.date_formatted} • ${item.time_formatted} • ${item.size_formatted}</div>
            <div class="card-pill-row">
              <span class="badge-tag ${item.locked ? 'tag-locked' : ''}">${lockIcon} ${item.locked ? 'LOCKED' : 'UNLOCKED'}</span>
              ${item.has_gps ? '<span class="badge-tag tag-active">GPS CSV</span>' : ''}
              ${item.has_imu ? '<span class="badge-tag tag-active">IMU CSV</span>' : ''}
              <span class="badge-tag">${item.highway_code || 'NH-44'}</span>
            </div>
          </div>
        </div>

        <div class="card-action-bar">
          <button class="card-action-btn btn-play" onclick="playRecording('${item.stem}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
            Play
          </button>
          
          <button class="card-action-btn" onclick="${lockActionFn}">
            ${item.locked ? '🔓 Unlock' : '🔒 Lock'}
          </button>

          <button class="card-action-btn" onclick="openDownloadMenu('${item.stem}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download
          </button>

          <button class="card-action-btn btn-delete" onclick="promptDeleteRecording('${item.stem}', ${item.locked})">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            Delete
          </button>
        </div>
      </div>
    `;
    })
    .join("");
}

// Filter Tab Selector
function setGalleryFilter(filterMode) {
  currentFilter = filterMode;
  document.querySelectorAll(".filter-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.getAttribute("data-filter") === filterMode);
  });
  loadGalleryRecordings();
}

// Lock / Unlock Actions
async function lockRecording(stem) {
  try {
    const res = await fetch(`/api/gallery/${stem}/lock`, { method: "POST" });
    if (res.ok) {
      showToast(`🔒 Recording ${stem} locked and protected.`);
      loadGalleryRecordings();
    } else {
      showToast("Failed to lock recording");
    }
  } catch (e) {
    showToast("Error locking recording");
  }
}

async function unlockRecording(stem) {
  try {
    const res = await fetch(`/api/gallery/${stem}/unlock`, { method: "POST" });
    if (res.ok) {
      showToast(`🔓 Recording ${stem} unlocked.`);
      loadGalleryRecordings();
    } else {
      showToast("Failed to unlock recording");
    }
  } catch (e) {
    showToast("Error unlocking recording");
  }
}

// Delete Recording with Confirmation & Lock Guard
function promptDeleteRecording(stem, isLocked) {
  if (isLocked) {
    showToast("⚠️ Cannot delete locked recording. Unlock it first.");
    return;
  }

  showConfirmModal(
    "Delete Recording?",
    `Are you sure you want to delete '${stem}.mp4' and its synchronized GPS & IMU telemetry files? This cannot be undone.`,
    async () => {
      try {
        const res = await fetch(`/api/gallery/${stem}`, { method: "DELETE" });
        const data = await res.json();
        if (res.ok) {
          showToast("Recording deleted successfully.");
          loadGalleryRecordings();
        } else {
          showToast(`Delete failed: ${data.detail}`);
        }
      } catch (e) {
        showToast("Error deleting recording");
      }
    }
  );
}

// Play Recording in Modal Video Player
function playRecording(stem) {
  const modal = document.getElementById("videoModal");
  const title = document.getElementById("modalVideoTitle");
  const video = document.getElementById("playbackVideoPlayer");
  const downloadsRow = document.getElementById("modalDownloadLinks");

  if (!modal || !video) return;

  title.innerText = `${stem}.mp4`;
  video.src = `/api/gallery/${stem}/video`;

  // Provide direct asset download buttons
  if (downloadsRow) {
    downloadsRow.innerHTML = `
      <a class="download-asset-link" href="/api/gallery/${stem}/download/mp4" download>📥 MP4 Video</a>
      <a class="download-asset-link" href="/api/gallery/${stem}/download/gps" download>📍 GPS CSV</a>
      <a class="download-asset-link" href="/api/gallery/${stem}/download/imu" download>⚡ IMU CSV</a>
      <a class="download-asset-link" href="/api/gallery/${stem}/download/telemetry" download>📊 Telemetry JSON</a>
    `;
  }

  modal.style.display = "flex";
  video.play().catch(() => {});
}

function closeVideoModal() {
  const modal = document.getElementById("videoModal");
  const video = document.getElementById("playbackVideoPlayer");
  if (video) {
    video.pause();
    video.src = "";
  }
  if (modal) modal.style.display = "none";
}

// Open Download Selection Modal
function openDownloadMenu(stem) {
  playRecording(stem);
}
