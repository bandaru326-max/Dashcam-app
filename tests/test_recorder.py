"""
Unit tests for DashcamRecorder state machine and lock propagation.
"""

import shutil
import tempfile
import unittest
from backend.config import AppConfig
from backend.core.hal.camera import CameraDriver
from backend.core.hal.gps import GPSDriver
from backend.core.hal.imu import IMUDriver
from backend.core.hal.gpio_controller import GPIOController
from backend.core.storage_manager import StorageManager
from backend.core.recorder import DashcamRecorder


class TestDashcamRecorder(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = AppConfig()
        self.config.storage.storage_path = self.test_dir
        self.config.storage.loop_duration_sec = 60

        self.storage = StorageManager(recordings_dir=self.test_dir)
        self.camera = CameraDriver(simulated=True)
        self.gps = GPSDriver(simulated=True)
        self.imu = IMUDriver(simulated=True)
        self.gpio = GPIOController(simulated=True)

        self.recorder = DashcamRecorder(
            config=self.config,
            camera=self.camera,
            gps=self.gps,
            imu=self.imu,
            gpio=self.gpio,
            storage=self.storage,
        )

    def tearDown(self):
        if self.recorder.is_recording():
            self.recorder.stop_recording()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_start_stop_state_machine(self):
        self.assertFalse(self.recorder.is_recording())
        status_init = self.recorder.get_status()
        self.assertEqual(status_init.status_text, "READY TO RECORD")

        # Start recording
        success, _ = self.recorder.start_recording()
        self.assertTrue(success)
        self.assertTrue(self.recorder.is_recording())

        status_rec = self.recorder.get_status()
        self.assertTrue(status_rec.is_recording)
        self.assertIn("REC ●", status_rec.status_text)
        self.assertTrue(status_rec.current_stem.startswith("NHAI_SURVEY_"))

        # Lock recording
        lock_ok, _ = self.recorder.lock_current_recording()
        self.assertTrue(lock_ok)
        self.assertTrue(self.recorder.get_status().is_locked)

        # Stop recording
        stop_ok, _ = self.recorder.stop_recording()
        self.assertTrue(stop_ok)
        self.assertFalse(self.recorder.is_recording())


if __name__ == "__main__":
    unittest.main()
