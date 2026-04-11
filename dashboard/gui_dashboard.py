"""
Профессиональный GUI-дашборд на tkinter — Интеллектуальная система QoP.

Единый интерфейс для всех режимов работы:
  - Demo (симулятор, без Asterisk)
  - Live (подключение к реальному Asterisk через AMI)

Панели:
  - Заголовок с логотипом и индикатором статуса
  - Карточки активных вызовов с метриками и QoP-индикаторами
  - Графики метрик в реальном времени (latency, jitter, loss)
  - Панель алертов с цветовой индикацией severity
  - Панель управления: выбор режима, сценарии аномалий, настройки AMI
"""

import tkinter as tk
from tkinter import ttk
import threading
import asyncio
import time
import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Цветовая палитра (тёмная тема) ─────────────────────────────────────────

COLORS = {
    "bg_dark": "#0f1923",
    "bg_panel": "#1a2733",
    "bg_card": "#233040",
    "bg_card_hover": "#2a3a4d",
    "bg_input": "#2a3a4d",
    "border": "#2e4057",
    "border_accent": "#3d5a80",

    "text_primary": "#e0e6ed",
    "text_secondary": "#8899aa",
    "text_dim": "#556677",
    "text_white": "#ffffff",

    "accent_blue": "#4fc3f7",
    "accent_cyan": "#00e5ff",

    "qop_low": "#4caf50",
    "qop_low_bg": "#1b3a1e",
    "qop_medium": "#ff9800",
    "qop_medium_bg": "#3a2e10",
    "qop_high": "#f44336",
    "qop_high_bg": "#3a1515",

    "alert_info": "#4fc3f7",
    "alert_warning": "#ff9800",
    "alert_critical": "#f44336",

    "chart_latency": "#4fc3f7",
    "chart_jitter": "#ff9800",
    "chart_loss": "#f44336",

    "btn_primary": "#1976d2",
    "btn_primary_hover": "#2196f3",
    "btn_danger": "#c62828",
    "btn_danger_hover": "#e53935",
    "btn_success": "#2e7d32",
    "btn_success_hover": "#43a047",
    "btn_neutral": "#37474f",
    "btn_neutral_hover": "#455a64",
}

QOP_CONFIG = {
    "low": {
        "label": "LOW",
        "subtitle": "Standard SIP + RTP",
        "color": COLORS["qop_low"],
        "bg": COLORS["qop_low_bg"],
    },
    "medium": {
        "label": "MEDIUM",
        "subtitle": "SIP TLS Only",
        "color": COLORS["qop_medium"],
        "bg": COLORS["qop_medium_bg"],
    },
    "high": {
        "label": "HIGH",
        "subtitle": "SIP TLS + SRTP",
        "color": COLORS["qop_high"],
        "bg": COLORS["qop_high_bg"],
    },
}


# ─── Вспомогательные виджеты ─────────────────────────────────────────────────

class MetricChart(tk.Canvas):
    """Мини-график временного ряда метрики."""

    def __init__(self, parent, color: str, max_points: int = 40,
                 height: int = 50, **kwargs):
        super().__init__(parent, bg=COLORS["bg_card"], highlightthickness=0,
                         height=height, **kwargs)
        self.color = color
        self.max_points = max_points
        self.data: deque = deque(maxlen=max_points)
        self._height = height

    def add_point(self, value: float):
        self.data.append(value)
        self._redraw()

    def _redraw(self):
        self.delete("all")
        if len(self.data) < 2:
            return

        w = self.winfo_width()
        h = self._height
        pad = 4

        max_val = max(self.data) * 1.2 if max(self.data) > 0 else 1

        points = []
        for i, val in enumerate(self.data):
            x = pad + (w - 2 * pad) * i / (self.max_points - 1)
            y = h - pad - (h - 2 * pad) * val / max_val
            points.append((x, y))

        # Заливка под линией
        fill_pts = list(points) + [(points[-1][0], h), (points[0][0], h)]
        flat = [c for p in fill_pts for c in p]
        self.create_polygon(flat, fill=self.color, outline="", stipple="gray25")

        # Линия
        flat_line = [c for p in points for c in p]
        if len(flat_line) >= 4:
            self.create_line(flat_line, fill=self.color, width=2, smooth=True)

        # Точка на конце
        lx, ly = points[-1]
        self.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                         fill=self.color, outline=COLORS["text_white"], width=1)


