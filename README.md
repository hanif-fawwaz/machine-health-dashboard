# Machine Health Monitor Dashboard — Tim WIB

Aplikasi web dashboard real-time mandiri (Python Dash + Plotly) untuk memantau dan mengendalikan perangkat **Smart Machine Health Monitor** berbasis ESP32 (sensor getaran MPU6050 + suhu NTC) melalui **MQTT HiveMQ Cloud**.

---

## 1. Arsitektur & Teknologi

- **Bahasa & Framework**: Python 3.10+, `dash`, `plotly`, `pandas`, `paho-mqtt` (2.x), `python-dotenv`.
- **Tanpa Pihak Ketiga**: Murni Python mandiri tanpa platform seperti Grafana, Node-RED, Blynk, atau Streamlit.
- **Protokol Komunikasi**: MQTT v3.1.1/v5 melalui TLS (port 8883) ke HiveMQ Cloud dengan Client ID unik.
- **Sumbu Waktu**: Menggunakan waktu lokal saat data diterima di dashboard (`datetime.now()`), bukan `millis()` ESP32.
- **Keamanan Thread**: Buffer memori `collections.deque` (3600 titik telemetry = 1 jam pada 1 Hz, 200 event perubahan state) dilindungi `threading.Lock`.

### Struktur File

```
Project_samsung_dasboard/
├── app.py              # Entry point: Layout Dash, interval callbacks 1000ms, kontrol interaktif
├── mqtt_client.py      # Background MQTT client (paho 2.x), buffer thread-safe, & Mock Simulator
├── config.py           # Loader variabel lingkungan (.env), konstanta topik, palet warna
├── components.py       # Generator Plotly (Gauges, Line Charts, Timeline) & Komponen HTML
├── assets/
│   └── style.css       # Desain tema Industrial Control-Room gelap, responsif 12 kolom
├── requirements.txt    # Dependensi pustaka Python
├── .env.example        # Template konfigurasi kredensial (tanpa rahasia)
├── .gitignore          # Mengabaikan .env, __pycache__, logs, dll.
├── PRD.md              # Dokumen Product Requirements & Kontrak MQTT
├── design.md           # Dokumen Desain Visual & UI Guidelines
└── README.md           # Panduan lengkap instalasi, arsitektur, dan cara tes
```

---

## 2. Kontrak Topik & Data MQTT (Team ID: `WIB`)

| Topik | Arah | Format | Keterangan |
|---|---|---|---|
| `sic8/WIB/telemetry` | Device $\rightarrow$ Dashboard | JSON (1 Hz) | Data real-time getaran RMS, suhu, status relay, mode, fault, threshold |
| `sic8/WIB/event` | Device $\rightarrow$ Dashboard | JSON | Dipublish saat terjadi transisi state beserta alasannya |
| `sic8/WIB/status` | Device $\rightarrow$ Dashboard | Teks (`online`/`offline`) | Retained LWT (Last Will and Testament) status perangkat |
| `sic8/WIB/cmd` | Dashboard $\rightarrow$ Device | JSON | Perintah kontrol (mode, relay, threshold, reset, simulasi) |

### Contoh Payload JSON

**Telemetry (`sic8/WIB/telemetry`)**:
```json
{
  "type": "telemetry",
  "ts": 123456,
  "vib_rms": 0.512,
  "temp": 34.2,
  "state": "NORMAL",
  "state_id": 0,
  "vib_level": 0,
  "temp_level": 0,
  "relay": 1,
  "mode": "auto",
  "fault": 0,
  "warn_vib": 1.00,
  "crit_vib": 3.00,
  "warn_temp": 50.0,
  "crit_temp": 70.0
}
```

**Event (`sic8/WIB/event`)**:
```json
{
  "type": "event",
  "ts": 123456,
  "from": "NORMAL",
  "to": "WARNING",
  "to_id": 1,
  "reason": "vib"
}
```

**Command (`sic8/WIB/cmd`)**:
```json
{
  "set_warn_vib": 1.00,
  "set_crit_vib": 3.00,
  "set_warn_temp": 50.0,
  "set_crit_temp": 70.0,
  "mode": "auto",
  "relay": 1,
  "sim_vib": 0.0,
  "sim_fault": false,
  "calibrate": true,
  "reset": true
}
```

---

## 3. Cara Instalasi & Menjalankan

### Langkah 1: Pasang Dependensi
Buka terminal / PowerShell di root proyek dan jalankan:
```powershell
pip install -r requirements.txt
```

### Langkah 2: Konfigurasi Kredensial (.env)
Salin file `.env.example` menjadi `.env`:
```powershell
cp .env.example .env
```
Buka file `.env` dan masukkan informasi cluster HiveMQ Cloud Anda:
```ini
MQTT_HOST=your-cluster-id.s1.eu.hivemq.cloud
MQTT_PORT=8883
MQTT_USER=dashboard_user
MQTT_PASS=dashboard_password
TEAM_ID=WIB

# Set MOCK=1 jika ingin menjalankan pengujian simulasi offline tanpa broker/hardware
MOCK=0
```

> [!TIP]
> Disarankan membuat dua akun user di HiveMQ Cloud Access Management: satu untuk ESP32/Wokwi, dan satu untuk Dashboard.

### Langkah 3: Jalankan Dashboard
Cukup jalankan satu perintah:
```powershell
python app.py
```
Buka peramban (browser) di:
```
http://localhost:8050
```

---

## 4. Fitur-Fitur Utama

