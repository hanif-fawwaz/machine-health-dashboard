# DOKUMENTASI LENGKAP PROYEK
## Machine Health Monitor Dashboard — Tim WIB

Dokumentasi resmi arsitektur, panduan menjalankan aplikasi, dan petunjuk pemeliharaan serta pengembangan ke depan untuk proyek **Machine Health Monitor Dashboard**.

---

## 1. Ringkasan & Arsitektur Sistem

Dashboard ini adalah aplikasi web mandiri berbasis **Python** (tanpa ketergantungan pada platform pihak ketiga seperti Grafana, Node-RED, Blynk, atau Streamlit). Aplikasi ini berfungsi untuk memantau metrik getaran RMS dan suhu mesin industri secara real-time, menampilkan riwayat perubahan state, serta mengirimkan perintah kendali (threshold, mode, relay, kalibrasi, reset) ke perangkat ESP32 melalui broker **MQTT HiveMQ Cloud**.

### 1.1 Stack Teknologi
- **Bahasa**: Python 3.10+
- **Framework Web**: `dash` (Flask + React di balik layar)
- **Visualisasi Grafik**: `plotly` (`plotly.graph_objects`)
- **Protokol IoT**: `paho-mqtt` 2.x dengan enkripsi TLS (Port 8883)
- **Manipulasi Data**: `pandas`
- **Konfigurasi Keamanan**: `python-dotenv`

### 1.2 Struktur Folder & File
```
Project_samsung_dasboard/
├── app.py                  # Entry point: Layout Dash, interval refresh 1000 ms, & callback kontrol
├── mqtt_client.py          # Background MQTT client, thread-safe memory buffer, & Mock Simulator
├── components.py           # Generator figure Plotly (Gauges, Line Charts, Timeline) & HTML cards/tables
├── config.py               # Pengaturan lingkungan (.env), konstanta topik MQTT, & palet tema
├── test_system.py          # Skrip pengujian otomatis 9 kriteria penerimaan (Acceptance Criteria)
├── assets/
│   └── style.css           # Desain Industrial Control-Room gelap, CSS grid 12 kolom, & animasi
├── requirements.txt        # Daftar dependensi pustaka Python
├── .env.example            # Template konfigurasi variabel lingkungan aman
├── .gitignore              # Mengecualikan file sensitif (.env, log, virtual environment)
├── PRD.md                  # Dokumen Product Requirement Document & Kontrak Data MQTT
├── design.md               # Spesifikasi visual, tipografi, dan tata letak
├── README.md               # Panduan ringkas repository
└── DOKUMENTASI_LENGKAP.md  # File dokumentasi menyeluruh ini
```

---

## 2. Kontrak Data MQTT (Topic Base: `sic8/WIB`)

| Topik | Arah | Format | Keterangan |
|---|---|---|---|
| `sic8/WIB/telemetry` | ESP32 $\rightarrow$ Dashboard | JSON (1 Hz) | Data telemetri getaran RMS, suhu, status relay, mode, batas threshold |
| `sic8/WIB/event` | ESP32 $\rightarrow$ Dashboard | JSON | Dipublish setiap terjadi perubahan state beserta alasannya |
| `sic8/WIB/status` | ESP32 $\rightarrow$ Dashboard | Teks (`online`/`offline`) | Pesan LWT (*Last Will and Testament*) retained status perangkat |
| `sic8/WIB/cmd` | Dashboard $\rightarrow$ ESP32 | JSON | Perintah kontrol (mode, relay, batas threshold, reset, simulasi) |

### 2.1 Format Payload Telemetry
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
*Catatan Penting: Sumbu X pada grafik dashboard menggunakan waktu terima lokal komputer dashboard (`datetime.now()`), bukan `millis()` perangkat.*

### 2.2 Format Payload Event
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
*Alasan (reason): `vib`, `temp`, `vib+temp`, `recovered`, `sensor`, `crit_timeout`, `reset`, `reset_denied`.*

### 2.3 Format Payload Command
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

## 3. Cara Menjalankan Aplikasi (Running)

### 3.1 Persiapan Awal
Pastikan dependensi telah terinstal:
```powershell
pip install -r requirements.txt
```

---

### 3.2 Opsi A: Mode Mock Simulator (Tanpa Hardware / Demo Offline)
Mode ini sangat praktis untuk demonstrasi dan evaluasi cepat tanpa memerlukan perangkat ESP32 fisik maupun koneksi broker eksternal:
1. Pastikan variabel `MOCK=1` aktif (atau biarkan host di file `.env` kosong).
2. Jalankan server:
   ```powershell
   python app.py
   ```
3. Buka peramban di:
   ```
   http://localhost:8050
   ```
   *Mesin simulator bawaan akan mengalirkan data telemetri 1 Hz secara otomatis. Anda dapat mencoba menaikkan getaran via tombol preset atau slider untuk melihat reaksi transisi WARNING $\rightarrow$ CRITICAL $\rightarrow$ timeout 5 detik ke SHUTDOWN $\rightarrow$ RESET.*

---

### 3.3 Opsi B: Mode Produksi / Broker Nyata (HiveMQ Cloud + ESP32 / Wokwi)
1. Buat file `.env` dari `.env.example`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Isi informasi cluster HiveMQ Cloud Anda di file `.env`:
   ```ini
   MQTT_HOST=your-cluster-id.s1.eu.hivemq.cloud
   MQTT_PORT=8883
   MQTT_USER=dashboard_user
   MQTT_PASS=dashboard_password
   TEAM_ID=WIB
   MOCK=0
   ```
