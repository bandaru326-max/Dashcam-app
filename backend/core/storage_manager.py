"""
Storage Manager & Gallery Indexer for NHAI Dashcam.
Handles circular buffer loop-recording cleanup, disk space auditing,
and metadata indexing with locked file protection.
"""

from __future__ import annotations
import io
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw


@dataclass
class StorageInfo:
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    used_percent: float = 0.0
    total_formatted: str = "0 GB"
    used_formatted: str = "0 GB"
    free_formatted: str = "0 GB"
    low_storage_warning: bool = False


@dataclass
class RecordingItem:
    stem: str
    filename_video: str
    date_formatted: str
    time_formatted: str
    duration_sec: float
    duration_formatted: str
    size_bytes: int
    size_formatted: str
    has_gps: bool
    has_imu: bool
    locked: bool
    highway_code: str
    chainage_km: float
    timestamp_epoch: float


class StorageManager:
    """Manages recording directory, circular buffer auto-pruning, and gallery items."""

    def __init__(
        self,
        recordings_dir: str = "./recordings",
        max_usage_percent: int = 90,
        low_warning_percent: int = 15,
    ):
        self.recordings_path = Path(recordings_dir).resolve()
        self.recordings_path.mkdir(parents=True, exist_ok=True)
        self.thumbs_path = self.recordings_path / ".thumbnails"
        self.thumbs_path.mkdir(parents=True, exist_ok=True)

        self.max_usage_percent = max_usage_percent
        self.low_warning_percent = low_warning_percent

    def get_storage_info(self) -> StorageInfo:
        """Query host disk filesystem usage."""
        try:
            total, used, free = shutil.disk_usage(self.recordings_path)
            used_percent = (used / total) * 100.0 if total > 0 else 0.0
            free_percent = (free / total) * 100.0 if total > 0 else 0.0
            low_warning = free_percent <= self.low_warning_percent

            return StorageInfo(
                total_bytes=total,
                used_bytes=used,
                free_bytes=free,
                used_percent=round(used_percent, 1),
                total_formatted=self._format_bytes(total),
                used_formatted=self._format_bytes(used),
                free_formatted=self._format_bytes(free),
                low_storage_warning=low_warning,
            )
        except Exception as e:
            print(f"[Storage] Disk usage query error: {e}")
            return StorageInfo()

    def list_recordings(
        self,
        filter_mode: str = "all",  # "all", "locked", "today"
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[dict]:
        """Enumerate and sort all recordings in reverse chronological order."""
        items: list[RecordingItem] = []

        # Find all .mp4 files or metadata files
        video_files = list(self.recordings_path.glob("*.mp4"))

        for vid in video_files:
            stem = vid.stem
            meta_path = self.recordings_path / f"{stem}_meta.json"
            gps_path = self.recordings_path / f"{stem}_gps.csv"
            imu_path = self.recordings_path / f"{stem}_imu.csv"

            meta = {}
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    pass

            locked = meta.get("locked", False)
            duration_sec = meta.get("duration_sec", 0.0)
            highway_code = meta.get("highway_code", "NH-44")
            chainage_km = meta.get("chainage_start_km", 0.0)

            # File stat
            stat = vid.stat()
            size_bytes = stat.st_size
            mtime = stat.st_mtime
            dt = datetime.fromtimestamp(mtime)

            date_str = dt.strftime("%d %b %Y")
            time_str = dt.strftime("%H:%M:%S")

            # Duration formatting
            dur_m = int(duration_sec // 60)
            dur_s = int(duration_sec % 60)
            dur_formatted = f"{dur_m:02d}:{dur_s:02d}"

            item = RecordingItem(
                stem=stem,
                filename_video=vid.name,
                date_formatted=date_str,
                time_formatted=time_str,
                duration_sec=duration_sec,
                duration_formatted=dur_formatted,
                size_bytes=size_bytes,
                size_formatted=self._format_bytes(size_bytes),
                has_gps=gps_path.exists(),
                has_imu=imu_path.exists(),
                locked=locked,
                highway_code=highway_code,
                chainage_km=chainage_km,
                timestamp_epoch=mtime,
            )

            # Apply filters
            if filter_mode == "locked" and not locked:
                continue
            if filter_mode == "today":
                today_str = datetime.now().strftime("%d %b %Y")
                if date_str != today_str:
                    continue

            items.append(item)

        # Sort reverse chronologically (newest first)
        items.sort(key=lambda x: x.timestamp_epoch, reverse=True)
        return [item.__dict__ for item in items]

    def lock_recording(self, stem: str) -> bool:
        """Protect a recording from circular buffer auto-deletion."""
        meta_path = self.recordings_path / f"{stem}_meta.json"
        data = {}
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["locked"] = True
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[Storage] Segment '{stem}' successfully LOCKED.")
            return True
        except Exception as e:
            print(f"[Storage] Error locking segment: {e}")
            return False

    def unlock_recording(self, stem: str) -> bool:
        """Remove protection lock from a recording."""
        meta_path = self.recordings_path / f"{stem}_meta.json"
        data = {}
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        data["locked"] = False
        try:
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"[Storage] Segment '{stem}' UNLOCKED.")
            return True
        except Exception as e:
            print(f"[Storage] Error unlocking segment: {e}")
            return False

    def delete_recording(self, stem: str) -> tuple[bool, str]:
        """Delete all files belonging to stem. Fails if recording is locked."""
        meta_path = self.recordings_path / f"{stem}_meta.json"
        if meta_path.exists():
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                if meta.get("locked", False):
                    return False, "Cannot delete protected/locked recording. Unlock it first."
            except Exception:
                pass

        deleted_count = 0
        for pattern in (f"{stem}.mp4", f"{stem}_*.csv", f"{stem}_*.json"):
            for fpath in self.recordings_path.glob(pattern):
                try:
                    fpath.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"[Storage] Error deleting {fpath}: {e}")

        # Remove thumbnail if present
        thumb_file = self.thumbs_path / f"{stem}.jpg"
        if thumb_file.exists():
            try:
                thumb_file.unlink()
            except Exception:
                pass

        if deleted_count > 0:
            print(f"[Storage] Deleted {deleted_count} files for segment '{stem}'.")
            return True, f"Recording {stem} deleted successfully."
        return False, "Recording files not found."

    def prune_circular_buffer(self) -> int:
        """
        Check disk usage; if usage exceeds threshold, delete oldest unlocked files.
        Never deletes locked files!
        Returns number of pruned segments.
        """
        info = self.get_storage_info()
        if info.used_percent < self.max_usage_percent:
            return 0

        print(f"[Storage] Disk usage at {info.used_percent}% >= threshold {self.max_usage_percent}%. Starting auto-prune.")
        all_items = self.list_recordings()
        # Filter for unlocked items, sorted oldest first
        unlocked_items = [i for i in all_items if not i["locked"]]
        unlocked_items.sort(key=lambda x: x["timestamp_epoch"])  # Oldest first

        pruned_count = 0
        for item in unlocked_items:
            success, _ = self.delete_recording(item["stem"])
            if success:
                pruned_count += 1
                new_info = self.get_storage_info()
                if new_info.used_percent < (self.max_usage_percent - 5):
                    break  # Freed sufficient space

        print(f"[Storage] Circular buffer auto-prune completed. Removed {pruned_count} old unlocked segments.")
        return pruned_count

    def get_or_generate_thumbnail(self, stem: str) -> Optional[bytes]:
        """Get cached thumbnail or generate a clean placeholder thumbnail."""
        thumb_file = self.thumbs_path / f"{stem}.jpg"
        if thumb_file.exists():
            try:
                with open(thumb_file, "rb") as f:
                    return f.read()
            except Exception:
                pass

        # Generate a styled thumbnail
        img = Image.new("RGB", (320, 180), color=(18, 27, 42))
        draw = ImageDraw.Draw(img)

        # Draw road perspective vignette
        draw.polygon([(40, 180), (140, 70), (180, 70), (280, 180)], fill=(35, 42, 54))
        draw.line([(160, 70), (160, 180)], fill=(200, 200, 200), width=2)

        # Draw title watermark
        draw.rectangle([(8, 8), (180, 32)], fill=(10, 15, 24, 200))
        draw.text((14, 12), "NHAI SURVEY CAM", fill=(16, 185, 129))
        draw.text((14, 150), stem[:25], fill=(226, 232, 240))

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        thumb_bytes = buf.getvalue()

        try:
            with open(thumb_file, "wb") as f:
                f.write(thumb_bytes)
        except Exception:
            pass

        return thumb_bytes

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if abs(num_bytes) < 1024.0:
                return f"{num_bytes:.1f} {unit}"
            num_bytes /= 1024.0
        return f"{num_bytes:.1f} PB"
