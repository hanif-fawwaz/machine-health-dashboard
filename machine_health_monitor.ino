#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>

// ===================== KONFIGURASI =====================
#define ENABLE_MQTT 1            // 0 = hanya Serial, 1 = Serial + MQTT

#if ENABLE_MQTT
  #include <WiFi.h>
  #include <WiFiClientSecure.h>
  #include <PubSubClient.h>
#endif

#ifndef ESP_ARDUINO_VERSION_MAJOR
  #define ESP_ARDUINO_VERSION_MAJOR 2
#endif

// WiFi (Wokwi memakai SSID ini)
const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";

// HiveMQ Cloud -> ISI DENGAN MILIK ANDA (jangan dibagikan / di-commit ke GitHub)
const char*    MQTT_HOST = "ISI_HOST_HIVEMQ.s1.eu.hivemq.cloud";
const uint16_t MQTT_PORT = 8883;
const char*    MQTT_USER = "ISI_USERNAME";
const char*    MQTT_PASS = "ISI_PASSWORD";

// Topic
#define TEAM_ID         "WIB"
#define TOPIC_BASE      "sic8/" TEAM_ID
#define TOPIC_TELEMETRY TOPIC_BASE "/telemetry"
#define TOPIC_EVENT     TOPIC_BASE "/event"
#define TOPIC_STATUS    TOPIC_BASE "/status"
#define TOPIC_CMD       TOPIC_BASE "/cmd"

// Pin
#define PIN_SDA        21
#define PIN_SCL        22
#define PIN_NTC        34   // ADC1, input-only
#define PIN_LED_GREEN  27
#define PIN_LED_YELLOW 32
#define PIN_LED_RED    33
#define PIN_BUZZER     25
#define PIN_RELAY      26
#define PIN_BTN_RESET  4
#define PIN_BTN_MODE   16

const bool RELAY_ACTIVE_HIGH = true;   // ubah ke false jika relay Wokwi terbalik

// Sampling dan analisis
const unsigned long SAMPLE_MS     = 10;     // sampling MPU6050 tiap 10 ms
const int           WINDOW_SIZE   = 50;     // 50 sampel = 1 jendela RMS (500 ms)
const unsigned long TEMP_MS       = 500;
const unsigned long TELEMETRY_MS  = 1000;
const unsigned long DISPLAY_MS    = 250;
const float         NTC_BETA      = 3950.0;

// Threshold (bisa diubah lewat perintah cmd)
struct Config {
  float warnVib  = 1.0f;    // m/s^2 (RMS)
  float critVib  = 3.0f;
  float warnTemp = 50.0f;   // derajat C
  float critTemp = 70.0f;
  float hystVib  = 0.2f;    // hysteresis
  float hystTemp = 3.0f;
} cfg;

unsigned long critHoldMs = 5000;   // CRITICAL bertahan sekian ms -> SHUTDOWN

// ===================== STATE =====================
enum State { ST_NORMAL, ST_WARNING, ST_CRITICAL, ST_SHUTDOWN, ST_FAULT };
const char* STATE_NAME[] = {"NORMAL", "WARNING", "CRITICAL", "SHUTDOWN", "FAULT"};

State state = ST_NORMAL;
unsigned long critSince = 0;

float vibRms = 0, tempC = 0, baseline = 9.8f, simVib = 0;
int   vibLevel = 0, tempLevel = 0;
bool  mpuOk = false, tempOk = false, simFault = false;
bool  manualMode = false, manualRelay = true, relayOn = true;
bool  resetRequested = false, oledOk = false;

// buffer analisis
float sumSq = 0; int sampleCount = 0;
float rmsHist[4] = {0, 0, 0, 0}; int rmsIdx = 0, rmsCount = 0;
int   mpuFail = 0;
unsigned long lastSample = 0, lastTemp = 0, lastTele = 0, lastDisp = 0, lastMpuRetry = 0;
uint32_t lastFreq = 0;

Adafruit_MPU6050 mpu;
Adafruit_SSD1306 display(128, 64, &Wire, -1);

#if ENABLE_MQTT
WiFiClientSecure netClient;
PubSubClient mqtt(netClient);
unsigned long lastMqttTry = 0;
char clientId[40];                 // client ID unik tiap boot (hindari bentrok di broker)
#endif

