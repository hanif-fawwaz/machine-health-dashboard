"""
mqtt_client.py — Handler koneksi MQTT HiveMQ Cloud, buffer thread-safe, dan Mock Simulator Engine.
Mematuhi kontrak MQTT pada PRD.md Bagian 5 dan kriteria penerimaan Bagian 9.
"""

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import json
import logging
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta
import pandas as pd

from config import (
    MQTT_HOST,
    MQTT_PORT,
    MQTT_USER,
    MQTT_PASS,
    TEAM_ID,
    MOCK_MODE,
    TOPIC_TELEMETRY,
    TOPIC_EVENT,
    TOPIC_STATUS,
    TOPIC_CMD,
    STATE_NORMAL,
    STATE_WARNING,
    STATE_CRITICAL,
    STATE_SHUTDOWN,
    STATE_FAULT,
    STATE_ID_TO_NAME,
    DEFAULT_WARN_VIB,
    DEFAULT_CRIT_VIB,
    DEFAULT_WARN_TEMP,
    DEFAULT_CRIT_TEMP,
)

logger = logging.getLogger("mqtt_client")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# Inisialisasi Buffer Thread-Safe
_lock = threading.Lock()
# Buffer telemetry: 3600 titik (1 jam pada 1 Hz)
_telemetry_buffer = deque(maxlen=3600)
# Buffer event: 200 event
_event_buffer = deque(maxlen=200)

# Status Koneksi & Perangkat
_broker_connected = False
_device_online = False
_last_telemetry_time = None

# Referensi MQTT Client
_mqtt_client = None