1. **Header & Status Konektivitas**:
   - Titik status koneksi **Broker** (hijau = connected, abu-abu = disconnected).
   - Titik status perangkat **Device** (dari LWT retained status).
   - Label **Data Age**: Menghitung selisih detik data terakhir, otomatis memberi tanda **STALE** berwarna abu-abu jika > 5 detik tanpa data.
   - Dropdown Jendela Waktu (1m, 5m, 15m, 60m).
   - Tombol **Export CSV** untuk mengunduh riwayat telemetri dalam memori.

2. **State Card Industrial**:
   - Strip kiri 6px dengan warna dinamis sesuai state (`NORMAL`, `WARNING`, `CRITICAL`, `SHUTDOWN`, `FAULT`).
   - Teks state besar (48px) dengan efek animasi pulse pada `SHUTDOWN` dan kedip pada `FAULT`.
   - Chip status badge: `AUTO`/`MANUAL`, `RELAY ON`/`OFF`, dan `FAULT ACTIVE`.

3. **Gauges & Grafik Interaktif**:
   - 2 Speedometer Gauge: Getaran RMS (m/s²) dan Suhu Mesin (°C) dengan zona warna transparan (hijau $\rightarrow$ kuning $\rightarrow$ merah) sesuai batas threshold aktif.
   - 2 Grafik Garis Real-Time: Garis threshold putus-putus dengan anotasi di kanan. Dilengkapi fitur `uirevision="keep"` sehingga zoom atau panning tidak akan ter-reset saat refresh data 1 detik.
   - **State Timeline**: Step chart horizontal yang memvisualisasikan riwayat transisi level state.

4. **Tabel Riwayat Event**:
   - Menampilkan 20 transisi event terakhir dengan header sticky.
   - Badge warna chip transisi asal $\rightarrow$ tujuan.
   - Baris khusus `reset_denied` bergaris kuning dengan peringatan icon ⚠.

5. **Panel Kontrol Mesin**:
   - **Mode & Relay**: Segmented switch AUTO / MANUAL. Tombol toggle relay terkunci saat mode AUTO dan hanya dapat dioperasikan saat MANUAL.
   - **Threshold**: 4 input batas getaran dan suhu dengan tombol *Apply* yang divalidasi langsung di sisi klien (`warn < crit` dan `warn > 0`). Menampilkan pesan error merah jika tidak valid.
   - **Aksi**: Tombol *Reset Shutdown* (hanya aktif saat state SHUTDOWN) dan tombol *Calibrate*.
   - **Simulasi Pengujian**: Preset cepat (*Normal*, *Warning*, *Critical*), slider `sim_vib` (0–6), dan sakelar `sim_fault`.

---

## 5. Prosedur Pengujian Kriteria Penerimaan (Acceptance Criteria)

Untuk menguji seluruh kriteria penerimaan tanpa perangkat fisik, aktifkan `MOCK=1` di `.env` (atau hapus host broker), lalu jalankan `python app.py`:

| No | Kriteria Penerimaan | Langkah Pengujian | Hasil yang Diharapkan |
|:--:|---|---|---|
| **1** | Telemetri Real-Time | Buka dashboard di browser | Grafik dan gauge diperbarui setiap detik secara mulus tanpa reset posisi zoom |
| **2** | State Warning & Critical | Klik tombol preset **Warning (1.5)**, lalu **Critical (4.0)** | State card berubah menjadi kuning WARNING dalam $\le$ 3 detik, lalu merah CRITICAL. Jika ditahan di CRITICAL $\ge$ 5 detik pada mode AUTO, mesin otomatis berpindah ke **SHUTDOWN** dan Relay mati (OFF) |
| **3** | Logika Reset SHUTDOWN | Saat state SHUTDOWN, klik tombol **RESET SHUTDOWN** saat getaran masih tinggi. Lalu ubah getaran ke 0 (`sim_vib=0`) dan klik RESET lagi | Saat getaran tinggi, reset ditolak dan muncul baris event berlabel `reset_denied` ⚠. Setelah getaran aman (0.0), tombol reset berhasil mengembalikan mesin ke state NORMAL |
| **4** | Kontrol Mode & Relay | Tekan tombol MANUAL, lalu klik TOGGLE RELAY. Setelah itu tekan tombol AUTO | Di mode MANUAL, relay dapat dihidupkan/dimatikan bebas. Di mode AUTO, tombol toggle relay dinonaktifkan (disabled) |
| **5** | Validasi Threshold | Masukkan input *Warn Vib = 3.5* dan *Crit Vib = 2.0* lalu tekan *Apply Thresholds* | Input ditolak di antarmuka dengan notifikasi error merah; tidak ada data tidak valid yang dikirim ke perangkat |
| **6** | Status Stale & Offline | Simulasikan jeda data > 5 detik | Label usia data berubah menjadi **STALE** dengan warna abu-abu `#64748B` |
| **7** | Simulasi Sensor Error | Centang kotak **Simulasi Sensor Rusak (sim_fault)** | State mesin langsung berubah menjadi **FAULT** (warna ungu), strip berkedip, dan tercatat event `sensor` di tabel |
| **8** | Ekspor CSV | Klik tombol **Export CSV** di header | File `.csv` terunduh dan dapat dibuka dengan rapi di Microsoft Excel atau spreadsheet lainnya |
| **9** | Integritas Kredensial | Periksa file `.gitignore` dan git status | File `.env` tidak masuk ke version control, tidak ada password/token yang terekspos |

