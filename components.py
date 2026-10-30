"""
components.py — Generator komponen visual Dash & Plotly.
Mengimplementasikan spesifikasi design.md:
- Industrial control-room dark theme
- Gauge dengan zona threshold dinamis (35% transparansi)
- Grafik garis dengan uirevision='keep' (tanpa kedip/reset zoom)
- State timeline step chart
- State card dengan strip warna dan pulse animation
- Event table dengan sticky header dan badge warna
"""

from dash import html
import plotly.graph_objects as go
import pandas as pd

from config import (
    COLOR_BG,
    COLOR_SURFACE,
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    COLOR_ACCENT,
    COLOR_NORMAL,
    COLOR_WARNING,
    COLOR_CRITICAL,
    COLOR_SHUTDOWN,
    COLOR_FAULT,
    COLOR_STALE,
    STATE_COLORS,
    STATE_NORMAL,
    STATE_SHUTDOWN,
    STATE_FAULT,
)

# Template default font Plotly
FONT_UI = "Inter, sans-serif"
FONT_MONO = "JetBrains Mono, monospace"


# ==============================================================================
# 1. GAUGE FIGURE (Plotly go.Indicator)
# ==============================================================================
def create_gauge_figure(
    value: float | None,
    warn_thresh: float,
    crit_thresh: float,
    unit: str = "m/s²",
    is_temp: bool = False,
    is_stale: bool = False,
) -> go.Figure:
    """
    Membuat gauge speedometer industri sesuai design.md Bagian 5.3:
    - Steps: hijau (0->warn), kuning (warn->crit), merah (crit->max) opasitas 35%
    - Rentang getaran: 0 -> crit * 1.5; suhu: 0 -> crit * 1.3
    - Bar nilai: --accent
    - Angka mono 32px
    """
    fig = go.Figure()

    if is_temp:
        max_val = max(100.0, round(crit_thresh * 1.3, 1))
        val_fmt = ".1f"
    else:
        max_val = max(5.0, round(crit_thresh * 1.5, 2))
        val_fmt = ".3f"

    display_val = value if value is not None else 0.0
    val_color = COLOR_STALE if is_stale else COLOR_TEXT

    fig.add_trace(
        go.Indicator(
            mode="gauge+number",
            value=display_val,
            number={
                "valueformat": val_fmt,
                "suffix": f" {unit}",
                "font": {"size": 28, "family": FONT_MONO, "color": val_color},
            },
            gauge={
                "axis": {
                    "range": [0, max_val],
                    "tickwidth": 1,
                    "tickcolor": COLOR_BORDER,
                    "tickfont": {"size": 10, "family": FONT_MONO, "color": COLOR_TEXT_DIM},
                },
                "bar": {"color": COLOR_ACCENT, "thickness": 0.22},
                "bgcolor": "rgba(26, 34, 48, 0.4)",
                "borderwidth": 1,
                "bordercolor": COLOR_BORDER,
                "steps": [
                    {
                        "range": [0, warn_thresh],
                        "color": "rgba(34, 197, 94, 0.35)",  # hijau transparan
                    },
                    {
                        "range": [warn_thresh, crit_thresh],
                        "color": "rgba(245, 158, 11, 0.35)", # kuning transparan
                    },
                    {
                        "range": [crit_thresh, max_val],
                        "color": "rgba(239, 68, 68, 0.35)",  # merah transparan
                    },
                ],
                "threshold": {
                    "line": {"color": COLOR_CRITICAL, "width": 3},
                    "thickness": 0.8,
                    "value": crit_thresh,
                },
            },
        )
    )

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=24, r=24, t=10, b=10),
        height=150,
        uirevision="keep",
    )
    return fig


