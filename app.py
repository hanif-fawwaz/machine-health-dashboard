"""
app.py — Entry Point Aplikasi Dashboard Machine Health Monitor.
Menggabungkan Dash layout, callbacks, auto-refresh 1 Hz, dan panel kontrol real-time.
"""

import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from datetime import datetime
import pandas as pd
from dash import Dash, html, dcc, Input, Output, State, ctx, no_update

from config import (
    TEAM_ID,
    DEFAULT_WARN_VIB,
    DEFAULT_CRIT_VIB,
    DEFAULT_WARN_TEMP,
    DEFAULT_CRIT_TEMP,
    COLOR_NORMAL,
    COLOR_STALE,
    STATE_SHUTDOWN,
)
from mqtt_client import (
    start_mqtt_client,
    publish_cmd,
    get_connection_status,
    get_latest_telemetry,
    get_telemetry_df,
    get_events_list,
    get_all_telemetry_for_export,
)
from components import (
    create_gauge_figure,
    create_line_chart,
    create_state_timeline,
    create_state_card_element,
    create_event_table_rows,
)

# Inisialisasi App Dash dengan Google Fonts Inter & JetBrains Mono
app = Dash(
    __name__,
    title="Machine Health Monitor — Tim WIB",
    update_title=None,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
    ],
)
server = app.server

# Memulai background MQTT Client atau Mock Simulator
start_mqtt_client()