class StyledButton(tk.Canvas):
    """Кнопка с hover-эффектом."""

    def __init__(self, parent, text: str, color: str, hover_color: str,
                 command=None, width=140, height=36, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg=parent["bg"], highlightthickness=0, **kwargs)
        self._text = text
        self._color = color
        self._hover_color = hover_color
        self._current_color = color
        self._command = command
        self._btn_width = width
        self._btn_height = height

        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._command() if self._command else None)
        self._draw()

    def _set_hover(self, on: bool):
        self._current_color = self._hover_color if on else self._color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h, r = self._btn_width, self._btn_height, 8
        c = self._current_color
        # Rounded rectangle via arcs + rects
        self.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=c, outline=c)
        self.create_arc(w-2*r, 0, w, 2*r, start=0, extent=90, fill=c, outline=c)
        self.create_arc(0, h-2*r, 2*r, h, start=180, extent=90, fill=c, outline=c)
        self.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=c, outline=c)
        self.create_rectangle(r, 0, w-r, h, fill=c, outline=c)
        self.create_rectangle(0, r, w, h-r, fill=c, outline=c)
        self.create_text(w//2, h//2, text=self._text,
                         fill=COLORS["text_white"], font=("Helvetica", 11, "bold"))


# ─── Главный дашборд ─────────────────────────────────────────────────────────