// ===================== UTIL =====================
float accelMag(const sensors_event_t &a) {
  return sqrtf(a.acceleration.x * a.acceleration.x +
               a.acceleration.y * a.acceleration.y +
               a.acceleration.z * a.acceleration.z);
}

// Level 0/1/2 dengan hysteresis (level turun hanya jika nilai < batas - hyst)
int levelWithHyst(float v, float warn, float crit, float hyst, int prev) {
  if (v >= crit || (prev == 2 && v >= crit - hyst)) return 2;
  if (v >= warn || (prev >= 1 && v >= warn - hyst)) return 1;
  return 0;
}

// ===================== OUTPUT HARDWARE =====================
void setRelay(bool on) {
  relayOn = on;
  digitalWrite(PIN_RELAY, (on == RELAY_ACTIVE_HIGH) ? HIGH : LOW);
}

void setLeds(bool g, bool y, bool r) {
  digitalWrite(PIN_LED_GREEN, g);
  digitalWrite(PIN_LED_YELLOW, y);
  digitalWrite(PIN_LED_RED, r);
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void buzzerInit()          { ledcAttach(PIN_BUZZER, 2000, 8); ledcWriteTone(PIN_BUZZER, 0); }
void buzzerTone(uint32_t f) { ledcWriteTone(PIN_BUZZER, f); }
#else
void buzzerInit()          { ledcSetup(0, 2000, 8); ledcAttachPin(PIN_BUZZER, 0); ledcWriteTone(0, 0); }
void buzzerTone(uint32_t f) { ledcWriteTone(0, f); }
#endif

void applyOutputs(unsigned long now) {
  // Relay: AUTO -> mati saat SHUTDOWN; MANUAL -> sesuai perintah
  setRelay(manualMode ? manualRelay : (state != ST_SHUTDOWN));

  // LED
  switch (state) {
    case ST_NORMAL:   setLeds(1, 0, 0); break;
    case ST_WARNING:  setLeds(0, 1, 0); break;
    case ST_CRITICAL: setLeds(0, 0, 1); break;
    case ST_SHUTDOWN: setLeds(0, 0, (now % 500) < 250); break;
    case ST_FAULT:    { bool b = (now % 1000) < 500; setLeds(b, b, b); } break;
  }

  // Buzzer (pola berbeda tiap state)
  uint32_t f = 0;
  switch (state) {
    case ST_WARNING:  f = (now % 1000) < 150 ? 1500 : 0; break;
    case ST_CRITICAL: f = 2500; break;
    case ST_SHUTDOWN: f = (now % 200) < 100 ? 3000 : 0; break;
    case ST_FAULT:    f = (now % 1000) < 500 ? 800 : 0; break;
    default: f = 0;
  }
  if (f != lastFreq) { buzzerTone(f); lastFreq = f; }
}

// ===================== PUBLISH / EVENT =====================
void publishMqtt(const char* topic, const char* payload, bool retained = false) {
#if ENABLE_MQTT
  if (mqtt.connected()) mqtt.publish(topic, payload, retained);
#endif
}

// Event: dikirim saat state berubah. state_id ikut dikirim agar mudah diplot.
void emitEvent(const char* from, const char* to, const char* reason) {
  char buf[200];
  snprintf(buf, sizeof(buf),
           "{\"type\":\"event\",\"ts\":%lu,\"from\":\"%s\",\"to\":\"%s\",\"to_id\":%d,\"reason\":\"%s\"}",
           millis(), from, to, (int)state, reason);
  Serial.println(buf);
  publishMqtt(TOPIC_EVENT, buf);
}

// Telemetry: JSON datar (semua nilai angka/teks sederhana) -> langsung jadi 1 baris DataFrame.
void publishTelemetry(unsigned long now) {
  if (now - lastTele < TELEMETRY_MS) return;
  lastTele = now;
  bool fault = !mpuOk || !tempOk || simFault;
  char buf[512];
  snprintf(buf, sizeof(buf),
    "{\"type\":\"telemetry\",\"ts\":%lu,\"vib_rms\":%.3f,\"temp\":%.1f,"
    "\"state\":\"%s\",\"state_id\":%d,\"vib_level\":%d,\"temp_level\":%d,"
    "\"relay\":%d,\"mode\":\"%s\",\"fault\":%d,"
    "\"warn_vib\":%.2f,\"crit_vib\":%.2f,\"warn_temp\":%.1f,\"crit_temp\":%.1f}",
    now, vibRms, tempC, STATE_NAME[state], (int)state, vibLevel, tempLevel,
    relayOn ? 1 : 0, manualMode ? "manual" : "auto", fault ? 1 : 0,
    cfg.warnVib, cfg.critVib, cfg.warnTemp, cfg.critTemp);
  Serial.println(buf);
  publishMqtt(TOPIC_TELEMETRY, buf);
}

// ===================== SENSOR =====================
void i2cScan() {
  Serial.println("# I2C scan:");
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) Serial.printf("#   ditemukan 0x%02X\n", addr);
  }
}