# ==============================================================================
# MOCK SIMULATOR ENGINE (Untuk mode offline & pengujian kriteria FR-1 s/d FR-9)
# ==============================================================================
class MockDeviceSimulator(threading.Thread):
    """
    Simulator ESP32 internal yang mereplikasi firmware Smart Machine Health Monitor
    secara presisi saat MOCK_MODE=True atau broker eksternal tidak aktif.
    """
    def __init__(self):
        super().__init__(daemon=True)
        self.running = True
        self.state = STATE_NORMAL
        self.state_id = 0
        self.mode = "auto"          # "auto" atau "manual"
        self.relay = 1              # 1 = ON, 0 = OFF
        self.fault = 0              # 0 = normal, 1 = sensor rusak
        
        # Thresholds
        self.warn_vib = DEFAULT_WARN_VIB
        self.crit_vib = DEFAULT_CRIT_VIB
        self.warn_temp = DEFAULT_WARN_TEMP
        self.crit_temp = DEFAULT_CRIT_TEMP

        # Kontrol simulasi
        self.sim_vib = 0.0          # RMS sintetis
        self.sim_fault = False      # boolean simulasi error
        self.crit_enter_time = None # Waktu mulai masuk CRITICAL (untuk timer 5s)
        self.base_temp = 34.0       # Suhu dasar normal

    def handle_command(self, cmd: dict):
        """Menerima dan memproses perintah JSON yang dikirim ke topic sic8/WIB/cmd"""
        with _lock:
            # 1. Update Thresholds jika valid (warn < crit)
            if "set_warn_vib" in cmd:
                self.warn_vib = float(cmd["set_warn_vib"])
            if "set_crit_vib" in cmd:
                self.crit_vib = float(cmd["set_crit_vib"])
            if "set_warn_temp" in cmd:
                self.warn_temp = float(cmd["set_warn_temp"])
            if "set_crit_temp" in cmd:
                self.crit_temp = float(cmd["set_crit_temp"])

            # 2. Mode auto / manual
            if "mode" in cmd and cmd["mode"] in ("auto", "manual"):
                self.mode = cmd["mode"]
                if self.mode == "auto":
                    # Jika kembali ke auto dan mesin normal/warning, relay otomatis ON
                    if self.state in (STATE_NORMAL, STATE_WARNING, STATE_CRITICAL):
                        self.relay = 1

            # 3. Relay (hanya berlaku saat mode manual)
            if "relay" in cmd:
                if self.mode == "manual":
                    self.relay = int(cmd["relay"])
                else:
                    logger.info("Perintah relay diabaikan karena perangkat dalam mode AUTO")

            # 4. Simulasi getaran
            if "sim_vib" in cmd:
                self.sim_vib = max(0.0, float(cmd["sim_vib"]))

            # 5. Simulasi fault sensor
            if "sim_fault" in cmd:
                self.sim_fault = bool(cmd["sim_fault"])

            # 6. Kalibrasi
            if cmd.get("calibrate"):
                logger.info("MOCK: Baseline MPU6050 dikalibrasi.")

            # 7. Reset dari SHUTDOWN
            if cmd.get("reset"):
                now = datetime.now()
                # Kondisi aman: sim_vib < crit_vib dan sim_fault == False
                if self.state == STATE_SHUTDOWN:
                    if self.sim_vib < self.crit_vib and not self.sim_fault:
                        prev_state = self.state
                        self.state = STATE_NORMAL
                        self.state_id = 0
                        self.crit_enter_time = None
                        if self.mode == "auto":
                            self.relay = 1
                        _record_event_unlocked(now, prev_state, self.state, self.state_id, "reset")
                    else:
                        # Belum aman -> reset ditolak!
                        _record_event_unlocked(now, self.state, self.state, self.state_id, "reset_denied")

    def run(self):
        global _device_online, _broker_connected
        _broker_connected = True
        _device_online = True
        
        while self.running:
            time.sleep(1.0)
            now = datetime.now()
            
            with _lock:
                # Menghitung getaran efektif (noise acak kecil + sim_vib)
                base_vib = random.uniform(0.35, 0.48)
                current_vib = round(base_vib + self.sim_vib, 3)

                # Menghitung suhu efektif (variasi kecil)
                temp_fluct = random.uniform(-0.3, 0.4)
                current_temp = round(self.base_temp + temp_fluct, 1)

                # Evaluasi fault sensor
                self.fault = 1 if self.sim_fault else 0

                prev_state = self.state
                
                # --- State Machine Logic ---
                if self.fault == 1:
                    new_state = STATE_FAULT
                    new_id = 4
                    reason = "sensor"
                    self.crit_enter_time = None
                elif self.state == STATE_SHUTDOWN:
                    # Tetap dalam SHUTDOWN sampai ada perintah reset yang valid
                    new_state = STATE_SHUTDOWN
                    new_id = 3
                    reason = None
                    self.relay = 0
                else:
                    # Evaluasi getaran
                    if current_vib >= self.crit_vib:
                        v_level = 2
                    elif current_vib >= self.warn_vib:
                        v_level = 1
                    else:
                        v_level = 0

                    # Evaluasi suhu
                    if current_temp >= self.crit_temp:
                        t_level = 2
                    elif current_temp >= self.warn_temp:
                        t_level = 1
                    else:
                        t_level = 0

                    max_level = max(v_level, t_level)
                    if max_level == 2:
                        new_state = STATE_CRITICAL
                        new_id = 2
                        reason = "vib+temp" if (v_level == 2 and t_level == 2) else ("vib" if v_level == 2 else "temp")
                        
                        # Cek timeout 5 detik pada mode auto
                        if self.crit_enter_time is None:
                            self.crit_enter_time = now
                        elif (now - self.crit_enter_time).total_seconds() >= 5.0 and self.mode == "auto":
                            new_state = STATE_SHUTDOWN
                            new_id = 3
                            reason = "crit_timeout"
                            self.relay = 0
                            self.crit_enter_time = None
                    elif max_level == 1:
                        new_state = STATE_WARNING
                        new_id = 1
                        reason = "vib+temp" if (v_level == 1 and t_level == 1) else ("vib" if v_level == 1 else "temp")
                        self.crit_enter_time = None
                    else:
                        new_state = STATE_NORMAL
                        new_id = 0
                        reason = "recovered"
                        self.crit_enter_time = None

                # Catat event jika terjadi transisi state
                if new_state != prev_state and reason:
                    self.state = new_state
                    self.state_id = new_id
                    _record_event_unlocked(now, prev_state, new_state, new_id, reason)
                else:
                    self.state = new_state
                    self.state_id = new_id

                # Buat payload telemetry sesuai PRD Bagian 5.1
                vib_level = 2 if current_vib >= self.crit_vib else (1 if current_vib >= self.warn_vib else 0)
                temp_level = 2 if current_temp >= self.crit_temp else (1 if current_temp >= self.warn_temp else 0)

                telemetry_data = {
                    "type": "telemetry",
                    "ts": int(time.time() * 1000),  # millis perangkat
                    "vib_rms": current_vib,
                    "temp": current_temp,
                    "state": self.state,
                    "state_id": self.state_id,
                    "vib_level": vib_level,
                    "temp_level": temp_level,
                    "relay": self.relay,
                    "mode": self.mode,
                    "fault": self.fault,
                    "warn_vib": self.warn_vib,
                    "crit_vib": self.crit_vib,
                    "warn_temp": self.warn_temp,
                    "crit_temp": self.crit_temp,
                }
                
                # Simpan ke buffer dengan sumbu X waktu terima lokal dashboard
                _record_telemetry_unlocked(now, telemetry_data)