# ==============================================================================
# 2. GRAFIK GARIS REAL-TIME (Plotly Line Chart)
# ==============================================================================
def create_line_chart(
    df: pd.DataFrame,
    y_col: str,
    warn_val: float,
    crit_val: float,
    y_label: str,
    unit: str,
    accent_color: str = COLOR_ACCENT,
) -> go.Figure:
    """
    Membuat grafik garis data vs waktu sesuai design.md Bagian 5.4:
    - Template plotly_dark transparan, grid halus #1F2937
    - Garis threshold putus-putus dengan anotasi di ujung kanan
    - uirevision='keep' agar zoom/pan tidak reset saat refresh 1 Hz
    - Teks placeholder jika dataframe masih kosong
    """
    fig = go.Figure()

    if df.empty or y_col not in df.columns:
        # Placeholder saat data kosong
        fig.add_annotation(
            text="Menunggu data dari perangkat…",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color=COLOR_TEXT_DIM, family=FONT_UI),
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            margin=dict(l=48, r=16, t=12, b=32),
            height=240,
            uirevision="keep",
        )
        return fig

    # 1. Garis data utama
    fig.add_trace(
        go.Scatter(
            x=df["datetime"],
            y=df[y_col],
            mode="lines",
            name=y_label,
            line=dict(color=accent_color, width=2),
            fill="tozeroy",
            fillcolor="rgba(56, 189, 248, 0.08)",
            hovertemplate="%{y:.3f} " + unit + "<extra></extra>",
        )
    )

    # 2. Garis Threshold Warning
    fig.add_hline(
        y=warn_val,
        line=dict(color=COLOR_WARNING, width=1.5, dash="dash"),
        annotation_text=f"WARN ({warn_val:.2f})",
        annotation_position="top right",
        annotation_font=dict(size=10, color=COLOR_WARNING, family=FONT_MONO),
    )

    # 3. Garis Threshold Critical
    fig.add_hline(
        y=crit_val,
        line=dict(color=COLOR_CRITICAL, width=1.5, dash="dash"),
        annotation_text=f"CRIT ({crit_val:.2f})",
        annotation_position="top right",
        annotation_font=dict(size=10, color=COLOR_CRITICAL, family=FONT_MONO),
    )

    # Format layout
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=48, r=16, t=16, b=32),
        height=240,
        hovermode="x unified",
        uirevision="keep",
        xaxis=dict(
            showgrid=True,
            gridcolor="#1F2937",
            gridwidth=1,
            tickfont=dict(size=11, color=COLOR_TEXT_DIM, family=FONT_MONO),
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#1F2937",
            gridwidth=1,
            tickfont=dict(size=11, color=COLOR_TEXT_DIM, family=FONT_MONO),
            zeroline=False,
            title=dict(text=f"{y_label} ({unit})", font=dict(size=11, color=COLOR_TEXT_DIM)),
        ),
        showlegend=False,
    )
    return fig


# ==============================================================================
# 3. STATE TIMELINE (Step Chart)
# ==============================================================================
def create_state_timeline(df: pd.DataFrame) -> go.Figure:
    """
    Membuat step chart state_id vs waktu sesuai design.md Bagian 5.5:
    - line_shape='hv'
    - Sumbu Y berlabel nama state (NORMAL, WARNING, CRITICAL, SHUTDOWN, FAULT)
    - Shaded bands horizontal redup
    """
    fig = go.Figure()

    if df.empty or "state_id" not in df.columns:
        fig.add_annotation(
            text="Menunggu riwayat state…",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=13, color=COLOR_TEXT_DIM, family=FONT_UI),
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            margin=dict(l=75, r=16, t=8, b=30),
            height=180,
            uirevision="keep",
        )
        return fig

    # Horizontal background bands untuk tiap state
    state_band_colors = [
        "rgba(34, 197, 94, 0.06)",   # 0: NORMAL
        "rgba(245, 158, 11, 0.08)",  # 1: WARNING
        "rgba(239, 68, 68, 0.08)",   # 2: CRITICAL
        "rgba(185, 28, 28, 0.12)",   # 3: SHUTDOWN
        "rgba(168, 85, 247, 0.08)",  # 4: FAULT
    ]
    for i in range(5):
        fig.add_hrect(
            y0=i - 0.45,
            y1=i + 0.45,
            fillcolor=state_band_colors[i],
            line_width=0,
            layer="below",
        )

    # Step line chart
    fig.add_trace(
        go.Scatter(
            x=df["datetime"],
            y=df["state_id"],
            mode="lines",
            line=dict(color=COLOR_ACCENT, width=2.5, shape="hv"),
            hovertemplate="State: %{text}<extra></extra>",
            text=df["state"],
        )
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=75, r=16, t=10, b=30),
        height=180,
        hovermode="x unified",
        uirevision="keep",
        xaxis=dict(
            showgrid=True,
            gridcolor="#1F2937",
            gridwidth=1,
            tickfont=dict(size=10, color=COLOR_TEXT_DIM, family=FONT_MONO),
            zeroline=False,
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=[0, 1, 2, 3, 4],
            ticktext=["NORMAL", "WARN", "CRIT", "SHUTDOWN", "FAULT"],
            tickfont=dict(size=10, color=COLOR_TEXT_DIM, family=FONT_MONO),
            range=[-0.5, 4.5],
            showgrid=True,
            gridcolor="#1F2937",
            zeroline=False,
        ),
        showlegend=False,
    )
    return fig