void calibrateBaseline() {
  float sum = 0; int n = 0;
  for (int i = 0; i < 100; i++) {
    sensors_event_t a, g, t;
    if (mpu.getEvent(&a, &g, &t)) { sum += accelMag(a); n++; }
    delay(5);
  }
  if (n > 0) { baseline = sum / n; Serial.printf("# baseline = %.3f m/s2\n", baseline); }
}

void sampleVibration(unsigned long now) {
  if (now - lastSample < SAMPLE_MS) return;
  lastSample = now;

  if (!mpuOk) {  // coba init ulang tiap 3 detik
    if (now - lastMpuRetry >= 3000) {
      lastMpuRetry = now;
      if (mpu.begin(0x68)) { mpuOk = true; mpuFail = 0; Serial.println("# MPU6050 pulih"); }
    }
    return;
  }

  sensors_event_t a, g, t;
  bool ok = mpu.getEvent(&a, &g, &t);
  float m = ok ? accelMag(a) : NAN;
  if (!ok || isnan(m)) {
    if (++mpuFail >= 5) { mpuOk = false; Serial.println("# MPU6050 gagal dibaca"); }
    return;
  }
  mpuFail = 0;

  float dev = m - baseline;                       // komponen getaran
  if (simVib > 0) dev += simVib * 1.732f * (random(-1000, 1001) / 1000.0f);  // noise sintetis (RMS = simVib)
  sumSq += dev * dev;
  sampleCount++;

  if (sampleCount >= WINDOW_SIZE) {
    float rms = sqrtf(sumSq / sampleCount);
    sumSq = 0; sampleCount = 0;
    rmsHist[rmsIdx] = rms; rmsIdx = (rmsIdx + 1) % 4; if (rmsCount < 4) rmsCount++;
    float s = 0; for (int i = 0; i < rmsCount; i++) s += rmsHist[i];
    vibRms = s / rmsCount;                         // moving average 4 jendela
    vibLevel = levelWithHyst(vibRms, cfg.warnVib, cfg.critVib, cfg.hystVib, vibLevel);
  }
}

void readTemperature(unsigned long now) {
  if (now - lastTemp < TEMP_MS) return;
  lastTemp = now;
  long acc = 0;
  for (int i = 0; i < 8; i++) acc += analogRead(PIN_NTC);
  int raw = acc / 8;
  if (raw <= 10 || raw >= 4085) { tempOk = false; return; }   // lepas / short
  float c = 1.0 / (log(1.0 / (4095.0 / raw - 1.0)) / NTC_BETA + 1.0 / 298.15) - 273.15;
  if (isnan(c) || c < -40 || c > 150) { tempOk = false; return; }
  tempOk = true;
  tempC = c;
  tempLevel = levelWithHyst(tempC, cfg.warnTemp, cfg.critTemp, cfg.hystTemp, tempLevel);
}

