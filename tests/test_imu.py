"""
Unit tests for MPU6050 IMU driver, calculations, and shock detection.
"""

import unittest
from backend.core.hal.imu import IMUDriver


class TestIMUDriver(unittest.TestCase):
    def setUp(self):
        self.shock_called = False
        self.shock_val = 0.0

        def on_shock(val):
            self.shock_called = True
            self.shock_val = val

        self.driver = IMUDriver(simulated=True, shock_threshold_g=2.5, on_shock_callback=on_shock)

    def test_g_force_and_angle_calculations(self):
        # 1g static vertical: ax=0, ay=0, az=1.0 -> total_g=1.0, pitch=0, roll=0
        self.driver._process_reading(0.0, 0.0, 1.0, 0.0, 0.0, 0.0)
        reading = self.driver.get_latest()
        self.assertAlmostEqual(reading.total_g, 1.0, places=2)
        self.assertAlmostEqual(reading.pitch_deg, 0.0, places=1)
        self.assertAlmostEqual(reading.roll_deg, 0.0, places=1)
        self.assertFalse(reading.shock_detected)

    def test_shock_detection_trigger(self):
        # 3.0g shock bump on Z axis
        self.driver._process_reading(0.0, 0.0, 3.0, 10.0, 5.0, 2.0)
        reading = self.driver.get_latest()
        self.assertTrue(reading.shock_detected)
        self.assertTrue(self.shock_called)
        self.assertAlmostEqual(self.shock_val, 3.0, places=1)

    def test_int16_conversion(self):
        # Positive 16-bit
        self.assertEqual(IMUDriver._to_int16(0x00, 0x10), 16)
        # Negative 16-bit (-1)
        self.assertEqual(IMUDriver._to_int16(0xFF, 0xFF), -1)


if __name__ == "__main__":
    unittest.main()
