"""
Профессиональный GUI-дашборд на tkinter — Интеллектуальная система QoP.

Панели:
  - Заголовок с логотипом системы
  - Карточки активных вызовов с метриками и QoP-индикаторами
  - Графики метрик в реальном времени (latency, jitter, loss)
  - Панель алертов с цветовой индикацией
  - Панель управления демо-сценариями
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import threading
import asyncio
import time
import logging
import os
import sys
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
        "icon": "\u25cf",  # ●
    },
    "medium": {
        "label": "MEDIUM",
        "subtitle": "SIP TLS Only",
        "color": COLORS["qop_medium"],
        "bg": COLORS["qop_medium_bg"],
        "icon": "\u25cf",
    },
    "high": {
        "label": "HIGH",
        "subtitle": "SIP TLS + SRTP",
        "color": COLORS["qop_high"],
        "bg": COLORS["qop_high_bg"],
        "icon": "\u25cf",
    },
}


# ─── Вспомогательные виджеты ─────────────────────────────────────────────────

class RoundedFrame(tk.Canvas):
    """Фрейм с закруглёнными углами."""

    def __init__(self, parent, bg_color, border_color=None, radius=12, **kwargs):
        self._bg_color = bg_color
        self._border_color = border_color or bg_color
        self._radius = radius
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, **kwargs)
        self.bind("<Configure>", self._draw)
        self.inner = tk.Frame(self, bg=bg_color)
        self.create_window(0, 0, window=self.inner, anchor="nw")

    def _draw(self, event=None):
        self.delete("bg")
        w, h, r = self.winfo_width(), self.winfo_height(), self._radius
        # Рамка
        self.create_rounded_rect(1, 1, w - 1, h - 1, r, self._border_color, "bg")
        # Заливка
        self.create_rounded_rect(2, 2, w - 2, h - 2, r - 1, self._bg_color, "bg")
        self.tag_lower("bg")
        self.inner.place(x=r // 2, y=r // 2, width=w - r, height=h - r)

    def create_rounded_rect(self, x1, y1, x2, y2, r, fill, tag):
        self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90,
                        fill=fill, outline=fill, tags=tag)
        self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90,
                        fill=fill, outline=fill, tags=tag)
        self.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90,
                        fill=fill, outline=fill, tags=tag)
        self.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90,
                        fill=fill, outline=fill, tags=tag)
        self.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill, tags=tag)
        self.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill, outline=fill, tags=tag)
        self.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill, outline=fill, tags=tag)


class MetricChart(tk.Canvas):
    """Мини-график временного ряда метрики."""

    def __init__(self, parent, color: str, max_points: int = 40,
                 height: int = 60, **kwargs):
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
        padding = 4

        max_val = max(self.data) * 1.2 if max(self.data) > 0 else 1
        min_val = 0

        points = []
        for i, val in enumerate(self.data):
            x = padding + (w - 2 * padding) * i / (self.max_points - 1)
            y = h - padding - (h - 2 * padding) * (val - min_val) / (max_val - min_val)
            points.append((x, y))

        # Заливка под графиком
        fill_points = list(points) + [(points[-1][0], h), (points[0][0], h)]
        flat = [coord for p in fill_points for coord in p]
        # Полупрозрачная заливка через stipple
        self.create_polygon(flat, fill=self.color, outline="", stipple="gray25")

        # Линия графика
        flat_line = [coord for p in points for coord in p]
        if len(flat_line) >= 4:
            self.create_line(flat_line, fill=self.color, width=2, smooth=True)

        # Последнее значение
        if points:
            lx, ly = points[-1]
            self.create_oval(lx - 3, ly - 3, lx + 3, ly + 3,
                             fill=self.color, outline=COLORS["text_white"], width=1)


class StyledButton(tk.Canvas):
    """Кнопка с закруглёнными углами и hover-эффектом."""

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

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _draw(self):
        self.delete("all")
        r = 8
        w, h = self._btn_width, self._btn_height
        # Закруглённый прямоугольник
        self.create_arc(0, 0, 2 * r, 2 * r, start=90, extent=90,
                        fill=self._current_color, outline=self._current_color)
        self.create_arc(w - 2 * r, 0, w, 2 * r, start=0, extent=90,
                        fill=self._current_color, outline=self._current_color)
        self.create_arc(0, h - 2 * r, 2 * r, h, start=180, extent=90,
                        fill=self._current_color, outline=self._current_color)
        self.create_arc(w - 2 * r, h - 2 * r, w, h, start=270, extent=90,
                        fill=self._current_color, outline=self._current_color)
        self.create_rectangle(r, 0, w - r, h, fill=self._current_color,
                              outline=self._current_color)
        self.create_rectangle(0, r, w, h - r, fill=self._current_color,
                              outline=self._current_color)
        self.create_text(w // 2, h // 2, text=self._text,
                         fill=COLORS["text_white"],
                         font=("Helvetica", 11, "bold"))

    def _on_enter(self, e):
        self._current_color = self._hover_color
        self._draw()

    def _on_leave(self, e):
        self._current_color = self._color
        self._draw()

    def _on_click(self, e):
        if self._command:
            self._command()


# ─── Главный дашборд ─────────────────────────────────────────────────────────

class QoPDashboard:
    """Профессиональный GUI-дашборд системы рекомендаций QoP."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("QoP Intelligent Recommendation System")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.geometry("1280x820")
        self.root.minsize(1100, 700)

        # Шрифты
        self.fonts = {
            "title": ("Helvetica", 20, "bold"),
            "subtitle": ("Helvetica", 12),
            "heading": ("Helvetica", 14, "bold"),
            "body": ("Helvetica", 11),
            "body_bold": ("Helvetica", 11, "bold"),
            "small": ("Helvetica", 10),
            "mono": ("Courier", 11),
            "mono_small": ("Courier", 10),
            "metric_big": ("Helvetica", 22, "bold"),
            "metric_label": ("Helvetica", 9),
            "qop_level": ("Helvetica", 16, "bold"),
            "qop_sub": ("Helvetica", 9),
            "alert_title": ("Helvetica", 11, "bold"),
            "alert_body": ("Helvetica", 10),
        }

        # Данные
        self._call_cards: dict[str, dict] = {}
        self._alerts_list: list[dict] = []
        self._charts: dict[str, dict[str, MetricChart]] = {}
        self._status_var = tk.StringVar(value="Система готова к запуску")
        self._running = False
        self._simulator = None
        self._predictor = None
        self._rec_engine = None
        self._loop = None
        self._demo_phase = tk.StringVar(value="idle")

        self._build_ui()

    # ─── UI Layout ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        self._build_header()

        # Main content area
        content = tk.Frame(self.root, bg=COLORS["bg_dark"])
        content.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Left: calls + charts
        left = tk.Frame(content, bg=COLORS["bg_dark"])
        left.pack(side="left", fill="both", expand=True)

        self._calls_container = tk.Frame(left, bg=COLORS["bg_dark"])
        self._calls_container.pack(fill="both", expand=True, pady=(0, 8))

        # Right: alerts + controls
        right = tk.Frame(content, bg=COLORS["bg_dark"], width=380)
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

        # Левая часть — название
        left = tk.Frame(inner, bg=COLORS["bg_panel"])
        left.pack(side="left", fill="y")

        # Иконка
        icon_label = tk.Label(left, text="\u26a1", font=("Helvetica", 28),
                              bg=COLORS["bg_panel"], fg=COLORS["accent_cyan"])
        icon_label.pack(side="left", padx=(0, 12))

        text_frame = tk.Frame(left, bg=COLORS["bg_panel"])
        text_frame.pack(side="left")

        tk.Label(text_frame, text="QoP Recommendation System",
                 font=self.fonts["title"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_white"]).pack(anchor="w")
        tk.Label(text_frame, text="Intelligent VoIP Security Advisor  \u2022  Asterisk PBX",
                 font=self.fonts["small"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_secondary"]).pack(anchor="w")

        # Правая часть — статус
        right = tk.Frame(inner, bg=COLORS["bg_panel"])
        right.pack(side="right", fill="y")

        self._status_indicator = tk.Canvas(right, width=12, height=12,
                                           bg=COLORS["bg_panel"],
                                           highlightthickness=0)
        self._status_indicator.pack(side="left", padx=(0, 8), pady=20)
        self._status_indicator.create_oval(2, 2, 10, 10,
                                           fill=COLORS["text_dim"],
                                           outline=COLORS["text_dim"],
                                           tags="dot")

        self._status_label = tk.Label(right, textvariable=self._status_var,
                                      font=self.fonts["small"],
                                      bg=COLORS["bg_panel"],
                                      fg=COLORS["text_secondary"])
        self._status_label.pack(side="left", pady=20)

        # Разделительная линия
        sep = tk.Frame(self.root, bg=COLORS["border"], height=1)
        sep.pack(fill="x")

    def _build_alerts_panel(self, parent):
        # Заголовок
        header = tk.Frame(parent, bg=COLORS["bg_dark"])
        header.pack(fill="x", pady=(0, 8))

        tk.Label(header, text="\U0001f514  \u0410\u043b\u0435\u0440\u0442\u044b",
                 font=self.fonts["heading"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self._alert_count_label = tk.Label(header, text="0",
                                           font=self.fonts["small"],
                                           bg=COLORS["accent_blue"],
                                           fg=COLORS["text_white"],
                                           padx=8, pady=2)
        self._alert_count_label.pack(side="right")

        # Контейнер алертов со скроллом
        alerts_frame = tk.Frame(parent, bg=COLORS["bg_panel"],
                                highlightbackground=COLORS["border"],
                                highlightthickness=1)
        alerts_frame.pack(fill="both", expand=True, pady=(0, 12))

        self._alerts_canvas = tk.Canvas(alerts_frame, bg=COLORS["bg_panel"],
                                        highlightthickness=0)
        self._alerts_inner = tk.Frame(self._alerts_canvas, bg=COLORS["bg_panel"])
        self._alerts_canvas.pack(fill="both", expand=True, padx=2, pady=2)
        self._alerts_canvas.create_window((0, 0), window=self._alerts_inner,
                                          anchor="nw")
        self._alerts_inner.bind("<Configure>",
                                lambda e: self._alerts_canvas.configure(
                                    scrollregion=self._alerts_canvas.bbox("all")))

        # Placeholder
        self._alerts_placeholder = tk.Label(
            self._alerts_inner,
            text="\u041d\u0435\u0442 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u0430\u043b\u0435\u0440\u0442\u043e\u0432",
            font=self.fonts["small"],
            bg=COLORS["bg_panel"],
            fg=COLORS["text_dim"],
            pady=30
        )
        self._alerts_placeholder.pack()

    def _build_controls_panel(self, parent):
        # Заголовок
        tk.Label(parent, text="\u2699  \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
                 font=self.fonts["heading"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 10))

        ctrl = tk.Frame(parent, bg=COLORS["bg_panel"],
                        highlightbackground=COLORS["border"],
                        highlightthickness=1)
        ctrl.pack(fill="x")
        ctrl_inner = tk.Frame(ctrl, bg=COLORS["bg_panel"])
        ctrl_inner.pack(fill="x", padx=12, pady=12)

        # Кнопка запуска
        self._btn_start = StyledButton(
            ctrl_inner, "\u25b6  \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c Demo",
            COLORS["btn_success"], COLORS["btn_success_hover"],
            command=self._start_demo, width=200, height=40
        )
        self._btn_start.pack(pady=(0, 10))

        # Separator
        tk.Frame(ctrl_inner, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        tk.Label(ctrl_inner, text="\u0421\u0446\u0435\u043d\u0430\u0440\u0438\u0438 \u0430\u043d\u043e\u043c\u0430\u043b\u0438\u0439:",
                 font=self.fonts["body_bold"],
                 bg=COLORS["bg_panel"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(4, 8))

        # Кнопки сценариев
        scenarios = [
            ("\u26a0  \u0414\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f 4G",
             COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject_anomaly("4g")),
            ("\u26a0  \u041f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430 WiFi",
             COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject_anomaly("wifi")),
            ("\u2714  \u0421\u043d\u044f\u0442\u044c \u0430\u043d\u043e\u043c\u0430\u043b\u0438\u0438",
             COLORS["btn_neutral"], COLORS["btn_neutral_hover"],
             self._clear_anomalies),
        ]

        self._scenario_btns = []
        for text, color, hover, cmd in scenarios:
            btn = StyledButton(ctrl_inner, text, color, hover,
                               command=cmd, width=200, height=34)
            btn.pack(pady=3)
            self._scenario_btns.append(btn)

    # ─── Call Cards ──────────────────────────────────────────────────────

    def _create_call_card(self, channel_id: str, caller_ip: str,
                          is_external: bool) -> dict:
        """Создать карточку вызова."""
        card_frame = tk.Frame(self._calls_container, bg=COLORS["bg_card"],
                              highlightbackground=COLORS["border"],
                              highlightthickness=1)
        card_frame.pack(fill="x", pady=4)

        # Верхняя строка: канал + IP + тип
        top = tk.Frame(card_frame, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=16, pady=(12, 4))

        tk.Label(top, text=f"\U0001f4de {channel_id}",
                 font=self.fonts["body_bold"],
                 bg=COLORS["bg_card"],
                 fg=COLORS["text_white"]).pack(side="left")

        net_text = "WAN" if is_external else "LAN"
        net_color = COLORS["qop_high"] if is_external else COLORS["qop_low"]
        net_bg = COLORS["qop_high_bg"] if is_external else COLORS["qop_low_bg"]

        net_label = tk.Label(top, text=f"  {net_text}  ",
                             font=self.fonts["small"],
                             bg=net_bg, fg=net_color)
        net_label.pack(side="left", padx=8)

        tk.Label(top, text=caller_ip,
                 font=self.fonts["mono_small"],
                 bg=COLORS["bg_card"],
                 fg=COLORS["text_secondary"]).pack(side="left", padx=8)

        # QoP badge (правая часть)
        qop_frame = tk.Frame(top, bg=COLORS["bg_card"])
        qop_frame.pack(side="right")

        qop_icon = tk.Label(qop_frame, text="\u25cf",
                            font=("Helvetica", 14),
                            bg=COLORS["bg_card"],
                            fg=COLORS["text_dim"])
        qop_icon.pack(side="left")

        qop_label = tk.Label(qop_frame, text="ANALYZING...",
                             font=self.fonts["qop_level"],
                             bg=COLORS["bg_card"],
                             fg=COLORS["text_dim"])
        qop_label.pack(side="left", padx=(4, 0))

        qop_sub = tk.Label(qop_frame, text="",
                           font=self.fonts["qop_sub"],
                           bg=COLORS["bg_card"],
                           fg=COLORS["text_dim"])
        qop_sub.pack(side="left", padx=(8, 0))

        # Метрики
        metrics_frame = tk.Frame(card_frame, bg=COLORS["bg_card"])
        metrics_frame.pack(fill="x", padx=16, pady=(4, 4))

        metric_widgets = {}
        metrics_info = [
            ("latency", "\u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430", "ms",
             COLORS["chart_latency"]),
            ("jitter", "\u0414\u0436\u0438\u0442\u0442\u0435\u0440", "ms",
             COLORS["chart_jitter"]),
            ("loss", "\u041f\u043e\u0442\u0435\u0440\u0438", "%",
             COLORS["chart_loss"]),
            ("confidence", "\u0423\u0432\u0435\u0440\u0435\u043d\u043d\u043e\u0441\u0442\u044c", "%",
             COLORS["accent_cyan"]),
        ]

        for key, label, unit, color in metrics_info:
            mf = tk.Frame(metrics_frame, bg=COLORS["bg_card"])
            mf.pack(side="left", expand=True, fill="x", padx=4)

            tk.Label(mf, text=label,
                     font=self.fonts["metric_label"],
                     bg=COLORS["bg_card"],
                     fg=COLORS["text_secondary"]).pack(anchor="w")

            val_frame = tk.Frame(mf, bg=COLORS["bg_card"])
            val_frame.pack(anchor="w")

            val = tk.Label(val_frame, text="—",
                           font=self.fonts["metric_big"],
                           bg=COLORS["bg_card"], fg=color)
            val.pack(side="left")

            tk.Label(val_frame, text=f" {unit}",
                     font=self.fonts["small"],
                     bg=COLORS["bg_card"],
                     fg=COLORS["text_dim"]).pack(side="left", anchor="s", pady=4)

            metric_widgets[key] = val

        # Графики
        charts_frame = tk.Frame(card_frame, bg=COLORS["bg_card"])
        charts_frame.pack(fill="x", padx=16, pady=(0, 10))

        charts = {}
        for key, _, _, color in metrics_info[:3]:
            chart = MetricChart(charts_frame, color=color, max_points=40, height=45)
            chart.pack(side="left", expand=True, fill="x", padx=2)
            charts[key] = chart

        card_data = {
            "frame": card_frame,
            "qop_icon": qop_icon,
            "qop_label": qop_label,
            "qop_sub": qop_sub,
            "metrics": metric_widgets,
            "charts": charts,
            "channel_id": channel_id,
        }

        self._call_cards[channel_id] = card_data
        return card_data

    def _update_call_card(self, channel_id: str, metrics: dict,
                          prediction: Optional[dict] = None):
        """Обновить данные карточки (вызывается из UI-потока)."""
        if channel_id not in self._call_cards:
            return

        card = self._call_cards[channel_id]

        # Метрики
        lat = metrics.get("latency_ms", 0)
        jit = metrics.get("jitter_ms", 0)
        loss = metrics.get("packet_loss_pct", 0)

        card["metrics"]["latency"].config(text=f"{lat:.0f}")
        card["metrics"]["jitter"].config(text=f"{jit:.1f}")
        card["metrics"]["loss"].config(text=f"{loss:.2f}")

        # Графики
        card["charts"]["latency"].add_point(lat)
        card["charts"]["jitter"].add_point(jit)
        card["charts"]["loss"].add_point(loss)

        # QoP
        if prediction:
            level = prediction["level_name"]
            conf = prediction["confidence"]
            cfg = QOP_CONFIG[level]

            card["qop_icon"].config(text=cfg["icon"], fg=cfg["color"])
            card["qop_label"].config(text=cfg["label"], fg=cfg["color"])
            card["qop_sub"].config(text=cfg["subtitle"], fg=cfg["color"])
            card["metrics"]["confidence"].config(
                text=f"{conf:.0%}",
                fg=COLORS["accent_cyan"]
            )

            # Подсветка карточки
            card["frame"].config(highlightbackground=cfg["color"])

    # ─── Alerts ──────────────────────────────────────────────────────────

    def _add_alert_ui(self, severity: str, title: str, message: str):
        """Добавить алерт в панель."""
        self._alerts_placeholder.pack_forget()

        color_map = {
            "info": COLORS["alert_info"],
            "warning": COLORS["alert_warning"],
            "critical": COLORS["alert_critical"],
        }
        color = color_map.get(severity, COLORS["text_secondary"])

        af = tk.Frame(self._alerts_inner, bg=COLORS["bg_card"],
                      highlightbackground=color, highlightthickness=1)
        af.pack(fill="x", padx=4, pady=3)

        # Заголовок алерта
        top = tk.Frame(af, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=8, pady=(6, 2))

        sev_text = severity.upper()
        tk.Label(top, text=f"[{sev_text}]",
                 font=self.fonts["small"],
                 bg=COLORS["bg_card"], fg=color).pack(side="left")

        ts = time.strftime("%H:%M:%S")
        tk.Label(top, text=ts, font=self.fonts["small"],
                 bg=COLORS["bg_card"],
                 fg=COLORS["text_dim"]).pack(side="right")

        # Тело
        tk.Label(af, text=title,
                 font=self.fonts["alert_title"],
                 bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                 anchor="w", wraplength=340).pack(fill="x", padx=8)

        tk.Label(af, text=message,
                 font=self.fonts["alert_body"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                 anchor="w", wraplength=340, justify="left"
                 ).pack(fill="x", padx=8, pady=(0, 6))

        self._alerts_list.append(af)
        self._alert_count_label.config(text=str(len(self._alerts_list)))

        # Автоскролл
        self._alerts_canvas.update_idletasks()
        self._alerts_canvas.yview_moveto(1.0)

    # ─── Demo Logic ──────────────────────────────────────────────────────

    def _start_demo(self):
        """Запустить демо в отдельном потоке."""
        if self._running:
            return

        self._running = True
        self._set_status("\u0420\u0430\u0431\u043e\u0442\u0430\u0435\u0442", COLORS["qop_low"])

        thread = threading.Thread(target=self._demo_thread, daemon=True)
        thread.start()

    def _demo_thread(self):
        """Фоновый поток с asyncio event loop для демо."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._run_demo_async())
        except Exception as e:
            logger.error(f"Demo error: {e}")

    async def _run_demo_async(self):
        """Асинхронная логика демо."""
        # Загрузка моделей
        self.root.after(0, lambda: self._set_status(
            "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430 ML-\u043c\u043e\u0434\u0435\u043b\u0435\u0439...",
            COLORS["accent_blue"]))

        from ml_agent.inference import QoPPredictor
        from recommendation.engine import QoPRecommendationEngine
        from monitoring.simulator import AMISimulator

        self._predictor = QoPPredictor()
        self._predictor.load()

        self._rec_engine = QoPRecommendationEngine()

        self._simulator = AMISimulator()

        self.root.after(0, lambda: self._set_status(
            "\u041c\u043e\u0434\u0435\u043b\u0438 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u044b. \u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u0432\u044b\u0437\u043e\u0432\u043e\u0432...",
            COLORS["accent_blue"]))

        # Создать вызовы
        profiles = [
            ("lan_ideal", "192.168.1.100", False),
            ("wan_wifi_public", "203.0.113.50", True),
            ("wan_4g_mobile", "85.143.22.45", True),
        ]

        channels = {}
        for profile, ip, is_ext in profiles:
            ch = self._simulator.add_call(profile)
            channels[profile] = ch
            self.root.after(0, lambda c=ch, i=ip, e=is_ext:
                            self._create_call_card(c, i, e))

        self._channels = channels
        await asyncio.sleep(0.5)

        self.root.after(0, lambda: self._set_status(
            "\u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0430\u043a\u0442\u0438\u0432\u0435\u043d  \u2022  3 \u0432\u044b\u0437\u043e\u0432\u0430",
            COLORS["qop_low"]))

        # Цикл генерации метрик
        tick = 0
        while self._running:
            for ch_id, call in list(self._simulator.active_calls.items()):
                metrics_obj = self._simulator._generate_metrics(call)
                features = metrics_obj.to_feature_vector()
                features["caller_ip"] = metrics_obj.caller_ip

                prediction = self._predictor.predict(features)

                rec = self._rec_engine.process_prediction(
                    channel_id=ch_id,
                    prediction=prediction,
                    metrics={**features, "caller_ip": metrics_obj.caller_ip},
                )

                # Обновить UI
                self.root.after(0, lambda c=ch_id, m=features, p=prediction:
                                self._update_call_card(c, m, p))

                # Алерт при смене уровня
                if rec.is_change:
                    sev = "warning"
                    level_order = {"low": 0, "medium": 1, "high": 2}
                    if level_order.get(rec.level, 0) < level_order.get(rec.previous_level, 0):
                        sev = "critical" if rec.level == "low" else "warning"
                        title = "\u0414\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f \u043a\u0430\u043d\u0430\u043b\u0430 \u2014 \u043f\u043e\u043d\u0438\u0436\u0435\u043d\u0438\u0435 QoP"
                    else:
                        sev = "info"
                        title = "\u0423\u043b\u0443\u0447\u0448\u0435\u043d\u0438\u0435 \u043a\u0430\u043d\u0430\u043b\u0430 \u2014 \u043f\u043e\u0432\u044b\u0448\u0435\u043d\u0438\u0435 QoP"

                    msg = (
                        f"{ch_id}: {rec.previous_level.upper()} \u2192 {rec.level.upper()}\n"
                        f"\u0417\u0430\u0434\u0435\u0440\u0436\u043a\u0430: {rec.latency_ms:.0f}\u043c\u0441, "
                        f"\u0414\u0436\u0438\u0442\u0442\u0435\u0440: {rec.jitter_ms:.1f}\u043c\u0441, "
                        f"\u041f\u043e\u0442\u0435\u0440\u0438: {rec.packet_loss_pct:.2f}%"
                    )
                    self.root.after(0, lambda s=sev, t=title, m=msg:
                                    self._add_alert_ui(s, t, m))

            tick += 1
            await asyncio.sleep(2.0)

    def _inject_anomaly(self, scenario: str):
        """Внести аномалию в симулятор."""
        if not self._simulator or not self._channels:
            return

        if scenario == "4g":
            ch = self._channels.get("wan_4g_mobile")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=150, jitter_add=25, loss_add=5)
                self._set_status(
                    "\u26a0 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u044f: \u0434\u0435\u0433\u0440\u0430\u0434\u0430\u0446\u0438\u044f 4G (+150\u043c\u0441, +5% \u043f\u043e\u0442\u0435\u0440\u044c)",
                    COLORS["alert_warning"])
        elif scenario == "wifi":
            ch = self._channels.get("wan_wifi_public")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=200, jitter_add=40, loss_add=8)
                self._set_status(
                    "\u26a0 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u044f: \u043f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430 WiFi (+200\u043c\u0441, +8% \u043f\u043e\u0442\u0435\u0440\u044c)",
                    COLORS["alert_critical"])

    def _clear_anomalies(self):
        """Снять все аномалии."""
        if not self._simulator or not self._channels:
            return

        for ch in self._channels.values():
            self._simulator.clear_anomaly(ch)

        self._set_status(
            "\u2714 \u0410\u043d\u043e\u043c\u0430\u043b\u0438\u0438 \u0441\u043d\u044f\u0442\u044b. \u041a\u0430\u043d\u0430\u043b\u044b \u0441\u0442\u0430\u0431\u0438\u043b\u0438\u0437\u0438\u0440\u0443\u044e\u0442\u0441\u044f...",
            COLORS["qop_low"])

    def _set_status(self, text: str, color: str):
        """Обновить статус-бар."""
        self._status_var.set(text)
        self._status_indicator.delete("dot")
        self._status_indicator.create_oval(2, 2, 10, 10,
                                           fill=color, outline=color,
                                           tags="dot")

    # ─── Run ─────────────────────────────────────────────────────────────

    def run(self):
        """Запустить GUI."""
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