// ===================== PERINTAH (Serial / MQTT) =====================
void handleCommand(const char* payload, size_t len) {
  JsonDocument doc;
  DeserializationError err = deserializeJson(doc, payload, len);
  if (err) { Serial.printf("# cmd error: %s\n", err.c_str()); return; }

  // Threshold
  float wv = cfg.warnVib, cv = cfg.critVib, wt = cfg.warnTemp, ct = cfg.critTemp;
  bool changed = false;
  if (!doc["set_warn_vib"].isNull())  { wv = doc["set_warn_vib"].as<float>();  changed = true; }
  if (!doc["set_crit_vib"].isNull())  { cv = doc["set_crit_vib"].as<float>();  changed = true; }
  if (!doc["set_warn_temp"].isNull()) { wt = doc["set_warn_temp"].as<float>(); changed = true; }
  if (!doc["set_crit_temp"].isNull()) { ct = doc["set_crit_temp"].as<float>(); changed = true; }
  if (changed) {
    if (wv > 0 && wv < cv && wt < ct) {
      cfg.warnVib = wv; cfg.critVib = cv; cfg.warnTemp = wt; cfg.critTemp = ct;
      Serial.println("# threshold diperbarui");
    } else {
      Serial.println("# threshold ditolak: warn harus < crit");
    }
  }

  // Mode auto / manual
  const char* m = doc["mode"] | "";
  if (strcmp(m, "manual") == 0 || strcmp(m, "auto") == 0) {
    manualMode = (strcmp(m, "manual") == 0);
    manualRelay = relayOn;
    critSince = millis();
    Serial.printf("# mode = %s\n", m);
  }

  // Relay (hanya mode manual)
  if (!doc["relay"].isNull()) {
    if (manualMode) manualRelay = doc["relay"].as<int>() != 0;
    else Serial.println("# relay diabaikan: mode masih auto");
  }

  if (!doc["sim_vib"].isNull())   simVib = max(0.0f, doc["sim_vib"].as<float>());
  if (!doc["sim_fault"].isNull()) simFault = doc["sim_fault"].as<bool>();
  if (doc["calibrate"] | false)   calibrateBaseline();
  if (doc["reset"] | false)       resetRequested = true;
}

void readSerialCommands() {
  static char sbuf[256];
  static size_t sl = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (sl > 0) { sbuf[sl] = 0; handleCommand(sbuf, sl); sl = 0; }
    } else if (sl < sizeof(sbuf) - 1) {
      sbuf[sl++] = c;
    }
  }
}

// ===================== STATE MACHINE =====================
void setState(State ns, const char* reason) {
  if (ns == state) return;
  State old = state;
  state = ns;                       // state diubah dulu agar to_id di event benar
  emitEvent(STATE_NAME[old], STATE_NAME[ns], reason);
}

const char* causeText() {
  int l = max(vibLevel, tempLevel);
  if (l == 0) return "recovered";
  if (vibLevel == l && tempLevel == l) return "vib+temp";
  return (vibLevel == l) ? "vib" : "temp";
}

void updateState(unsigned long now) {
  bool fault = !mpuOk || !tempOk || simFault;

  // SHUTDOWN bersifat latched: hanya keluar lewat reset saat kondisi aman
  if (state == ST_SHUTDOWN) {
    if (resetRequested) {
      resetRequested = false;
      if (!fault && max(vibLevel, tempLevel) == 0) setState(ST_NORMAL, "reset");
      else emitEvent(STATE_NAME[state], STATE_NAME[state], "reset_denied");
    }
    return;
  }
  resetRequested = false;

  if (fault) { setState(ST_FAULT, "sensor"); return; }

  int lvl = max(vibLevel, tempLevel);
  if (lvl == 0) {
    setState(ST_NORMAL, "recovered");
  } else if (lvl == 1) {
    setState(ST_WARNING, causeText());
  } else {
    if (state != ST_CRITICAL) { setState(ST_CRITICAL, causeText()); critSince = now; }
    else if (!manualMode && now - critSince >= critHoldMs) setState(ST_SHUTDOWN, "crit_timeout");
  }
}

// ===================== TOMBOL =====================
bool buttonPressed(uint8_t pin, bool &last, unsigned long &tChange, unsigned long now) {
  bool cur = (digitalRead(pin) == LOW);
  if (cur != last && now - tChange > 50) { tChange = now; last = cur; return cur; }
  return false;
}

void readButtons(unsigned long now) {
  static bool lastReset = false, lastMode = false;
  static unsigned long tReset = 0, tMode = 0;
  if (buttonPressed(PIN_BTN_RESET, lastReset, tReset, now)) resetRequested = true;
  if (buttonPressed(PIN_BTN_MODE, lastMode, tMode, now)) {
    manualMode = !manualMode;
    manualRelay = relayOn;
    critSince = now;
    Serial.printf("# mode = %s\n", manualMode ? "manual" : "auto");
  }
}

