"""
Unit tests for Storage Manager & Circular Buffer Auto-Pruning.
Verifies locked recording protection guarantees.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from backend.core.storage_manager import StorageManager


class TestStorageManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.storage = StorageManager(recordings_dir=self.test_dir, max_usage_percent=90)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_locked_recording_protection(self):
        # Create a sample recording file set
        stem = "NHAI_SURVEY_20261120_110000_SEC001"
        vid_file = Path(self.test_dir) / f"{stem}.mp4"
        with open(vid_file, "wb") as f:
            f.write(b"SAMPLE_VIDEO_DATA")

        # Lock the recording
        self.storage.lock_recording(stem)

        # Attempt to delete while locked -> MUST FAIL
        success, msg = self.storage.delete_recording(stem)
        self.assertFalse(success)
        self.assertIn("protected/locked", msg)
        self.assertTrue(vid_file.exists())

        # Unlock the recording
        self.storage.unlock_recording(stem)

        # Now delete should succeed
        success_del, _ = self.storage.delete_recording(stem)
        self.assertTrue(success_del)
        self.assertFalse(vid_file.exists())


if __name__ == "__main__":
    unittest.main()
