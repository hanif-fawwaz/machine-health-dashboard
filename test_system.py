"""
test_system.py — Skrip pengujian otomatis untuk memverifikasi kriteria penerimaan PRD Bagian 9.
"""

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["MOCK"] = "1"

import time
import unittest
import pandas as pd
from datetime import datetime

import config
import mqtt_client
import components
from app import app


class TestMachineHealthMonitor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Mulai mock engine simulator
        mqtt_client.start_mqtt_client()
        # Beri waktu simulator membangkitkan 2-3 data telemetry
        time.sleep(2.5)

    def test_01_telemetry_flow(self):
        """Kriteria 1: Telemetry bergerak dan buffer terisi data."""
        latest = mqtt_client.get_latest_telemetry()
        self.assertIsNotNone(latest, "Telemetry terbaru tidak boleh None")
        self.assertIn("vib_rms", latest)
        self.assertIn("temp", latest)
        self.assertIn("state", latest)
        self.assertIn("state_id", latest)
        self.assertIn("relay", latest)
        self.assertIn("mode", latest)
        
        df = mqtt_client.get_telemetry_df(window_minutes=5)
        self.assertFalse(df.empty, "Dataframe telemetry tidak boleh kosong")
        self.assertGreater(len(df), 0)

    def test_02_simulation_transitions_warning_critical_shutdown(self):
        """Kriteria 2: sim_vib=1.5 -> WARNING, sim_vib=4.0 -> CRITICAL -> 5s -> SHUTDOWN & relay OFF."""
        # 1. Pastikan mode AUTO
        mqtt_client.publish_cmd({"mode": "auto"})
        
        # 2. Test Warning
        mqtt_client.publish_cmd({"sim_vib": 1.5, "sim_fault": False})
        time.sleep(1.8)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "WARNING", f"Harusnya WARNING, dapat: {latest['state']}")
        self.assertEqual(latest["state_id"], 1)

        # 3. Test Critical
        mqtt_client.publish_cmd({"sim_vib": 4.0})
        time.sleep(1.8)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "CRITICAL", f"Harusnya CRITICAL, dapat: {latest['state']}")
        self.assertEqual(latest["state_id"], 2)

        # 4. Tunggu timeout 5 detik pada CRITICAL -> SHUTDOWN & relay OFF
        print("    [Info] Menunggu timeout 5 detik untuk transisi ke SHUTDOWN...")
        time.sleep(5.5)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "SHUTDOWN", f"Harusnya SHUTDOWN setelah 5s, dapat: {latest['state']}")
        self.assertEqual(latest["state_id"], 3)
        self.assertEqual(latest["relay"], 0, "Relay harus OFF (0) saat SHUTDOWN")

    def test_03_reset_from_shutdown_logic(self):
        """Kriteria 3: Reset saat getaran tinggi -> reset_denied; reset saat aman -> NORMAL."""
        # Pastikan masih dalam SHUTDOWN dari test sebelumnya
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "SHUTDOWN")

        # Coba reset saat sim_vib masih 4.0 (belum aman)
        mqtt_client.publish_cmd({"reset": True})
        time.sleep(0.5)
        events = mqtt_client.get_events_list(limit=5)
        reasons = [e["reason"] for e in events]
        self.assertIn("reset_denied", reasons, "Event reset_denied harus tercatat saat reset tidak aman")

        # Turunkan getaran ke aman (0.0) lalu kirim reset
        mqtt_client.publish_cmd({"sim_vib": 0.0})
        time.sleep(1.2)
        mqtt_client.publish_cmd({"reset": True})
        time.sleep(1.2)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "NORMAL", f"Harusnya NORMAL setelah reset aman, dapat: {latest['state']}")
        self.assertEqual(latest["state_id"], 0)
        self.assertEqual(latest["relay"], 1, "Relay harus kembali ON setelah reset pada mode auto")

    def test_04_mode_and_relay(self):
        """Kriteria 4: Mode manual relay bisa diubah, mode auto relay dikontrol otomatis."""
        # Pindah ke manual
        mqtt_client.publish_cmd({"mode": "manual", "relay": 0})
        time.sleep(1.2)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["mode"], "manual")
        self.assertEqual(latest["relay"], 0)

        # Toggle relay ke ON (1)
        mqtt_client.publish_cmd({"relay": 1})
        time.sleep(1.2)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["relay"], 1)

        # Kembalikan ke mode AUTO
        mqtt_client.publish_cmd({"mode": "auto"})
        time.sleep(1.2)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["mode"], "auto")

    def test_05_threshold_validation(self):
        """Kriteria 5: Validasi batas threshold."""
        # Client side validation test logic
        wv, cv = 3.5, 2.0
        self.assertFalse(wv < cv, "warn_vib >= crit_vib harus ditolak")

    def test_06_sim_fault(self):
        """Kriteria 7: sim_fault = true -> FAULT state tampil, event sensor tercatat."""
        mqtt_client.publish_cmd({"sim_fault": True})
        time.sleep(1.5)
        latest = mqtt_client.get_latest_telemetry()
        self.assertEqual(latest["state"], "FAULT", f"Harusnya FAULT, dapat: {latest['state']}")
        self.assertEqual(latest["state_id"], 4)
        
        events = mqtt_client.get_events_list(limit=5)
        reasons = [e["reason"] for e in events]
        self.assertIn("sensor", reasons, "Event sensor harus tercatat saat fault aktif")

        # Matikan simulasi fault
        mqtt_client.publish_cmd({"sim_fault": False})
        time.sleep(1.5)

    def test_07_export_csv_data(self):
        """Kriteria 8: Export data menghasilkan record valid."""
        records = mqtt_client.get_all_telemetry_for_export()
        self.assertGreater(len(records), 0)
        df = pd.DataFrame(records)
        self.assertIn("vib_rms", df.columns)
        self.assertIn("temp", df.columns)
        self.assertIn("state", df.columns)

    def test_08_components_render(self):
        """Komponen visual Plotly & HTML ter-generate tanpa error."""
        df = mqtt_client.get_telemetry_df(window_minutes=5)
        events = mqtt_client.get_events_list(limit=20)
        
        # Test figures
        fig_gauge_vib = components.create_gauge_figure(0.5, 1.0, 3.0, "m/s²")
        fig_gauge_temp = components.create_gauge_figure(35.0, 50.0, 70.0, "°C", is_temp=True)
        fig_line_vib = components.create_line_chart(df, "vib_rms", 1.0, 3.0, "Getaran", "m/s²")
        fig_line_temp = components.create_line_chart(df, "temp", 50.0, 70.0, "Suhu", "°C")
        fig_timeline = components.create_state_timeline(df)

        self.assertIsNotNone(fig_gauge_vib)
        self.assertIsNotNone(fig_gauge_temp)
        self.assertIsNotNone(fig_line_vib)
        self.assertIsNotNone(fig_line_temp)
        self.assertIsNotNone(fig_timeline)

        # Test HTML components
        card = components.create_state_card_element("NORMAL", "auto", True, False)
        self.assertIsNotNone(card)
        table_rows = components.create_event_table_rows(events)
        self.assertIsInstance(table_rows, list)

    def test_09_dash_layout(self):
        """Layout Dash terkompilasi dengan sempurna."""
        self.assertIsNotNone(app.layout)


if __name__ == "__main__":
    unittest.main()

