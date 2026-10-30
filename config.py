"""
config.py — Konfigurasi aplikasi, kredensial MQTT, konstanta topik, dan tema warna.
Memuat variabel dari file .env secara aman tanpa mengekspos kredensial.
"""

import os
# Optimasi thread OpenBLAS untuk Windows
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from dotenv import load_dotenv

# Muat file .env jika ada
load_dotenv()

# Kredensial dan setting MQTT HiveMQ Cloud
MQTT_HOST = os.getenv("MQTT_HOST", "").strip()
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER", "").strip()
MQTT_PASS = os.getenv("MQTT_PASS", "").strip()
TEAM_ID = os.getenv("TEAM_ID", "WIB").strip()

# Mode Mock Simulator (aktif jika MOCK=1 atau jika host broker belum diisi)
_mock_env = os.getenv("MOCK", "").lower()
if _mock_env in ("1", "true", "yes"):
    MOCK_MODE = True
elif _mock_env in ("0", "false", "no"):
    MOCK_MODE = False
else:
    # Otomatis aktifkan mock jika kredensial broker belum dikonfigurasi
    MOCK_MODE = (len(MQTT_HOST) == 0)

# Kontrak Topik MQTT (Topic base sic8/WIB)
TOPIC_TELEMETRY = f"sic8/{TEAM_ID}/telemetry"
TOPIC_EVENT = f"sic8/{TEAM_ID}/event"
TOPIC_STATUS = f"sic8/{TEAM_ID}/status"
TOPIC_CMD = f"sic8/{TEAM_ID}/cmd"

# Mapping State Mesin
STATE_NORMAL = "NORMAL"
STATE_WARNING = "WARNING"
STATE_CRITICAL = "CRITICAL"
STATE_SHUTDOWN = "SHUTDOWN"
STATE_FAULT = "FAULT"

STATE_ID_TO_NAME = {
    0: STATE_NORMAL,
    1: STATE_WARNING,
    2: STATE_CRITICAL,
    3: STATE_SHUTDOWN,
    4: STATE_FAULT,
}

STATE_NAME_TO_ID = {
    STATE_NORMAL: 0,
    STATE_WARNING: 1,
    STATE_CRITICAL: 2,
    STATE_SHUTDOWN: 3,
    STATE_FAULT: 4,
}

# Nilai default threshold
DEFAULT_WARN_VIB = 1.00
DEFAULT_CRIT_VIB = 3.00
DEFAULT_WARN_TEMP = 50.0
DEFAULT_CRIT_TEMP = 70.0

# Palet Warna Industrial Control-Room (design.md)
COLOR_BG = "#0B0F14"
COLOR_SURFACE = "#121821"
COLOR_SURFACE_2 = "#1A2230"
COLOR_BORDER = "#263043"
COLOR_TEXT = "#E6EAF0"
COLOR_TEXT_DIM = "#8A97AB"
COLOR_ACCENT = "#38BDF8"
COLOR_NORMAL = "#22C55E"
COLOR_WARNING = "#F59E0B"
COLOR_CRITICAL = "#EF4444"
COLOR_SHUTDOWN = "#B91C1C"
COLOR_FAULT = "#A855F7"
COLOR_STALE = "#64748B"

STATE_COLORS = {
    STATE_NORMAL: COLOR_NORMAL,
    STATE_WARNING: COLOR_WARNING,
    STATE_CRITICAL: COLOR_CRITICAL,
    STATE_SHUTDOWN: COLOR_SHUTDOWN,
    STATE_FAULT: COLOR_FAULT,
}