# ==============================================================================
# DASHBOARD LAYOUT
# ==============================================================================
app.layout = html.Div(
    className="dashboard-container",
    children=[
        # Interval tick 1 detik (1000 ms)
        dcc.Interval(id="interval-tick", interval=1000, n_intervals=0),
        # Komponen unduhan CSV
        dcc.Download(id="download-telemetry-csv"),

        # Banner Peringatan Broker Putus (default: disembunyikan)
        html.Div(
            id="broker-banner",
            className="connection-banner",
            style={"display": "none"},
            children=[
                html.Span("⚠ KONEKSI BROKER TERPUTUS:"),
                html.Span(" Panel kontrol dinonaktifkan sementara. Grafik tetap menampilkan data memori."),
            ],
        ),

        # 1. HEADER BAR
        html.Div(
            className="header-bar",
            children=[
                html.Div(
                    className="header-title-group",
                    children=[
                        html.H1([
                            "Machine Health Monitor",
                            html.Span(f"TIM {TEAM_ID}", className="team-badge"),
                        ]),
                    ],
                ),
                html.Div(
                    className="header-status-group",
                    children=[
                        # Indikator Broker
                        html.Div(
                            className="status-dot-item",
                            children=[
                                html.Span(id="broker-dot", className="status-dot online"),
                                html.Span(id="broker-status-text", children="Broker: Connected"),
                            ],
                        ),
                        # Indikator Device (LWT retained)
                        html.Div(
                            className="status-dot-item",
                            children=[
                                html.Span(id="device-dot", className="status-dot online"),
                                html.Span(id="device-status-text", children="Device: Online"),
                            ],
                        ),
                        # Umur data terakhir
                        html.Div(
                            id="data-age-label",
                            className="data-age",
                            children="Data: Menunggu...",
                        ),
                        # Dropdown Jendela Waktu
                        dcc.Dropdown(
                            id="dropdown-time-window",
                            options=[
                                {"label": "1 Menit", "value": 1},
                                {"label": "5 Menit", "value": 5},
                                {"label": "15 Menit", "value": 15},
                                {"label": "60 Menit", "value": 60},
                            ],
                            value=5,
                            clearable=False,
                            style={"width": "115px", "color": "#0B0F14", "fontSize": "13px"},
                        ),
                        # Tombol Export CSV (Ghost Button)
                        html.Button(
                            "Export CSV",
                            id="btn-export-csv",
                            className="ctrl-btn",
                            title="Unduh seluruh data telemetry dalam memori",
                        ),
                    ],
                ),
            ],
        ),

        # 2. BARIS ATAS: STATE CARD & 2 GAUGES (Grid 12 Kolom -> 4, 4, 4)
        html.Div(
            className="grid-12",
            children=[
                # State Card
                html.Div(
                    className="col-4",
                    id="state-card-wrapper",
                    children=create_state_card_element("NORMAL", "auto", True, False),
                ),
                # Gauge Getaran
                html.Div(
                    className="col-4 panel-card gauge-panel",
                    children=[
                        html.Div(
                            className="panel-header",
                            children=[html.Span("GETARAN RMS", className="panel-title")],
                        ),
                        html.Div(
                            dcc.Graph(
                                id="gauge-vib",
                                figure=create_gauge_figure(0.0, DEFAULT_WARN_VIB, DEFAULT_CRIT_VIB, "m/s²"),
                                config={"displayModeBar": False},
                            ),
                            className="gauge-chart-container",
                        ),
                    ],
                ),
                # Gauge Suhu
                html.Div(
                    className="col-4 panel-card gauge-panel",
                    children=[
                        html.Div(
                            className="panel-header",
                            children=[html.Span("SUHU MESIN", className="panel-title")],
                        ),
                        html.Div(
                            dcc.Graph(
                                id="gauge-temp",
                                figure=create_gauge_figure(0.0, DEFAULT_WARN_TEMP, DEFAULT_CRIT_TEMP, "°C", is_temp=True),
                                config={"displayModeBar": False},
                            ),
                            className="gauge-chart-container",
                        ),
                    ],
                ),
            ],
        ),

        # 3. GRAFIK GETARAN RMS (12 Kolom, Tinggi 260px)
        html.Div(
            className="panel-card chart-panel",
            children=[
                html.Div(
                    className="panel-header",
                    children=[html.Span("GRAFIK GETARAN RMS REAL-TIME", className="panel-title")],
                ),
                dcc.Graph(
                    id="chart-vib",
                    figure=create_line_chart(pd.DataFrame(), "vib_rms", DEFAULT_WARN_VIB, DEFAULT_CRIT_VIB, "Getaran", "m/s²"),
                    config={"displayModeBar": True},
                    className="plotly-chart",
                ),
            ],
        ),

        # 4. GRAFIK SUHU (12 Kolom, Tinggi 260px)
        html.Div(
            className="panel-card chart-panel",
            children=[
                html.Div(
                    className="panel-header",
                    children=[html.Span("GRAFIK SUHU MESIN REAL-TIME", className="panel-title")],
                ),
                dcc.Graph(
                    id="chart-temp",
                    figure=create_line_chart(pd.DataFrame(), "temp", DEFAULT_WARN_TEMP, DEFAULT_CRIT_TEMP, "Suhu", "°C"),
                    config={"displayModeBar": True},
                    className="plotly-chart",
                ),
            ],
        ),

        # 5. BARIS BAWAH: TIMELINE & EVENT (7 Kolom) vs PANEL KONTROL (5 Kolom)
        html.Div(
            className="grid-12",
            children=[
                # Kiri (7 Kolom): State Timeline lalu Tabel Event
                html.Div(
                    className="col-7",
                    style={"display": "flex", "flexDirection": "column", "gap": "16px"},
                    children=[
                        # State Timeline
                        html.Div(
                            className="panel-card timeline-panel",
                            children=[
                                html.Div(
                                    className="panel-header",
                                    children=[html.Span("STATE TIMELINE", className="panel-title")],
                                ),
                                html.Div(
                                    dcc.Graph(
                                        id="chart-timeline",
                                        figure=create_state_timeline(pd.DataFrame()),
                                        config={"displayModeBar": False},
                                    ),
                                    className="timeline-chart-container",
                                ),
                            ],
                        ),
                        # Tabel Event
                        html.Div(
                            className="panel-card",
                            children=[
                                html.Div(
                                    className="panel-header",
                                    children=[html.Span("RIWAYAT PERUBAHAN STATE (20 TERAKHIR)", className="panel-title")],
                                ),
                                html.Div(
                                    className="event-table-container",
                                    children=[
                                        html.Table(
                                            className="event-table",
                                            children=[
                                                html.Thead(
                                                    html.Tr([
                                                        html.Th("WAKTU (WIB)"),
                                                        html.Th("TRANSISI STATE"),
                                                        html.Th("ALASAN (REASON)"),
                                                    ])
                                                ),
                                                html.Tbody(id="event-table-body", children=create_event_table_rows([])),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),

                # Kanan (5 Kolom): Panel Kontrol
                html.Div(
                    className="col-5 panel-card control-section",
                    children=[
                        html.Div(
                            className="panel-header",
                            children=[html.Span("PANEL KONTROL MESIN", className="panel-title")],
                        ),

                        # Sub 1: Mode & Relay
                        html.Div(
                            className="control-group",
                            children=[
                                html.Span("1. MODE & RELAY", className="control-subheading"),
                                html.Div(
                                    className="btn-row",
                                    children=[
                                        html.Button("AUTO", id="btn-mode-auto", className="ctrl-btn ctrl-btn-primary"),
                                        html.Button("MANUAL", id="btn-mode-manual", className="ctrl-btn"),
                                        html.Button(
                                            "TOGGLE RELAY",
                                            id="btn-toggle-relay",
                                            className="ctrl-btn",
                                            disabled=True,
                                            title="Aktif hanya di mode manual",
                                        ),
                                    ],
                                ),
                            ],
                        ),

                        # Sub 2: Thresholds (Client-side validation)
                        html.Div(
                            className="control-group",
                            children=[
                                html.Span("2. THRESHOLD BATAS", className="control-subheading"),
                                html.Div(
                                    className="ctrl-input-grid",
                                    children=[
                                        html.Div(
                                            className="ctrl-input-box",
                                            children=[
                                                html.Label("Warn Vib (m/s²)"),
                                                dcc.Input(
                                                    id="input-warn-vib",
                                                    type="number",
                                                    step=0.1,
                                                    value=DEFAULT_WARN_VIB,
                                                    className="ctrl-input",
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            className="ctrl-input-box",
                                            children=[
                                                html.Label("Crit Vib (m/s²)"),
                                                dcc.Input(
                                                    id="input-crit-vib",
                                                    type="number",
                                                    step=0.1,
                                                    value=DEFAULT_CRIT_VIB,
                                                    className="ctrl-input",
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            className="ctrl-input-box",
                                            children=[
                                                html.Label("Warn Temp (°C)"),
                                                dcc.Input(
                                                    id="input-warn-temp",
                                                    type="number",
                                                    step=1.0,
                                                    value=DEFAULT_WARN_TEMP,
                                                    className="ctrl-input",
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            className="ctrl-input-box",
                                            children=[
                                                html.Label("Crit Temp (°C)"),
                                                dcc.Input(
                                                    id="input-crit-temp",
                                                    type="number",
                                                    step=1.0,
                                                    value=DEFAULT_CRIT_TEMP,
                                                    className="ctrl-input",
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                html.Div(id="threshold-error-msg", className="error-message"),
                                html.Button(
                                    "Apply Thresholds",
                                    id="btn-apply-threshold",
                                    className="ctrl-btn ctrl-btn-primary",
                                    style={"marginTop": "8px"},
                                ),
                            ],
                        ),

                        # Sub 3: Aksi Mesin
                        html.Div(
                            className="control-group",
                            children=[
                                html.Span("3. AKSI MESIN", className="control-subheading"),
                                html.Div(
                                    className="btn-row",
                                    children=[
                                        html.Button(
                                            "RESET SHUTDOWN",
                                            id="btn-reset-shutdown",
                                            className="ctrl-btn ctrl-btn-danger",
                                            disabled=True,
                                            title="Aktif hanya saat mesin dalam state SHUTDOWN",
                                        ),
                                        html.Button(
                                            "Calibrate MPU6050",
                                            id="btn-calibrate",
                                            className="ctrl-btn",
                                        ),
                                    ],
                                ),
                            ],
                        ),

                        # Sub 4: Simulasi Pengujian
                        html.Div(
                            className="control-group",
                            children=[
                                html.Span("4. SIMULASI & DEMO", className="control-subheading"),
                                html.Div(
                                    className="btn-row",
                                    style={"marginBottom": "8px"},
                                    children=[
                                        html.Button("Normal (0.0)", id="preset-normal", className="ctrl-btn"),
                                        html.Button("Warning (1.5)", id="preset-warn", className="ctrl-btn"),
                                        html.Button("Critical (4.0)", id="preset-crit", className="ctrl-btn"),
                                    ],
                                ),
                                html.Div(
                                    className="ctrl-input-box",
                                    children=[
                                        html.Label(id="slider-vib-label", children="Sintetis sim_vib: 0.0 m/s²"),
                                        dcc.Slider(
                                            id="slider-sim-vib",
                                            min=0.0,
                                            max=6.0,
                                            step=0.1,
                                            value=0.0,
                                            marks={0: "0", 1.5: "1.5", 3: "3", 4: "4", 6: "6"},
                                        ),
                                    ],
                                ),
                                html.Div(
                                    style={"display": "flex", "alignItems": "center", "gap": "10px", "marginTop": "8px"},
                                    children=[
                                        dcc.Checklist(
                                            id="check-sim-fault",
                                            options=[{"label": " Simulasi Sensor Rusak (sim_fault)", "value": "fault"}],
                                            value=[],
                                            style={"color": "#E6EAF0", "fontSize": "13px"},
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),

        # Komponen Notifikasi Toast
        html.Div(id="toast-box", className="toast-notice", style={"display": "none"}),
    ],
)


# ==============================================================================
# CALLBACK 1: REAL-TIME TICK (Interval 1000 ms)
# Memperbarui charts, gauges, state card, status koneksi, dan kontrol
# ==============================================================================
@app.callback(
    [
        Output("state-card-wrapper", "children"),
        Output("gauge-vib", "figure"),
        Output("gauge-temp", "figure"),
        Output("chart-vib", "figure"),
        Output("chart-temp", "figure"),
        Output("chart-timeline", "figure"),
        Output("event-table-body", "children"),
        Output("broker-dot", "className"),
        Output("broker-status-text", "children"),
        Output("device-dot", "className"),
        Output("device-status-text", "children"),
        Output("data-age-label", "children"),
        Output("data-age-label", "className"),
        Output("broker-banner", "style"),
        Output("btn-reset-shutdown", "disabled"),
        Output("btn-toggle-relay", "disabled"),
        Output("btn-mode-auto", "className"),
        Output("btn-mode-manual", "className"),
    ],
    [
        Input("interval-tick", "n_intervals"),
        Input("dropdown-time-window", "value"),
    ],
)
def update_dashboard_realtime(n_intervals, time_window):
    broker_conn, device_on, data_age_sec, is_stale = get_connection_status()
    latest = get_latest_telemetry()
    df = get_telemetry_df(window_minutes=time_window if time_window else 5)
    events = get_events_list(limit=20)

    # Status Broker & Device Display
    broker_dot_cls = "status-dot online" if broker_conn else "status-dot offline"
    broker_text = "Broker: Connected" if broker_conn else "Broker: Disconnected"

    device_dot_cls = "status-dot online" if device_on else "status-dot offline"
    device_text = "Device: Online" if device_on else "Device: Offline"

    if data_age_sec is not None:
        data_age_text = f"Data: {data_age_sec:.1f} s lalu"
        if is_stale:
            data_age_text += " (STALE)"
            data_age_cls = "data-age stale"
        else:
            data_age_cls = "data-age"
    else:
        data_age_text = "Data: Menunggu…"
        data_age_cls = "data-age"

    # Banner Broker Putus
    banner_style = {"display": "none"} if broker_conn else {"display": "flex"}

    # Ekstrak data terkini
    if latest:
        state_name = latest.get("state", "NORMAL")
        mode = latest.get("mode", "auto")
        relay_on = bool(latest.get("relay", 1))
        fault_active = bool(latest.get("fault", 0))
        vib_val = latest.get("vib_rms", 0.0)
        temp_val = latest.get("temp", 0.0)
        warn_vib = latest.get("warn_vib", DEFAULT_WARN_VIB)
        crit_vib = latest.get("crit_vib", DEFAULT_CRIT_VIB)
        warn_temp = latest.get("warn_temp", DEFAULT_WARN_TEMP)
        crit_temp = latest.get("crit_temp", DEFAULT_CRIT_TEMP)
    else:
        state_name = "NORMAL"
        mode = "auto"
        relay_on = True
        fault_active = False
        vib_val = 0.0
        temp_val = 0.0
        warn_vib = DEFAULT_WARN_VIB
        crit_vib = DEFAULT_CRIT_VIB
        warn_temp = DEFAULT_WARN_TEMP
        crit_temp = DEFAULT_CRIT_TEMP

    # 1. State Card
    state_card_el = create_state_card_element(
        state_name=state_name,
        mode=mode,
        relay_on=relay_on,
        fault_active=fault_active,
        is_stale=is_stale,
        is_offline=(not device_on),
    )

    # 2. Gauges
    fig_gauge_vib = create_gauge_figure(vib_val, warn_vib, crit_vib, "m/s²", is_temp=False, is_stale=is_stale)
    fig_gauge_temp = create_gauge_figure(temp_val, warn_temp, crit_temp, "°C", is_temp=True, is_stale=is_stale)

    # 3. Line Charts
    fig_chart_vib = create_line_chart(df, "vib_rms", warn_vib, crit_vib, "Getaran RMS", "m/s²")
    fig_chart_temp = create_line_chart(df, "temp", warn_temp, crit_temp, "Suhu Mesin", "°C")

    # 4. State Timeline
    fig_timeline = create_state_timeline(df)

    # 5. Event Table
    event_rows = create_event_table_rows(events)

    # 6. Kontrol Status
    # Reset hanya aktif saat state == SHUTDOWN
    reset_disabled = not (state_name == STATE_SHUTDOWN and broker_conn)
    # Relay toggle hanya aktif saat mode == manual
    relay_disabled = not (mode == "manual" and broker_conn)

    btn_auto_cls = "ctrl-btn ctrl-btn-primary" if mode == "auto" else "ctrl-btn"
    btn_manual_cls = "ctrl-btn ctrl-btn-primary" if mode == "manual" else "ctrl-btn"

    return [
        state_card_el,
        fig_gauge_vib,
        fig_gauge_temp,
        fig_chart_vib,
        fig_chart_temp,
        fig_timeline,
        event_rows,
        broker_dot_cls,
        broker_text,
        device_dot_cls,
        device_text,
        data_age_text,
        data_age_cls,
        banner_style,
        reset_disabled,
        relay_disabled,
        btn_auto_cls,
        btn_manual_cls,
    ]


# ==============================================================================
# CALLBACK 2: CONTROLS & COMMANDS (Threshold, Mode, Relay, Reset, Calibrate, Sim)
# ==============================================================================
@app.callback(
    [
        Output("toast-box", "children"),
        Output("toast-box", "className"),
        Output("toast-box", "style"),
        Output("threshold-error-msg", "children"),
        Output("slider-sim-vib", "value"),
        Output("slider-vib-label", "children"),
    ],
    [
        Input("btn-apply-threshold", "n_clicks"),
        Input("btn-mode-auto", "n_clicks"),
        Input("btn-mode-manual", "n_clicks"),
        Input("btn-toggle-relay", "n_clicks"),
        Input("btn-reset-shutdown", "n_clicks"),
        Input("btn-calibrate", "n_clicks"),
        Input("preset-normal", "n_clicks"),
        Input("preset-warn", "n_clicks"),
        Input("preset-crit", "n_clicks"),
        Input("slider-sim-vib", "value"),
        Input("check-sim-fault", "value"),
    ],
    [
        State("input-warn-vib", "value"),
        State("input-crit-vib", "value"),
        State("input-warn-temp", "value"),
        State("input-crit-temp", "value"),
    ],
    prevent_initial_call=True,
)
def handle_machine_controls(
    n_apply,
    n_auto,
    n_manual,
    n_relay,
    n_reset,
    n_cal,
    p_norm,
    p_warn,
    p_crit,
    slider_val,
    fault_checked,
    warn_vib,
    crit_vib,
    warn_temp,
    crit_temp,
):
    triggered_id = ctx.triggered_id

    # 1. Preset Simulasi
    if triggered_id == "preset-normal":
        publish_cmd({"sim_vib": 0.0, "sim_fault": False})
        return "Preset Normal aktif (sim_vib=0.0)", "toast-notice success", {"display": "flex"}, "", 0.0, "Sintetis sim_vib: 0.0 m/s²"

    if triggered_id == "preset-warn":
        publish_cmd({"sim_vib": 1.5, "sim_fault": False})
        return "Preset Warning aktif (sim_vib=1.5)", "toast-notice success", {"display": "flex"}, "", 1.5, "Sintetis sim_vib: 1.5 m/s²"

    if triggered_id == "preset-crit":
        publish_cmd({"sim_vib": 4.0, "sim_fault": False})
        return "Preset Critical aktif (sim_vib=4.0)", "toast-notice success", {"display": "flex"}, "", 4.0, "Sintetis sim_vib: 4.0 m/s²"

    # 2. Slider sim_vib langsung
    if triggered_id == "slider-sim-vib":
        val = round(float(slider_val), 1)
        publish_cmd({"sim_vib": val})
        label = f"Sintetis sim_vib: {val:.1f} m/s²"
        return f"sim_vib diatur ke {val:.1f}", "toast-notice success", {"display": "flex"}, "", val, label

    # 3. Checkbox sim_fault
    if triggered_id == "check-sim-fault":
        is_fault = ("fault" in fault_checked) if fault_checked else False
        publish_cmd({"sim_fault": is_fault})
        msg = "Simulasi sensor error diaktifkan" if is_fault else "Simulasi sensor dinormalkan"
        return msg, "toast-notice success", {"display": "flex"}, "", no_update, no_update

    # 4. Mode Auto / Manual
    if triggered_id == "btn-mode-auto":
        publish_cmd({"mode": "auto"})
        return "Perintah terkirim: Mode AUTO", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    if triggered_id == "btn-mode-manual":
        publish_cmd({"mode": "manual"})
        return "Perintah terkirim: Mode MANUAL", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    # 5. Toggle Relay
    if triggered_id == "btn-toggle-relay":
        latest = get_latest_telemetry()
        current_relay = latest.get("relay", 1) if latest else 1
        new_relay = 0 if current_relay == 1 else 1
        publish_cmd({"relay": new_relay})
        relay_str = "ON" if new_relay == 1 else "OFF"
        return f"Perintah terkirim: Relay {relay_str}", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    # 6. Reset Shutdown
    if triggered_id == "btn-reset-shutdown":
        publish_cmd({"reset": True})
        return "Perintah RESET dikirim ke perangkat", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    # 7. Kalibrasi
    if triggered_id == "btn-calibrate":
        publish_cmd({"calibrate": True})
        return "Perintah KALIBRASI dikirim ke perangkat", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    # 8. Apply Thresholds (Client-side validation)
    if triggered_id == "btn-apply-threshold":
        try:
            wv = float(warn_vib)
            cv = float(crit_vib)
            wt = float(warn_temp)
            ct = float(crit_temp)
        except (ValueError, TypeError):
            return "Nilai input harus berupa angka yang valid", "toast-notice error", {"display": "flex"}, "Input tidak valid", no_update, no_update

        # Validasi batas getaran
        if wv <= 0:
            err = "Batas getaran warning harus lebih besar dari 0!"
            return err, "toast-notice error", {"display": "flex"}, err, no_update, no_update

        if wv >= cv:
            err = f"Nilai warning ({wv}) harus lebih kecil dari critical ({cv})!"
            return err, "toast-notice error", {"display": "flex"}, err, no_update, no_update

        # Validasi batas suhu
        if wt >= ct:
            err = f"Suhu warning ({wt}) harus lebih kecil dari critical ({ct})!"
            return err, "toast-notice error", {"display": "flex"}, err, no_update, no_update

        # Validasi berhasil -> kirim command ke MQTT
        publish_cmd({
            "set_warn_vib": wv,
            "set_crit_vib": cv,
            "set_warn_temp": wt,
            "set_crit_temp": ct,
        })
        return "Perintah terkirim: Threshold berhasil diperbarui", "toast-notice success", {"display": "flex"}, "", no_update, no_update

    return no_update, no_update, {"display": "none"}, "", no_update, no_update


# ==============================================================================
# CALLBACK 3: EXPORT CSV
# ==============================================================================
@app.callback(
    Output("download-telemetry-csv", "data"),
    Input("btn-export-csv", "n_clicks"),
    prevent_initial_call=True,
)
def export_telemetry_csv(n_clicks):
    records = get_all_telemetry_for_export()
    if not records:
        df_empty = pd.DataFrame(columns=[
            "datetime", "time_str", "vib_rms", "temp", "state", "state_id",
            "relay", "mode", "fault", "warn_vib", "crit_vib", "warn_temp", "crit_temp"
        ])
        return dcc.send_data_frame(df_empty.to_csv, filename="telemetry_empty.csv", index=False)

    df_export = pd.DataFrame(records)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"machine_health_telemetry_{timestamp_str}.csv"
    return dcc.send_data_frame(df_export.to_csv, filename=filename, index=False)


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    print(f"[*] Menjalankan Machine Health Monitor Dashboard...")
    print(f"[*] Buka browser Anda di: http://localhost:8050")
    app.run(debug=False, host="0.0.0.0", port=8050)