class QoPDashboard:
    """
    Единый GUI-дашборд системы рекомендаций QoP.

    Поддерживает режимы: Demo (симулятор) и Live (Asterisk AMI).
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("QoP Intelligent Recommendation System")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.geometry("1300x850")
        self.root.minsize(1100, 700)

        # Шрифты
        self.fonts = {
            "title": ("Helvetica", 20, "bold"),
            "heading": ("Helvetica", 14, "bold"),
            "body": ("Helvetica", 11),
            "body_bold": ("Helvetica", 11, "bold"),
            "small": ("Helvetica", 10),
            "mono_small": ("Courier", 10),
            "metric_big": ("Helvetica", 22, "bold"),
            "metric_label": ("Helvetica", 9),
            "qop_level": ("Helvetica", 16, "bold"),
            "qop_sub": ("Helvetica", 9),
        }

        # State
        self._call_cards: dict[str, dict] = {}
        self._alerts_widgets: list[tk.Frame] = []
        self._status_var = tk.StringVar(value="Готов к запуску")
        self._running = False
        self._simulator = None
        self._predictor = None
        self._rec_engine = None
        self._channels: dict[str, str] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # AMI settings variables
        self._ami_host = tk.StringVar(value="127.0.0.1")
        self._ami_port = tk.StringVar(value="5038")
        self._ami_user = tk.StringVar(value="monitor")
        self._ami_pass = tk.StringVar(value="monitor_secret")

        self._build_ui()

    # ─── UI Layout ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        content = tk.Frame(self.root, bg=COLORS["bg_dark"])
        content.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Left: call cards
        left = tk.Frame(content, bg=COLORS["bg_dark"])
        left.pack(side="left", fill="both", expand=True)

        self._calls_container = tk.Frame(left, bg=COLORS["bg_dark"])
        self._calls_container.pack(fill="both", expand=True)

        # Right: alerts + controls
        right = tk.Frame(content, bg=COLORS["bg_dark"], width=400)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        self._build_alerts_panel(right)
        self._build_controls_panel(right)

    def _build_header(self):
        header = tk.Frame(self.root, bg=COLORS["bg_panel"], height=70)
        header.pack(fill="x")
        header.pack_propagate(False)

        inner = tk.Frame(header, bg=COLORS["bg_panel"])
        inner.pack(fill="both", expand=True, padx=20)

        # Left — title
        left = tk.Frame(inner, bg=COLORS["bg_panel"])
        left.pack(side="left", fill="y")

        tk.Label(left, text="\u26a1", font=("Helvetica", 28),
                 bg=COLORS["bg_panel"], fg=COLORS["accent_cyan"]
                 ).pack(side="left", padx=(0, 12))

        tf = tk.Frame(left, bg=COLORS["bg_panel"])
        tf.pack(side="left")
        tk.Label(tf, text="QoP Recommendation System",
                 font=self.fonts["title"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_white"]).pack(anchor="w")
        tk.Label(tf, text="Intelligent VoIP Security Advisor  \u2022  Asterisk PBX",
                 font=self.fonts["small"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_secondary"]).pack(anchor="w")

        # Right — status
        right = tk.Frame(inner, bg=COLORS["bg_panel"])
        right.pack(side="right", fill="y")

        self._status_dot = tk.Canvas(right, width=12, height=12,
                                     bg=COLORS["bg_panel"], highlightthickness=0)
        self._status_dot.pack(side="left", padx=(0, 8), pady=20)
        self._status_dot.create_oval(2, 2, 10, 10, fill=COLORS["text_dim"],
                                     outline=COLORS["text_dim"], tags="dot")

        tk.Label(right, textvariable=self._status_var, font=self.fonts["small"],
                 bg=COLORS["bg_panel"], fg=COLORS["text_secondary"]
                 ).pack(side="left", pady=20)

        tk.Frame(self.root, bg=COLORS["border"], height=1).pack(fill="x")

    def _build_alerts_panel(self, parent):
        hdr = tk.Frame(parent, bg=COLORS["bg_dark"])
        hdr.pack(fill="x", pady=(0, 8))

        tk.Label(hdr, text="\U0001f514  \u0410\u043b\u0435\u0440\u0442\u044b",
                 font=self.fonts["heading"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self._alert_count = tk.Label(hdr, text="0", font=self.fonts["small"],
                                     bg=COLORS["accent_blue"],
                                     fg=COLORS["text_white"], padx=8, pady=2)
        self._alert_count.pack(side="right")

        frame = tk.Frame(parent, bg=COLORS["bg_panel"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
        frame.pack(fill="both", expand=True, pady=(0, 12))

        self._alerts_canvas = tk.Canvas(frame, bg=COLORS["bg_panel"],
                                        highlightthickness=0)
        self._alerts_inner = tk.Frame(self._alerts_canvas, bg=COLORS["bg_panel"])
        self._alerts_canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self._alerts_canvas.create_window((0, 0), window=self._alerts_inner, anchor="nw")
        self._alerts_inner.bind("<Configure>",
                                lambda e: self._alerts_canvas.configure(
                                    scrollregion=self._alerts_canvas.bbox("all")))

        self._alerts_placeholder = tk.Label(
            self._alerts_inner, text="\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0430\u043b\u0435\u0440\u0442\u043e\u0432",
            font=self.fonts["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_dim"], pady=30)
        self._alerts_placeholder.pack()

    def _build_controls_panel(self, parent):
        tk.Label(parent, text="\u2699  \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
                 font=self.fonts["heading"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 10))

        ctrl = tk.Frame(parent, bg=COLORS["bg_panel"],
                        highlightbackground=COLORS["border"], highlightthickness=1)
        ctrl.pack(fill="x")
        ci = tk.Frame(ctrl, bg=COLORS["bg_panel"])
        ci.pack(fill="x", padx=12, pady=12)

        # ── Выбор режима ──
        tk.Label(ci, text="\u0420\u0435\u0436\u0438\u043c \u0440\u0430\u0431\u043e\u0442\u044b:",
                 font=self.fonts["body_bold"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 6))

        self._mode_var = tk.StringVar(value="demo")
        modes_frame = tk.Frame(ci, bg=COLORS["bg_panel"])
        modes_frame.pack(fill="x", pady=(0, 8))

        for val, label in [("demo", "Demo (\u0441\u0438\u043c\u0443\u043b\u044f\u0442\u043e\u0440)"),
                           ("live", "Live (Asterisk AMI)")]:
            rb = tk.Radiobutton(modes_frame, text=label, variable=self._mode_var,
                                value=val, font=self.fonts["body"],
                                bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
                                selectcolor=COLORS["bg_card"],
                                activebackground=COLORS["bg_panel"],
                                activeforeground=COLORS["text_white"],
                                command=self._on_mode_change)
            rb.pack(anchor="w")

        # ── AMI settings (hidden by default) ──
        self._ami_frame = tk.Frame(ci, bg=COLORS["bg_panel"])
        # Не pack — показываем только при mode=live

        ami_fields = [
            ("Host:", self._ami_host),
            ("Port:", self._ami_port),
            ("User:", self._ami_user),
            ("Password:", self._ami_pass),
        ]
        for label_text, var in ami_fields:
            row = tk.Frame(self._ami_frame, bg=COLORS["bg_panel"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, font=self.fonts["small"],
                     bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
                     width=9, anchor="w").pack(side="left")
            entry = tk.Entry(row, textvariable=var, font=self.fonts["small"],
                             bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                             insertbackground=COLORS["text_white"],
                             highlightbackground=COLORS["border"],
                             highlightthickness=1, relief="flat")
            entry.pack(side="left", fill="x", expand=True)

        tk.Frame(ci, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        # ── Кнопка запуска ──
        self._btn_start = StyledButton(
            ci, "\u25b6  \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c",
            COLORS["btn_success"], COLORS["btn_success_hover"],
            command=self._on_start, width=220, height=40)
        self._btn_start.pack(pady=(0, 10))

        tk.Frame(ci, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        # ── Сценарии аномалий ──
        tk.Label(ci, text="\u0421\u0446\u0435\u043d\u0430\u0440\u0438\u0438 \u0430\u043d\u043e\u043c\u0430\u043b\u0438\u0439:",
                 font=self.fonts["body_bold"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(4, 8))

        btns = [
            ("\u26a0  \u0414\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f 4G",
             COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject("4g")),
            ("\u26a0  \u041f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430 WiFi",
             COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject("wifi")),
            ("\u2714  \u0421\u043d\u044f\u0442\u044c \u0430\u043d\u043e\u043c\u0430\u043b\u0438\u0438",
             COLORS["btn_neutral"], COLORS["btn_neutral_hover"],
             self._clear_anomalies),
        ]
        for text, color, hover, cmd in btns:
            StyledButton(ci, text, color, hover, command=cmd,
                         width=220, height=34).pack(pady=3)

    def _on_mode_change(self):
        if self._mode_var.get() == "live":
            self._ami_frame.pack(fill="x", pady=(0, 8))
        else:
            self._ami_frame.pack_forget()

    # ─── Call Cards ──────────────────────────────────────────────────────

    def _create_call_card(self, channel_id: str, caller_ip: str,
                          is_external: bool):
        card = tk.Frame(self._calls_container, bg=COLORS["bg_card"],
                        highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="x", pady=4)

        # Row 1: channel info + QoP badge
        top = tk.Frame(card, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=16, pady=(12, 4))

        tk.Label(top, text=f"\U0001f4de {channel_id}", font=self.fonts["body_bold"],
                 bg=COLORS["bg_card"], fg=COLORS["text_white"]).pack(side="left")

        net_text = "WAN" if is_external else "LAN"
        net_color = COLORS["qop_high"] if is_external else COLORS["qop_low"]
        net_bg = COLORS["qop_high_bg"] if is_external else COLORS["qop_low_bg"]
        tk.Label(top, text=f"  {net_text}  ", font=self.fonts["small"],
                 bg=net_bg, fg=net_color).pack(side="left", padx=8)

        tk.Label(top, text=caller_ip, font=self.fonts["mono_small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=8)

        # QoP badge
        qop_f = tk.Frame(top, bg=COLORS["bg_card"])
        qop_f.pack(side="right")

        qop_icon = tk.Label(qop_f, text="\u25cf", font=("Helvetica", 14),
                            bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        qop_icon.pack(side="left")

        qop_label = tk.Label(qop_f, text="ANALYZING...", font=self.fonts["qop_level"],
                             bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        qop_label.pack(side="left", padx=(4, 0))

        qop_sub = tk.Label(qop_f, text="", font=self.fonts["qop_sub"],
                           bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        qop_sub.pack(side="left", padx=(8, 0))

        # Row 2: metrics
        mf = tk.Frame(card, bg=COLORS["bg_card"])
        mf.pack(fill="x", padx=16, pady=(4, 4))

        metrics_info = [
            ("latency", "\u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430", "ms", COLORS["chart_latency"]),
            ("jitter", "\u0414\u0436\u0438\u0442\u0442\u0435\u0440", "ms", COLORS["chart_jitter"]),
            ("loss", "\u041f\u043e\u0442\u0435\u0440\u0438", "%", COLORS["chart_loss"]),
            ("confidence", "\u0423\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c", "%", COLORS["accent_cyan"]),
        ]

        metric_widgets = {}
        for key, lbl, unit, color in metrics_info:
            col = tk.Frame(mf, bg=COLORS["bg_card"])
            col.pack(side="left", expand=True, fill="x", padx=4)

            tk.Label(col, text=lbl, font=self.fonts["metric_label"],
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"]).pack(anchor="w")

            vf = tk.Frame(col, bg=COLORS["bg_card"])
            vf.pack(anchor="w")
            val = tk.Label(vf, text="\u2014", font=self.fonts["metric_big"],
                           bg=COLORS["bg_card"], fg=color)
            val.pack(side="left")
            tk.Label(vf, text=f" {unit}", font=self.fonts["small"],
                     bg=COLORS["bg_card"], fg=COLORS["text_dim"]
                     ).pack(side="left", anchor="s", pady=4)
            metric_widgets[key] = val

        # Row 3: charts
        cf = tk.Frame(card, bg=COLORS["bg_card"])
        cf.pack(fill="x", padx=16, pady=(0, 10))

        charts = {}
        for key, _, _, color in metrics_info[:3]:
            chart = MetricChart(cf, color=color, max_points=40, height=45)
            chart.pack(side="left", expand=True, fill="x", padx=2)
            charts[key] = chart

        self._call_cards[channel_id] = {
            "frame": card, "qop_icon": qop_icon, "qop_label": qop_label,
            "qop_sub": qop_sub, "metrics": metric_widgets, "charts": charts,
        }

    def _update_call_card(self, channel_id: str, metrics: dict,
                          prediction: Optional[dict] = None):
        if channel_id not in self._call_cards:
            return
        card = self._call_cards[channel_id]

        lat = metrics.get("latency_ms", 0)
        jit = metrics.get("jitter_ms", 0)
        loss = metrics.get("packet_loss_pct", 0)

        card["metrics"]["latency"].config(text=f"{lat:.0f}")
        card["metrics"]["jitter"].config(text=f"{jit:.1f}")
        card["metrics"]["loss"].config(text=f"{loss:.2f}")

        card["charts"]["latency"].add_point(lat)
        card["charts"]["jitter"].add_point(jit)
        card["charts"]["loss"].add_point(loss)

        if prediction:
            level = prediction["level_name"]
            conf = prediction["confidence"]
            cfg = QOP_CONFIG[level]

            card["qop_icon"].config(text="\u25cf", fg=cfg["color"])
            card["qop_label"].config(text=cfg["label"], fg=cfg["color"])
            card["qop_sub"].config(text=cfg["subtitle"], fg=cfg["color"])
            card["metrics"]["confidence"].config(text=f"{conf:.0%}",
                                                 fg=COLORS["accent_cyan"])
            card["frame"].config(highlightbackground=cfg["color"])

    def _remove_call_card(self, channel_id: str):
        if channel_id in self._call_cards:
            self._call_cards[channel_id]["frame"].destroy()
            del self._call_cards[channel_id]

    # ─── Alerts ──────────────────────────────────────────────────────────

    def _add_alert(self, severity: str, title: str, message: str):
        self._alerts_placeholder.pack_forget()

        color_map = {"info": COLORS["alert_info"],
                     "warning": COLORS["alert_warning"],
                     "critical": COLORS["alert_critical"]}
        color = color_map.get(severity, COLORS["text_secondary"])

        af = tk.Frame(self._alerts_inner, bg=COLORS["bg_card"],
                      highlightbackground=color, highlightthickness=1)
        af.pack(fill="x", padx=4, pady=3)

        top = tk.Frame(af, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(top, text=f"[{severity.upper()}]", font=self.fonts["small"],
                 bg=COLORS["bg_card"], fg=color).pack(side="left")
        tk.Label(top, text=time.strftime("%H:%M:%S"), font=self.fonts["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(side="right")

        tk.Label(af, text=title, font=self.fonts["body_bold"],
                 bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                 anchor="w", wraplength=360).pack(fill="x", padx=8)
        tk.Label(af, text=message, font=self.fonts["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                 anchor="w", wraplength=360, justify="left"
                 ).pack(fill="x", padx=8, pady=(0, 6))

        self._alerts_widgets.append(af)
        if len(self._alerts_widgets) > 20:
            old = self._alerts_widgets.pop(0)
            old.destroy()

        self._alert_count.config(text=str(len(self._alerts_widgets)))
        self._alerts_canvas.update_idletasks()
        self._alerts_canvas.yview_moveto(1.0)

    # ─── Start / Stop ────────────────────────────────────────────────────

    def _on_start(self):
        if self._running:
            return
        self._running = True

        mode = self._mode_var.get()
        thread = threading.Thread(target=self._worker_thread,
                                  args=(mode,), daemon=True)
        thread.start()

    def _worker_thread(self, mode: str):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            if mode == "demo":
                self._loop.run_until_complete(self._run_demo())
            elif mode == "live":
                self._loop.run_until_complete(self._run_live())
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            self.root.after(0, lambda: self._set_status(
                f"\u2718 \u041e\u0448\u0438\u0431\u043a\u0430: {e}", COLORS["alert_critical"]))

    def _set_status(self, text: str, color: str):
        self._status_var.set(text)
        self._status_dot.delete("dot")
        self._status_dot.create_oval(2, 2, 10, 10, fill=color, outline=color, tags="dot")

    # ─── Pipeline: metrics → ML → recommendation → UI ────────────────────

    def _process_tick(self, channel_id: str, caller_ip: str,
                      is_external: bool, features: dict):
        """Один тик конвейера: предсказание + рекомендация + обновление UI."""
        prediction = self._predictor.predict(features)

        rec = self._rec_engine.process_prediction(
            channel_id=channel_id,
            prediction=prediction,
            metrics={**features, "caller_ip": caller_ip},
        )

        # Update UI from main thread
        self.root.after(0, lambda: self._update_call_card(
            channel_id, features, prediction))

        # Alert on level change
        if rec.is_change:
            level_order = {"low": 0, "medium": 1, "high": 2}
            going_down = level_order.get(rec.level, 0) < level_order.get(rec.previous_level, 0)

            if going_down:
                sev = "critical" if rec.level == "low" else "warning"
                title = "\u0414\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f \u043a\u0430\u043d\u0430\u043b\u0430 \u2014 \u043f\u043e\u043d\u0438\u0436\u0435\u043d\u0438\u0435 QoP"
            else:
                sev = "info"
                title = "\u0423\u043b\u0443\u0447\u0448\u0435\u043d\u0438\u0435 \u043a\u0430\u043d\u0430\u043b\u0430 \u2014 \u043f\u043e\u0432\u044b\u0448\u0435\u043d\u0438\u0435 QoP"

            msg = (f"{channel_id}: {rec.previous_level.upper()} \u2192 {rec.level.upper()}\n"
                   f"\u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430: {rec.latency_ms:.0f}\u043c\u0441, "
                   f"\u0414\u0436\u0438\u0442\u0442\u0435\u0440: {rec.jitter_ms:.1f}\u043c\u0441, "
                   f"\u041f\u043e\u0442\u0435\u0440\u0438: {rec.packet_loss_pct:.2f}%")
            self.root.after(0, lambda s=sev, t=title, m=msg: self._add_alert(s, t, m))

    # ─── Demo Mode ───────────────────────────────────────────────────────

    async def _run_demo(self):
        self.root.after(0, lambda: self._set_status(
            "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 ML-\u043c\u043e\u0434\u0435\u043b\u0435\u0439...", COLORS["accent_blue"]))

        from ml_agent.inference import QoPPredictor
        from recommendation.engine import QoPRecommendationEngine
        from monitoring.simulator import AMISimulator

        self._predictor = QoPPredictor()
        self._predictor.load()
        self._rec_engine = QoPRecommendationEngine()
        self._simulator = AMISimulator()

        profiles = [
            ("lan_ideal", "192.168.1.100", False),
            ("wan_wifi_public", "176.59.44.12", True),
            ("wan_4g_mobile", "85.143.22.45", True),
        ]
        for profile, ip, is_ext in profiles:
            ch = self._simulator.add_call(profile)
            self._channels[profile] = ch
            self.root.after(0, lambda c=ch, i=ip, e=is_ext:
                            self._create_call_card(c, i, e))

        await asyncio.sleep(0.3)
        self.root.after(0, lambda: self._set_status(
            "\u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0430\u043a\u0442\u0438\u0432\u0435\u043d  \u2022  Demo  \u2022  3 \u0432\u044b\u0437\u043e\u0432\u0430",
            COLORS["qop_low"]))

        while self._running:
            for ch_id, call in list(self._simulator.active_calls.items()):
                metrics_obj = self._simulator._generate_metrics(call)
                features = metrics_obj.to_feature_vector()
                self._process_tick(ch_id, metrics_obj.caller_ip,
                                   metrics_obj.is_external, features)
            await asyncio.sleep(2.0)

    # ─── Live Mode ───────────────────────────────────────────────────────

    async def _run_live(self):
        self.root.after(0, lambda: self._set_status(
            "\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 \u043a Asterisk AMI...", COLORS["accent_blue"]))

        from ml_agent.inference import QoPPredictor
        from recommendation.engine import QoPRecommendationEngine
        from monitoring.ami_collector import AMICollector, CallMetrics

        self._predictor = QoPPredictor()
        self._predictor.load()
        self._rec_engine = QoPRecommendationEngine()

        # Build config override for AMI connection
        import yaml
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        config["asterisk"]["host"] = self._ami_host.get()
        config["asterisk"]["ami_port"] = int(self._ami_port.get())
        config["asterisk"]["ami_username"] = self._ami_user.get()
        config["asterisk"]["ami_password"] = self._ami_pass.get()

        # Write temp config
        tmp_cfg = "config_live_tmp.yaml"
        with open(tmp_cfg, "w") as f:
            yaml.dump(config, f)

        collector = AMICollector(tmp_cfg)

        async def on_metrics(metrics: CallMetrics):
            ch_id = metrics.channel_id
            # Create card if new channel
            if ch_id not in self._call_cards:
                self.root.after(0, lambda c=ch_id, ip=metrics.caller_ip,
                                ext=metrics.is_external:
                                self._create_call_card(c, ip, ext))
                await asyncio.sleep(0.1)

            features = metrics.to_feature_vector()
            self._process_tick(ch_id, metrics.caller_ip,
                               metrics.is_external, features)

        collector.on_metrics(on_metrics)

        try:
            await collector.connect()
            self.root.after(0, lambda: self._set_status(
                f"\u041f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u043e \u043a {self._ami_host.get()}:{self._ami_port.get()}  \u2022  Live",
                COLORS["qop_low"]))
            await asyncio.gather(
                collector._event_loop(),
                collector._aggregation_loop(),
            )
        except Exception as e:
            self.root.after(0, lambda: self._set_status(
                f"\u041e\u0448\u0438\u0431\u043a\u0430 AMI: {e}", COLORS["alert_critical"]))
            self.root.after(0, lambda: self._add_alert(
                "critical",
                "\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f \u043a AMI",
                str(e)))
        finally:
            import os
            if os.path.exists(tmp_cfg):
                os.remove(tmp_cfg)

    # ─── Anomaly controls ────────────────────────────────────────────────

    def _inject(self, scenario: str):
        if not self._simulator or not self._channels:
            return
        if scenario == "4g":
            ch = self._channels.get("wan_4g_mobile")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=150,
                                               jitter_add=25, loss_add=5)
                self._set_status(
                    "\u26a0 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u044f: \u0434\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f 4G (+150\u043c\u0441, +5% \u043f\u043e\u0442\u0435\u0440\u044c)",
                    COLORS["alert_warning"])
        elif scenario == "wifi":
            ch = self._channels.get("wan_wifi_public")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=200,
                                               jitter_add=40, loss_add=8)
                self._set_status(
                    "\u26a0 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u044f: \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430 WiFi (+200\u043c\u0441, +8% \u043f\u043e\u0442\u0435\u0440\u044c)",
                    COLORS["alert_critical"])

    def _clear_anomalies(self):
        if not self._simulator or not self._channels:
            return
        for ch in self._channels.values():
            self._simulator.clear_anomaly(ch)
        self._set_status(
            "\u2714 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u0438 \u0441\u043d\u044f\u0442\u044b",
            COLORS["qop_low"])

    # ─── Run ─────────────────────────────────────────────────────────────

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.root.destroy()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    app = QoPDashboard()
    app.run()


if __name__ == "__main__":
    main()