# ==============================================================================
# 4. STATE CARD COMPONENT
# ==============================================================================
def create_state_card_element(
    state_name: str,
    mode: str,
    relay_on: bool,
    fault_active: bool,
    is_stale: bool = False,
    is_offline: bool = False,
) -> html.Div:
    """
    Menghasilkan HTML Div untuk State Card sesuai design.md Bagian 5.2:
    - Strip kiri 6px berwarna state
    - Teks nama state besar (44-48px)
    - Chip status AUTO/MANUAL, RELAY ON/OFF, FAULT
    - Animasi pulse lembut untuk SHUTDOWN, blink untuk FAULT
    """
    display_state = "OFFLINE" if is_offline else state_name
    card_css_class = f"panel-card state-card {display_state}"

    # Chip styling
    mode_text = mode.upper() if mode else "AUTO"
    mode_chip_cls = "chip chip-auto" if mode_text == "AUTO" else "chip chip-manual"

    relay_text = "RELAY ON" if relay_on else "RELAY OFF"
    relay_chip_cls = "chip chip-relay-on" if relay_on else "chip chip-relay-off"

    chips = [
        html.Span(mode_text, className=mode_chip_cls),
        html.Span(relay_text, className=relay_chip_cls),
    ]

    if fault_active:
        chips.append(html.Span("FAULT ACTIVE", className="chip chip-fault-active"))

    return html.Div(
        className=card_css_class,
        children=[
            html.Div(
                className="panel-header",
                children=[
                    html.Span("STATUS MESIN", className="panel-title"),
                    html.Span(
                        "DATA STALE" if is_stale and not is_offline else ("OFFLINE" if is_offline else "LIVE"),
                        className="chip",
                        style={"color": COLOR_STALE if is_stale or is_offline else COLOR_NORMAL},
                    ),
                ],
            ),
            html.Div(
                display_state,
                className=f"state-title-text {display_state}",
            ),
            html.Div(className="state-chip-row", children=chips),
        ],
    )


# ==============================================================================
# 5. EVENT TABLE ROWS COMPONENT
# ==============================================================================
def create_event_table_rows(events: list) -> list:
    """
    Menghasilkan baris tabel HTML (tr) untuk 20 event terakhir sesuai design.md Bagian 5.6:
    - Waktu (HH:MM:SS), Dari -> Ke (chip badge berwarna), Alasan
    - Baris reset_denied ditandai dengan garis kiri kuning dan icon ⚠
    """
    if not events:
        return [
            html.Tr([
                html.Td(
                    "Belum ada catatan event perubahan state.",
                    colSpan=3,
                    style={"textAlign": "center", "color": COLOR_TEXT_DIM, "padding": "16px"},
                )
            ])
        ]

    rows = []
    for ev in events:
        from_st = ev.get("from", "NORMAL")
        to_st = ev.get("to", "NORMAL")
        reason = ev.get("reason", "")
        time_str = ev.get("time_str", "")

        is_denied = (reason == "reset_denied")
        row_cls = "event-denied" if is_denied else ""

        reason_display = f"⚠ {reason}" if is_denied else reason

        tr = html.Tr(
            className=row_cls,
            children=[
                html.Td(time_str),
                html.Td([
                    html.Span(from_st, className=f"event-badge badge-{from_st}"),
                    html.Span(" → ", style={"color": COLOR_TEXT_DIM, "margin": "0 4px"}),
                    html.Span(to_st, className=f"event-badge badge-{to_st}"),
                ]),
                html.Td(
                    reason_display,
                    style={"color": COLOR_WARNING if is_denied else COLOR_TEXT},
                ),
            ],
        )
        rows.append(tr)

    return rows

