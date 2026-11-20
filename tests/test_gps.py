"""
Unit tests for NEO-M8N GPS Driver & NMEA parser.
"""

import unittest
from backend.core.hal.gps import GPSDriver, GPSReading


class TestGPSDriver(unittest.TestCase):
    def setUp(self):
        self.driver = GPSDriver(simulated=True, start_chainage_km=140.0)

    def test_nmea_conversion(self):
        # 2831.2345 N -> 28 + 31.2345/60 = 28.520575
        dec = GPSDriver._nmea_to_decimal("2831.2345", "N")
        self.assertAlmostEqual(dec, 28.520575, places=4)

        # 07712.5432 W -> -(77 + 12.5432/60) = -77.209053
        dec_w = GPSDriver._nmea_to_decimal("07712.5432", "W")
        self.assertAlmostEqual(dec_w, -77.209053, places=4)

    def test_parse_rmc_sentence(self):
        # RMC with status A, 27°10.596' N, 78°00.486' E, 35 knots, 180° heading
        rmc = "$GPRMC,060000.00,A,2710.5960,N,07800.4860,E,35.0,180.0,201126,,,A*7B"
        self.driver._parse_nmea(rmc)
        reading = self.driver.get_latest()

        self.assertGreater(reading.latitude, 27.0)
        self.assertGreater(reading.longitude, 77.0)
        self.assertAlmostEqual(reading.speed_kmh, 35.0 * 1.852, places=1)
        self.assertEqual(reading.heading_deg, 180.0)

    def test_parse_gga_sentence(self):
        # GGA with 12 satellites, 0.9 HDOP, 175.5m altitude, quality 1 (3D Fix)
        gga = "$GPGGA,060000.00,2710.5960,N,07800.4860,E,1,12,0.9,175.5,M,0.0,M,,*4A"
        self.driver._parse_nmea(gga)
        reading = self.driver.get_latest()

        self.assertEqual(reading.satellites, 12)
        self.assertEqual(reading.hdop, 0.9)
        self.assertEqual(reading.altitude_m, 175.5)
        self.assertEqual(reading.fix_type, "3D Fix")

    def test_simulated_update(self):
        self.driver._update_simulated()
        reading = self.driver.get_latest()
        self.assertGreater(reading.latitude, 20.0)
        self.assertGreater(reading.speed_kmh, 30.0)
        self.assertEqual(reading.fix_type, "3D Fix")
        self.assertGreaterEqual(reading.chainage_km, 140.0)


if __name__ == "__main__":
    unittest.main()