// ===================== OLED =====================
void updateDisplay(unsigned long now) {
  if (!oledOk || now - lastDisp < DISPLAY_MS) return;
  lastDisp = now;
  char line[32];
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);
  display.setCursor(0, 0);
  display.print("MACHINE HEALTH ");
  display.print(manualMode ? "[MAN]" : "[AUTO]");

  display.setTextSize(2);
  display.setCursor(0, 11);
  display.print(STATE_NAME[state]);

  display.setTextSize(1);
  snprintf(line, sizeof(line), "Vib : %.2f m/s2", vibRms);
  display.setCursor(0, 32); display.print(line);
  if (tempOk) snprintf(line, sizeof(line), "Temp: %.1f C", tempC);
  else        snprintf(line, sizeof(line), "Temp: ERROR");
  display.setCursor(0, 42); display.print(line);

#if ENABLE_MQTT
  const char* net = mqtt.connected() ? "MQTT OK" : (WiFi.status() == WL_CONNECTED ? "WiFi OK" : "No WiFi");
#else
  const char* net = "Serial";
#endif
  snprintf(line, sizeof(line), "Relay:%s  %s", relayOn ? "ON" : "OFF", net);
  display.setCursor(0, 54); display.print(line);
  display.display();
}

// ===================== NETWORK =====================
#if ENABLE_MQTT
void onMqtt(char* topic, byte* payload, unsigned int length) {
  handleCommand((const char*)payload, length);
}

void connectMqtt() {
  // Bersihkan socket TLS lama supaya tidak ada sisa koneksi setengah mati
  netClient.stop();
  Serial.printf("# MQTT connect, clientId=%s\n", clientId);
  if (mqtt.connect(clientId, MQTT_USER, MQTT_PASS, TOPIC_STATUS, 1, true, "offline")) {
    mqtt.publish(TOPIC_STATUS, "online", true);
    mqtt.subscribe(TOPIC_CMD);
    Serial.println("# MQTT terhubung");
  } else {
    Serial.printf("# MQTT gagal, rc=%d\n", mqtt.state());
  }
}

void networkLoop(unsigned long now) {
  static bool wasConnected = false;

  if (WiFi.status() != WL_CONNECTED) {
    wasConnected = false;
    return;
  }

  bool nowConnected = mqtt.connected();
  if (wasConnected && !nowConnected)
    Serial.printf("# MQTT putus, rc=%d\n", mqtt.state());
  wasConnected = nowConnected;

  if (!nowConnected) {
    if (now - lastMqttTry >= 5000) { lastMqttTry = now; connectMqtt(); }
  } else {
    mqtt.loop();
  }
}
#endif

// ===================== SETUP & LOOP =====================
void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_LED_YELLOW, OUTPUT);
  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BTN_RESET, INPUT_PULLUP);
  pinMode(PIN_BTN_MODE, INPUT_PULLUP);
  setRelay(true);
  buzzerInit();
  analogReadResolution(12);

  Wire.begin(PIN_SDA, PIN_SCL);
  i2cScan();

  oledOk = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  if (oledOk) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.println("Machine Health");
    display.println("Monitor - booting");
    display.display();
  } else {
    Serial.println("# OLED tidak ditemukan");
  }

  mpuOk = mpu.begin(0x68);
  if (mpuOk) {
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setFilterBandwidth(MPU6050_BAND_260_HZ);
    calibrateBaseline();
  } else {
    Serial.println("# MPU6050 tidak ditemukan");
  }

#if ENABLE_MQTT
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  netClient.setInsecure();               // cukup untuk simulasi; untuk produksi pakai sertifikat CA

  // Client ID unik tiap boot. MAC ESP32 di Wokwi selalu sama, sehingga ID berbasis MAC
  // bentrok antar simulasi dan broker saling menendang koneksi (online/offline berulang).
  snprintf(clientId, sizeof(clientId), "mh-%s-%08lX", TEAM_ID, (unsigned long)esp_random());

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMqtt);
  mqtt.setBufferSize(640);
  mqtt.setKeepAlive(30);                 // detik; lebih longgar untuk jaringan simulasi
  mqtt.setSocketTimeout(10);             // detik
#endif

  Serial.println("# siap. Kirim perintah JSON lewat Serial Monitor, mis: {\"sim_vib\":1.5}");
}

void loop() {
  unsigned long now = millis();
  readButtons(now);
  readSerialCommands();
  sampleVibration(now);
  readTemperature(now);
  updateState(now);
  applyOutputs(now);
  updateDisplay(now);
#if ENABLE_MQTT
  networkLoop(now);
#endif
  publishTelemetry(now);
}