3. Jalankan aplikasi:
   ```powershell
   python app.py
   ```
4. Buka `http://localhost:8050`. Dashboard akan langsung terhubung via TLS port 8883 dan menampilkan data dari perangkat keras Anda.

---

### 3.4 Menjalankan Skrip Pengujian Otomatis
Untuk memvalidasi bahwa seluruh kriteria penerimaan berfungsi dengan baik:
```powershell
python test_system.py
```
Hasil uji:
```
Ran 9 tests in 21.814s
OK
```

---

## 4. Panduan Pemeliharaan & Pengembangan ke Depan

Kode proyek telah disusun dengan prinsip modularitas tinggi agar memudahkan pengembangan selanjutnya:

### 4.1 Menambahkan Sensor Baru (Contoh: Sensor Arus Listrik / Tekanan)
Jika di masa depan mesin dilengkapi sensor baru (misal `current_amp`):
1. **Konfigurasi ([`config.py`](file:///d:/Project/Project_samsung_dasboard/config.py))**:
   Tambahkan nilai batas default:
   ```python
   DEFAULT_WARN_CURRENT = 10.0
   DEFAULT_CRIT_CURRENT = 15.0
   ```
2. **Buffer Data ([`mqtt_client.py`](file:///d:/Project/Project_samsung_dasboard/mqtt_client.py))**:
   Di fungsi `_record_telemetry_unlocked()`, ekstrak atribut baru:
   ```python
   "current_amp": float(data.get("current_amp", 0.0))
   ```
3. **Komponen Visual ([`components.py`](file:///d:/Project/Project_samsung_dasboard/components.py))**:
   Gunakan fungsi grafik yang sudah ada:
   ```python
   fig_current = create_line_chart(df, "current_amp", warn_val, crit_val, "Arus Mesin", "A")
   ```
4. **Tampilan Web ([`app.py`](file:///d:/Project/Project_samsung_dasboard/app.py))**:
   Tambahkan `dcc.Graph(id="chart-current")` pada layout dan daftarkan di callback interval.

---

### 4.2 Kustomisasi Tampilan & Gaya (Styling)
- Seluruh gaya visual terpusat pada file [`assets/style.css`](file:///d:/Project/Project_samsung_dasboard/assets/style.css).
- Untuk mengubah warna tema, cukup ubah token CSS variables pada selector `:root`:
  ```css
  :root {
    --bg: #0B0F14;        /* Latar belakang halaman */
    --surface: #121821;   /* Latar kartu panel */
    --accent: #38BDF8;    /* Garis data dan tombol primer */
    --normal: #22C55E;    /* Indikator status Normal */
    --warning: #F59E0B;   /* Indikator status Warning */
    --critical: #EF4444;  /* Indikator status Critical */
    --shutdown: #B91C1C;  /* Indikator status Shutdown */
  }
  ```
- File CSS akan dimuat ulang secara instan oleh Dash saat disimpan.

---

### 4.3 Integrasi Basis Data Permanen (Penyimpanan Jangka Panjang)
Saat ini data disimpan di memori RAM buffer (`collections.deque` berkapasitas 3600 titik atau setara 1 jam). Jika ingin menyimpan riwayat harian atau bulanan:
- Buka [`mqtt_client.py`](file:///d:/Project/Project_samsung_dasboard/mqtt_client.py).
- Pada fungsi `_record_telemetry_unlocked()`, tambahkan penyimpanan ke **SQLite** atau database time-series seperti **InfluxDB / TimescaleDB**:
  ```python
  import sqlite3
  # Simpan ke tabel telemetry
  conn = sqlite3.connect("machine_history.db")
  conn.execute(
      "INSERT INTO telemetry (datetime, vib_rms, temp, state) VALUES (?, ?, ?, ?)",
      (received_dt.isoformat(), record["vib_rms"], record["temp"], record["state"])
  )
  conn.commit()
  ```

---

### 4.4 Deployment ke Lingkungan Produksi / Cloud Server (VPS)
Untuk menjalankan aplikasi secara terus-menerus di server Linux (Ubuntu/Debian) atau Docker:
1. Pasang WSGI server **Gunicorn**:
   ```bash
   pip install gunicorn
   ```
2. Jalankan dengan perintah:
   ```bash
   gunicorn app:server --bind 0.0.0.0:8050 --workers 1 --threads 4
   ```
   > **Catatan Penting**: Gunakan `--workers 1` dengan multiple threads (`--threads 4`). Ini memastikan MQTT Client background thread dan buffer memori real-time tetap berada dalam satu proses memori yang sama.
3. Anda dapat menghubungkan Gunicorn di belakang reverse proxy **Nginx** dengan sertifikat SSL (HTTPS).

---

### 4.5 Menambahkan Autentikasi Pengguna (Login Page)
Jika di masa depan dashboard perlu dibatasi aksesnya:
- Gunakan paket `dash-auth`:
  ```bash
  pip install dash-auth
  ```
- Tambahkan beberapa baris di `app.py`:
  ```python
  import dash_auth
  VALID_USERNAME_PASSWORD_PAIRS = {
      'operator': 'mesin123',
      'supervisor': 'admin123'
  }
  auth = dash_auth.BasicAuth(app, VALID_USERNAME_PASSWORD_PAIRS)
  ```

