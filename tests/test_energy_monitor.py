#!/usr/bin/env python3
"""Tests for BlackRoad Energy Monitor."""

import os
import sys
import json
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import energy_monitor as em


def _make_tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return f.name


class TestEnergyReadingDataclass(unittest.TestCase):
    def test_defaults(self):
        r = em.EnergyReading(device_id="d1", device_name="Fridge", watts=120.0)
        self.assertEqual(r.location, "default")
        self.assertIsNone(r.id)
        self.assertIsNone(r.timestamp)

    def test_device_stats_fields(self):
        ds = em.DeviceStats(
            device_id="d1", device_name="Fridge", location="kitchen",
            avg_watts=100.0, max_watts=150.0, min_watts=80.0,
            daily_kwh=2.4, daily_cost_usd=0.288,
            reading_count=10, last_reading_at="2024-01-01",
        )
        self.assertEqual(ds.daily_kwh, 2.4)


class TestInitDb(unittest.TestCase):
    def test_all_tables_created(self):
        path = _make_tmp_db()
        try:
            em.DB_PATH = path
            em.init_db()
            conn = sqlite3.connect(path)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            conn.close()
            self.assertIn("devices", tables)
            self.assertIn("readings", tables)
            self.assertIn("alerts", tables)
        finally:
            os.unlink(path)

    def test_init_idempotent(self):
        path = _make_tmp_db()
        try:
            em.DB_PATH = path
            em.init_db()
            em.init_db()
        finally:
            os.unlink(path)


class TestEnergyMonitor(unittest.TestCase):
    def setUp(self):
        self.path = _make_tmp_db()
        em.DB_PATH = self.path
        self.monitor = em.EnergyMonitor()

    def tearDown(self):
        self.monitor.close()
        os.unlink(self.path)

    def test_add_device_success(self):
        self.monitor.add_device("dev1", "Washing Machine", "laundry")
        conn = sqlite3.connect(self.path)
        row = conn.execute("SELECT * FROM devices WHERE device_id='dev1'").fetchone()
        conn.close()
        self.assertIsNotNone(row)

    def test_add_device_duplicate_no_exception(self):
        self.monitor.add_device("dup", "Dup", "room")
        self.monitor.add_device("dup", "Dup", "room")  # warn, not raise

    def test_add_reading_persists(self):
        r = em.EnergyReading(device_id="d1", device_name="AC", watts=1500.0)
        self.monitor.add_reading(r)
        conn = sqlite3.connect(self.path)
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_add_reading_assigns_id(self):
        r = em.EnergyReading(device_id="d2", device_name="TV", watts=80.0)
        result = self.monitor.add_reading(r)
        self.assertIsNotNone(result.id)

    def test_add_reading_sets_timestamp(self):
        r = em.EnergyReading(device_id="d3", device_name="Lamp", watts=10.0)
        result = self.monitor.add_reading(r)
        self.assertIsNotNone(result.timestamp)

    def test_get_daily_usage_empty(self):
        stats = self.monitor.get_daily_usage()
        self.assertEqual(stats, [])

    def test_get_daily_usage_after_reading(self):
        self.monitor.add_reading(
            em.EnergyReading(device_id="x1", device_name="Heater", watts=2000.0)
        )
        stats = self.monitor.get_daily_usage()
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].device_id, "x1")
        self.assertGreater(stats[0].daily_kwh, 0)

    def test_daily_cost_calculated(self):
        self.monitor.add_reading(
            em.EnergyReading(device_id="c1", device_name="Oven", watts=3000.0)
        )
        stats = self.monitor.get_daily_usage()
        # cost = kwh * 0.12; for 3000W over 24h = 72kWh * 0.12 = $8.64
        self.assertAlmostEqual(stats[0].daily_cost_usd,
                               stats[0].daily_kwh * em.COST_PER_KWH, places=4)

    def test_anomaly_detected_on_spike(self):
        # Feed 15 normal readings then a spike
        for _ in range(15):
            self.monitor.add_reading(
                em.EnergyReading(device_id="a1", device_name="PC", watts=100.0)
            )
        self.monitor.add_reading(
            em.EnergyReading(device_id="a1", device_name="PC", watts=9999.0)
        )
        anomalies = self.monitor.get_anomalies(limit=5)
        self.assertGreater(len(anomalies), 0)

    def test_get_anomalies_empty(self):
        self.assertEqual(self.monitor.get_anomalies(), [])

    def test_export_report_structure(self):
        self.monitor.add_reading(
            em.EnergyReading(device_id="e1", device_name="Fan", watts=50.0)
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            self.monitor.export_report(path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn("summary", data)
            self.assertIn("devices", data)
            self.assertIn("exported_at", data)
        finally:
            os.unlink(path)

    def test_usage_bar_helper(self):
        bar = em.usage_bar(0.0)
        self.assertIsInstance(bar, str)
        bar_full = em.usage_bar(3000.0)
        self.assertIsInstance(bar_full, str)


if __name__ == "__main__":
    unittest.main()