# Instance Mock Simulator
_mock_instance = None


def _record_telemetry_unlocked(received_dt: datetime, data: dict):
    """Menyimpan telemetry ke deque (asumsi lock sudah di-acquire)"""
    global _last_telemetry_time
    _last_telemetry_time = received_dt
    
    record = {
        "datetime": received_dt,
        "time_str": received_dt.strftime("%H:%M:%S"),
        "vib_rms": float(data.get("vib_rms", 0.0)),
        "temp": float(data.get("temp", 0.0)),
        "state": str(data.get("state", STATE_NORMAL)),
        "state_id": int(data.get("state_id", 0)),
        "vib_level": int(data.get("vib_level", 0)),
        "temp_level": int(data.get("temp_level", 0)),
        "relay": int(data.get("relay", 0)),
        "mode": str(data.get("mode", "auto")),
        "fault": int(data.get("fault", 0)),
        "warn_vib": float(data.get("warn_vib", DEFAULT_WARN_VIB)),
        "crit_vib": float(data.get("crit_vib", DEFAULT_CRIT_VIB)),
        "warn_temp": float(data.get("warn_temp", DEFAULT_WARN_TEMP)),
        "crit_temp": float(data.get("crit_temp", DEFAULT_CRIT_TEMP)),
    }
    _telemetry_buffer.append(record)


def _record_event_unlocked(received_dt: datetime, from_state: str, to_state: str, to_id: int, reason: str):
    """Menyimpan event ke deque (asumsi lock sudah di-acquire)"""
    event_record = {
        "datetime": received_dt,
        "time_str": received_dt.strftime("%H:%M:%S"),
        "from": from_state,
        "to": to_state,
        "to_id": to_id,
        "reason": reason,
    }
    _event_buffer.append(event_record)


# ==============================================================================
# MQTT CALLBACKS & SUBSCRIPTIONS (paho-mqtt 2.x)
# ==============================================================================
def _on_connect(client, userdata, flags, rc, properties=None):
    global _broker_connected
    if rc == 0:
        logger.info(f"Terhubung ke broker HiveMQ Cloud ({MQTT_HOST}:{MQTT_PORT})")
        _broker_connected = True
        
        # Subscribe ke topic telemetry, event, status
        client.subscribe([
            (TOPIC_TELEMETRY, 0),
            (TOPIC_EVENT, 0),
            (TOPIC_STATUS, 0),
        ])
        logger.info(f"Subscribed ke topik: {TOPIC_TELEMETRY}, {TOPIC_EVENT}, {TOPIC_STATUS}")
    else:
        logger.error(f"Gagal terhubung ke broker MQTT (rc={rc})")
        _broker_connected = False


def _on_disconnect(client, userdata, disconnect_flags, rc, properties=None):
    global _broker_connected, _device_online
    logger.warning(f"Koneksi broker MQTT terputus (rc={rc})")
    _broker_connected = False
    _device_online = False


def _on_message(client, userdata, msg):
    global _device_online
    now = datetime.now()
    topic = msg.topic
    
    try:
        payload_str = msg.payload.decode("utf-8").strip()
        
        # 1. Topic Status (Device Online / Offline retained LWT)
        if topic == TOPIC_STATUS:
            with _lock:
                _device_online = (payload_str.lower() == "online")
                logger.info(f"Device status update: {_device_online} ({payload_str})")
            return

        # 2. Topic Telemetry & Event berbentuk JSON
        data = json.loads(payload_str)
        
        if topic == TOPIC_TELEMETRY:
            with _lock:
                _record_telemetry_unlocked(now, data)
                # Device otomatis dianggap online jika mengirim telemetry
                _device_online = True
                
        elif topic == TOPIC_EVENT:
            with _lock:
                from_state = str(data.get("from", "UNKNOWN"))
                to_state = str(data.get("to", "UNKNOWN"))
                to_id = int(data.get("to_id", 0))
                reason = str(data.get("reason", "unknown"))
                _record_event_unlocked(now, from_state, to_state, to_id, reason)
                logger.info(f"Event diterima: {from_state} -> {to_state} ({reason})")

    except json.JSONDecodeError:
        logger.warning(f"JSON rusak diabaikan dari {topic}: {msg.payload[:100]}")
    except Exception as e:
        logger.error(f"Error memproses pesan MQTT di {topic}: {e}")


# ==============================================================================
# PUBLIC API MODULE
# ==============================================================================
def start_mqtt_client():
    """Memulai MQTT client paho di thread terpisah atau mengaktifkan Mock Simulator."""
    global _mqtt_client, _mock_instance

    if MOCK_MODE or not MQTT_HOST:
        logger.info("=== MODE MOCK SIMULATOR DIAKTIFKAN ===")
        _mock_instance = MockDeviceSimulator()
        _mock_instance.start()
        return

    # Inisialisasi client paho-mqtt v2
    import paho.mqtt.client as mqtt

    client_id = f"dash-{TEAM_ID}-{random.randint(1000, 9999)}"
    logger.info(f"Menginisialisasi paho-mqtt Client ID: {client_id}")

    try:
        # Gunakan API Version 2 untuk paho-mqtt 2.x
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        
        if MQTT_USER and MQTT_PASS:
            client.username_pw_set(MQTT_USER, MQTT_PASS)

        # TLS aktif untuk port 8883
        client.tls_set()

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect
        client.on_message = _on_message

        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=30)
        client.loop_start()
        _mqtt_client = client

    except Exception as e:
        logger.error(f"Koneksi ke HiveMQ Cloud gagal: {e}. Mengalihkan ke internal MOCK.")
        _mock_instance = MockDeviceSimulator()
        _mock_instance.start()


def publish_cmd(cmd_dict: dict) -> bool:
    """
    Mengirim perintah kontrol ke topik sic8/WIB/cmd.
    Jika dalam mode MOCK, langsung diteruskan ke mesin simulator.
    """
    global _mqtt_client, _mock_instance
    
    if _mock_instance is not None:
        _mock_instance.handle_command(cmd_dict)
        return True

    if _mqtt_client is not None and _broker_connected:
        try:
            payload = json.dumps(cmd_dict)
            _mqtt_client.publish(TOPIC_CMD, payload, qos=1)
            logger.info(f"Perintah dipublish ke {TOPIC_CMD}: {payload}")
            return True
        except Exception as e:
            logger.error(f"Gagal publish command ke MQTT: {e}")
            return False
            
    logger.warning("Gagal publish: Broker tidak terhubung")
    return False


def get_connection_status():
    """
    Mengembalikan (broker_connected, device_online, data_age_sec, is_stale).
    Data ditandai STALE jika waktu data terakhir > 5 detik.
    """
    with _lock:
        now = datetime.now()
        if _last_telemetry_time is not None:
            age_sec = (now - _last_telemetry_time).total_seconds()
            is_stale = (age_sec > 5.0)
        else:
            age_sec = None
            is_stale = True

        return _broker_connected, _device_online, age_sec, is_stale


def get_latest_telemetry() -> dict | None:
    """Mengembalikan snapshot data telemetry terbaru."""
    with _lock:
        if _telemetry_buffer:
            return dict(_telemetry_buffer[-1])
        return None


def get_telemetry_df(window_minutes: int = 5) -> pd.DataFrame:
    """
    Mengembalikan dataframe telemetry yang difilter sesuai jendela waktu (menit).
    Snapshot aman ber-lock.
    """
    with _lock:
        if not _telemetry_buffer:
            return pd.DataFrame()
        records = list(_telemetry_buffer)

    df = pd.DataFrame(records)
    if df.empty or "datetime" not in df.columns:
        return pd.DataFrame()

    # Filter berdasarkan jendela waktu
    cutoff_time = datetime.now() - timedelta(minutes=window_minutes)
    filtered_df = df[df["datetime"] >= cutoff_time]
    return filtered_df


def get_events_list(limit: int = 20) -> list:
    """Mengembalikan daftar event terbaru (terbaru di atas) maksimum sebanyak limit."""
    with _lock:
        events = list(_event_buffer)
    # Urutkan terbaru di atas
    events.reverse()
    return events[:limit]


def get_all_telemetry_for_export() -> list:
    """Snapshot seluruh buffer telemetry untuk ekspor CSV."""
    with _lock:
        return list(_telemetry_buffer)


def get_all_events_for_export() -> list:
    """Snapshot seluruh buffer event untuk ekspor CSV."""
    with _lock:
        return list(_event_buffer)
