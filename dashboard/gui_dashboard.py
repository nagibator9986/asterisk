"""
QoP Intelligent Recommendation System — Professional GUI Dashboard.

Современный tkinter-дашборд с расширенными метриками:
  - MOS (Mean Opinion Score) — оценка качества голоса 1-5
  - R-factor — E-Model качество
  - Живые графики: задержка, джиттер, потери, RTT, MOS
  - Длительность вызова, количество пакетов
  - Индикатор качества сигнала
  - Агрегированная статистика (всего вызовов, средний QoP, алертов)
  - Распределение QoP (круговая диаграмма)
  - Анимированные индикаторы статуса
  - Профессиональная тёмная тема с цветовыми акцентами
"""

import tkinter as tk
from tkinter import ttk
import threading
import asyncio
import time
import logging
import math
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)

# ═══ ЦВЕТОВАЯ ПАЛИТРА ═══════════════════════════════════════════════════════

COLORS = {
    # Background layers
    "bg_void": "#0a0e14",
    "bg_dark": "#0f1419",
    "bg_panel": "#151c24",
    "bg_card": "#1c2530",
    "bg_card_hover": "#253040",
    "bg_input": "#243140",
    "bg_accent": "#2d3e50",

    # Borders
    "border": "#2a3544",
    "border_bright": "#3d5a80",
    "border_accent": "#4fc3f7",

    # Text
    "text_primary": "#eceff4",
    "text_secondary": "#8899a6",
    "text_muted": "#556677",
    "text_dim": "#3a4756",
    "text_white": "#ffffff",

    # Accents
    "accent_blue": "#4fc3f7",
    "accent_cyan": "#00e5ff",
    "accent_purple": "#9c27b0",
    "accent_teal": "#26a69a",

    # QoP levels
    "qop_low": "#4caf50",       # Green
    "qop_low_dim": "#1b3a1e",
    "qop_medium": "#ff9800",    # Orange
    "qop_medium_dim": "#3a2810",
    "qop_high": "#f44336",      # Red
    "qop_high_dim": "#3a1515",

    # Alert severities
    "alert_info": "#4fc3f7",
    "alert_warning": "#ff9800",
    "alert_critical": "#f44336",
    "alert_success": "#4caf50",

    # Chart colors
    "chart_latency": "#4fc3f7",
    "chart_jitter": "#ffb74d",
    "chart_loss": "#f44336",
    "chart_mos": "#ba68c8",
    "chart_rtt": "#26a69a",

    # MOS quality colors
    "mos_excellent": "#4caf50",  # 4.0-5.0
    "mos_good": "#8bc34a",        # 3.6-4.0
    "mos_fair": "#ffc107",        # 3.1-3.6
    "mos_poor": "#ff9800",        # 2.6-3.1
    "mos_bad": "#f44336",         # <2.6

    # Buttons
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
        "desc": "Без шифрования",
        "color": COLORS["qop_low"],
        "bg": COLORS["qop_low_dim"],
        "icon": "🛡",
    },
    "medium": {
        "label": "MEDIUM",
        "subtitle": "SIP TLS Only",
        "desc": "Защита сигнализации",
        "color": COLORS["qop_medium"],
        "bg": COLORS["qop_medium_dim"],
        "icon": "🛡",
    },
    "high": {
        "label": "HIGH",
        "subtitle": "SIP TLS + SRTP",
        "desc": "Полное шифрование",
        "color": COLORS["qop_high"],
        "bg": COLORS["qop_high_dim"],
        "icon": "🛡",
    },
}


# ═══ УТИЛИТЫ ДЛЯ РАСЧЁТА МЕТРИК ═══════════════════════════════════════════

def calculate_mos(latency_ms: float, jitter_ms: float, loss_pct: float) -> float:
    """
    Упрощённая модель MOS (Mean Opinion Score) 1.0-5.0.
    Основана на ITU-T G.107 E-Model.
    """
    # Эффективная задержка (учитывает задержку + джиттер)
    effective_latency = latency_ms + 2 * jitter_ms + 10

    # R-factor (ITU-T G.107 simplified)
    if effective_latency < 160:
        r = 93.2 - (effective_latency / 40)
    else:
        r = 93.2 - (effective_latency - 120) / 10

    # Штраф за потери (каждый % потерь даёт -2.5 к R)
    r -= loss_pct * 2.5

    r = max(0, min(100, r))

    # R → MOS
    if r < 0:
        mos = 1.0
    elif r > 100:
        mos = 4.5
    else:
        mos = 1 + 0.035 * r + 7e-6 * r * (r - 60) * (100 - r)

    return round(max(1.0, min(5.0, mos)), 2)


def mos_color(mos: float) -> str:
    """Цвет по значению MOS."""
    if mos >= 4.0:
        return COLORS["mos_excellent"]
    elif mos >= 3.6:
        return COLORS["mos_good"]
    elif mos >= 3.1:
        return COLORS["mos_fair"]
    elif mos >= 2.6:
        return COLORS["mos_poor"]
    else:
        return COLORS["mos_bad"]


def mos_label(mos: float) -> str:
    """Текстовая оценка MOS."""
    if mos >= 4.0:
        return "Отлично"
    elif mos >= 3.6:
        return "Хорошо"
    elif mos >= 3.1:
        return "Средне"
    elif mos >= 2.6:
        return "Плохо"
    else:
        return "Ужасно"


def format_duration(seconds: int) -> str:
    """Форматирование длительности."""
    if seconds < 60:
        return f"{seconds}с"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}м {s:02d}с"
    h, m = divmod(m, 60)
    return f"{h}ч {m:02d}м"


# ═══ ВИДЖЕТЫ ═══════════════════════════════════════════════════════════════

class MetricChart(tk.Canvas):
    """Живой график временного ряда с заливкой и сеткой."""

    def __init__(self, parent, color: str, max_points: int = 50,
                 height: int = 55, show_grid: bool = True, **kwargs):
        super().__init__(parent, bg=COLORS["bg_card"], highlightthickness=0,
                         height=height, **kwargs)
        self.color = color
        self.max_points = max_points
        self.data: deque = deque(maxlen=max_points)
        self._height = height
        self._show_grid = show_grid

    def add_point(self, value: float):
        self.data.append(value)
        self._redraw()

    def _redraw(self):
        self.delete("all")
        if len(self.data) < 2:
            return

        w = self.winfo_width()
        h = self._height
        pad_x, pad_y = 6, 6

        max_val = max(self.data) * 1.15 if max(self.data) > 0 else 1

        # Сетка
        if self._show_grid:
            for i in range(1, 4):
                y = pad_y + (h - 2 * pad_y) * i / 4
                self.create_line(pad_x, y, w - pad_x, y,
                                 fill=COLORS["border"], dash=(2, 4))

        # Точки линии
        points = []
        for i, val in enumerate(self.data):
            x = pad_x + (w - 2 * pad_x) * i / (self.max_points - 1)
            y = h - pad_y - (h - 2 * pad_y) * val / max_val
            points.append((x, y))

        # Заливка
        fill_pts = list(points) + [(points[-1][0], h - pad_y), (points[0][0], h - pad_y)]
        flat = [c for p in fill_pts for c in p]
        self.create_polygon(flat, fill=self.color, outline="", stipple="gray25")

        # Линия
        flat_line = [c for p in points for c in p]
        if len(flat_line) >= 4:
            self.create_line(flat_line, fill=self.color, width=2.5, smooth=True)

        # Текущее значение
        lx, ly = points[-1]
        self.create_oval(lx - 4, ly - 4, lx + 4, ly + 4,
                         fill=self.color, outline=COLORS["text_white"], width=1.5)

        # Текущее значение надпись
        last_val = self.data[-1]
        text = f"{last_val:.1f}"
        self.create_text(w - 6, pad_y + 2, text=text, anchor="ne",
                         fill=self.color, font=("Helvetica", 9, "bold"))


class MOSGauge(tk.Canvas):
    """Круговой индикатор MOS (Mean Opinion Score)."""

    def __init__(self, parent, size: int = 80, **kwargs):
        super().__init__(parent, bg=COLORS["bg_card"], highlightthickness=0,
                         width=size, height=size, **kwargs)
        self._size = size
        self._value = 0.0
        self._draw()

    def set_value(self, mos: float):
        self._value = max(0, min(5.0, mos))
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self._size
        cx, cy = s / 2, s / 2
        radius = s / 2 - 6

        # Фоновое кольцо
        self.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                         outline=COLORS["border"], width=6)

        # Заполненная дуга (от 0 до 360 градусов на основе MOS/5)
        if self._value > 0:
            extent = -(self._value / 5.0) * 360
            color = mos_color(self._value)
            self.create_arc(cx - radius, cy - radius, cx + radius, cy + radius,
                            start=90, extent=extent,
                            outline=color, width=6, style="arc")

        # Значение в центре
        value_text = f"{self._value:.1f}" if self._value > 0 else "—"
        color = mos_color(self._value) if self._value > 0 else COLORS["text_dim"]
        self.create_text(cx, cy - 5, text=value_text,
                         fill=color, font=("Helvetica", 16, "bold"))
        self.create_text(cx, cy + 12, text="MOS",
                         fill=COLORS["text_secondary"],
                         font=("Helvetica", 8))


class QualityBar(tk.Canvas):
    """Горизонтальная полоса качества сигнала 0-100%."""

    def __init__(self, parent, width: int = 160, height: int = 8, **kwargs):
        super().__init__(parent, bg=COLORS["bg_card"], highlightthickness=0,
                         width=width, height=height, **kwargs)
        # ВАЖНО: НЕ использовать self._w / self._h — они зарезервированы tkinter
        self._bar_w = width
        self._bar_h = height
        self._value = 0
        self._color = COLORS["qop_low"]
        self._draw()

    def set_value(self, percent: float, color: str = None):
        self._value = max(0, min(100, percent))
        if color:
            self._color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        # Фон
        self.create_rectangle(0, 0, self._bar_w, self._bar_h,
                              fill=COLORS["bg_accent"], outline="")
        # Заливка
        fill_w = int(self._bar_w * self._value / 100)
        if fill_w > 0:
            self.create_rectangle(0, 0, fill_w, self._bar_h,
                                  fill=self._color, outline="")


class PulsingDot(tk.Canvas):
    """Пульсирующий индикатор живого статуса."""

    def __init__(self, parent, size: int = 14, color: str = None, **kwargs):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0,
                         width=size, height=size, **kwargs)
        self._size = size
        self._color = color or COLORS["qop_low"]
        self._phase = 0
        self._active = False
        self._draw()

    def set_color(self, color: str):
        self._color = color
        self._draw()

    def start(self):
        self._active = True
        self._animate()

    def stop(self):
        self._active = False

    def _animate(self):
        if not self._active:
            return
        self._phase = (self._phase + 1) % 60
        self._draw()
        self.after(50, self._animate)

    def _draw(self):
        self.delete("all")
        s = self._size
        cx = cy = s / 2

        if self._active:
            # Внешнее кольцо (пульсация)
            pulse_r = 3 + abs(math.sin(self._phase * 0.1)) * 3
            self.create_oval(cx - pulse_r - 2, cy - pulse_r - 2,
                             cx + pulse_r + 2, cy + pulse_r + 2,
                             outline=self._color, width=1)

        # Ядро
        self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                         fill=self._color, outline=self._color)


class StyledButton(tk.Canvas):
    """Кнопка с rounded corners и hover-эффектом."""

    def __init__(self, parent, text: str, color: str, hover_color: str,
                 command=None, width=180, height=38, icon: str = "", **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg=parent["bg"], highlightthickness=0, **kwargs)
        self._text = text
        self._icon = icon
        self._color = color
        self._hover_color = hover_color
        self._current = color
        self._command = command
        self._btn_w = width
        self._btn_h = height

        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self._command() if self._command else None)
        self._draw()

    def _set_hover(self, on: bool):
        self._current = self._hover_color if on else self._color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h, r = self._btn_w, self._btn_h, 9
        c = self._current
        self.create_arc(0, 0, 2*r, 2*r, start=90, extent=90, fill=c, outline=c)
        self.create_arc(w-2*r, 0, w, 2*r, start=0, extent=90, fill=c, outline=c)
        self.create_arc(0, h-2*r, 2*r, h, start=180, extent=90, fill=c, outline=c)
        self.create_arc(w-2*r, h-2*r, w, h, start=270, extent=90, fill=c, outline=c)
        self.create_rectangle(r, 0, w-r, h, fill=c, outline=c)
        self.create_rectangle(0, r, w, h-r, fill=c, outline=c)

        label = f"{self._icon}  {self._text}" if self._icon else self._text
        self.create_text(w // 2, h // 2, text=label,
                         fill=COLORS["text_white"],
                         font=("Helvetica", 11, "bold"))


class StatCard(tk.Frame):
    """Карточка агрегированной статистики в топ-баре."""

    def __init__(self, parent, title: str, icon: str, color: str):
        super().__init__(parent, bg=COLORS["bg_panel"],
                         highlightbackground=COLORS["border"],
                         highlightthickness=1)

        inner = tk.Frame(self, bg=COLORS["bg_panel"])
        inner.pack(padx=14, pady=10, fill="both", expand=True)

        # Верхняя строка: иконка + заголовок
        top = tk.Frame(inner, bg=COLORS["bg_panel"])
        top.pack(fill="x")

        tk.Label(top, text=icon, font=("Helvetica", 16),
                 bg=COLORS["bg_panel"], fg=color).pack(side="left")

        tk.Label(top, text=title, font=("Helvetica", 10),
                 bg=COLORS["bg_panel"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=(8, 0))

        # Значение
        self._value_label = tk.Label(inner, text="0",
                                     font=("Helvetica", 22, "bold"),
                                     bg=COLORS["bg_panel"],
                                     fg=COLORS["text_white"])
        self._value_label.pack(anchor="w", pady=(4, 0))

        # Subtitle (опционально)
        self._subtitle_label = tk.Label(inner, text="",
                                        font=("Helvetica", 9),
                                        bg=COLORS["bg_panel"],
                                        fg=COLORS["text_muted"])
        self._subtitle_label.pack(anchor="w")

    def set_value(self, value: str, subtitle: str = ""):
        self._value_label.config(text=str(value))
        self._subtitle_label.config(text=subtitle)


# ═══ ГЛАВНЫЙ ДАШБОРД ══════════════════════════════════════════════════════

class QoPDashboard:
    """Профессиональный GUI для мониторинга QoP в реальном времени."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("QoP Intelligent Recommendation System")
        self.root.configure(bg=COLORS["bg_void"])
        # Авто-подгон под разрешение экрана
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(1480, screen_w - 40)
        win_h = min(920, screen_h - 80)
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self.root.minsize(960, 600)

        title_size = 22 if screen_w >= 1400 else 18
        self.fonts = {
            "title": ("Helvetica", title_size, "bold"),
            "subtitle": ("Helvetica", 11),
            "heading": ("Helvetica", 14, "bold"),
            "body": ("Helvetica", 11),
            "body_bold": ("Helvetica", 11, "bold"),
            "small": ("Helvetica", 10),
            "small_bold": ("Helvetica", 10, "bold"),
            "tiny": ("Helvetica", 9),
            "mono": ("Menlo", 10),
            "metric_big": ("Helvetica", 26, "bold"),
            "metric_med": ("Helvetica", 18, "bold"),
            "metric_label": ("Helvetica", 9),
            "qop_level": ("Helvetica", 18, "bold"),
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
        self._start_time: Optional[float] = None

        # Aggregate stats
        self._stats = {
            "total_calls": 0,
            "active_calls": 0,
            "alerts_count": 0,
            "avg_mos": 0.0,
            "qop_distribution": {"low": 0, "medium": 0, "high": 0},
        }

        # AMI settings
        self._ami_host = tk.StringVar(value="192.168.0.215")
        self._ami_port = tk.StringVar(value="5038")
        self._ami_user = tk.StringVar(value="monitor")
        self._ami_pass = tk.StringVar(value="monitor_secret")

        self._build_ui()
        self._start_clock()

    # ─── UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_stats_bar()

        content = tk.Frame(self.root, bg=COLORS["bg_void"])
        content.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        # Левая часть — карточки вызовов
        left = tk.Frame(content, bg=COLORS["bg_void"])
        left.pack(side="left", fill="both", expand=True)

        # Заголовок секции
        section_header = tk.Frame(left, bg=COLORS["bg_void"])
        section_header.pack(fill="x", pady=(0, 8))

        tk.Label(section_header, text="📞  Активные вызовы",
                 font=self.fonts["heading"], bg=COLORS["bg_void"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self._no_calls_label = tk.Label(section_header, text="нет активных вызовов",
                                        font=self.fonts["small"],
                                        bg=COLORS["bg_void"],
                                        fg=COLORS["text_dim"])
        self._no_calls_label.pack(side="right")

        # Scrollable container for call cards
        canvas_frame = tk.Frame(left, bg=COLORS["bg_void"])
        canvas_frame.pack(fill="both", expand=True)

        self._cards_canvas = tk.Canvas(canvas_frame, bg=COLORS["bg_void"],
                                       highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical",
                                  command=self._cards_canvas.yview)
        self._calls_container = tk.Frame(self._cards_canvas, bg=COLORS["bg_void"])

        self._calls_container.bind("<Configure>",
                                   lambda e: self._cards_canvas.configure(
                                       scrollregion=self._cards_canvas.bbox("all")))

        self._cards_canvas.create_window((0, 0), window=self._calls_container,
                                         anchor="nw", tags="cards")
        self._cards_canvas.configure(yscrollcommand=scrollbar.set)

        self._cards_canvas.bind("<Configure>", self._on_canvas_resize)

        self._cards_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Правая часть — алерты + контролы (адаптивная ширина)
        right_w = min(420, max(300, (self.root.winfo_screenwidth() - 40) // 4))
        right = tk.Frame(content, bg=COLORS["bg_void"], width=right_w)
        right.pack(side="right", fill="y", padx=(16, 0))
        right.pack_propagate(False)

        self._build_alerts_panel(right)
        self._build_controls_panel(right)

    def _on_canvas_resize(self, event):
        self._cards_canvas.itemconfig("cards", width=event.width)

    def _build_header(self):
        header = tk.Frame(self.root, bg=COLORS["bg_dark"], height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        inner = tk.Frame(header, bg=COLORS["bg_dark"])
        inner.pack(fill="both", expand=True, padx=24, pady=10)

        # Левая часть — логотип + название
        left = tk.Frame(inner, bg=COLORS["bg_dark"])
        left.pack(side="left", fill="y")

        # Иконка-логотип
        icon_frame = tk.Frame(left, bg=COLORS["accent_blue"], width=54, height=54)
        icon_frame.pack(side="left", padx=(0, 16))
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text="⚡", font=("Helvetica", 28),
                 bg=COLORS["accent_blue"], fg=COLORS["text_white"]
                 ).pack(expand=True)

        # Название
        tf = tk.Frame(left, bg=COLORS["bg_dark"])
        tf.pack(side="left", fill="y")

        tk.Label(tf, text="QoP Recommendation System",
                 font=self.fonts["title"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_white"]).pack(anchor="w")

        subtitle_frame = tk.Frame(tf, bg=COLORS["bg_dark"])
        subtitle_frame.pack(anchor="w")

        tk.Label(subtitle_frame, text="Intelligent VoIP Security Advisor",
                 font=self.fonts["subtitle"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="left")

        tk.Label(subtitle_frame, text="  •  ",
                 font=self.fonts["subtitle"], bg=COLORS["bg_dark"],
                 fg=COLORS["text_dim"]).pack(side="left")

        tk.Label(subtitle_frame, text="XGBoost + Neural Network",
                 font=self.fonts["subtitle"], bg=COLORS["bg_dark"],
                 fg=COLORS["accent_cyan"]).pack(side="left")

        # Правая часть — статус + время
        right = tk.Frame(inner, bg=COLORS["bg_dark"])
        right.pack(side="right", fill="y")

        # Таймер работы
        self._uptime_label = tk.Label(right, text="00:00:00",
                                      font=("Menlo", 14, "bold"),
                                      bg=COLORS["bg_dark"],
                                      fg=COLORS["text_white"])
        self._uptime_label.pack(side="right", padx=(0, 16))

        # Статус-индикатор
        status_frame = tk.Frame(right, bg=COLORS["bg_dark"])
        status_frame.pack(side="right", padx=(0, 16))

        self._status_dot = PulsingDot(status_frame, size=14,
                                      color=COLORS["text_dim"])
        self._status_dot.pack(side="left", padx=(0, 8))

        tk.Label(status_frame, textvariable=self._status_var,
                 font=self.fonts["small_bold"],
                 bg=COLORS["bg_dark"],
                 fg=COLORS["text_secondary"]).pack(side="left")

        # Разделительная линия
        tk.Frame(self.root, bg=COLORS["accent_blue"], height=2).pack(fill="x")

    def _build_stats_bar(self):
        bar = tk.Frame(self.root, bg=COLORS["bg_void"])
        bar.pack(fill="x", padx=16, pady=(16, 12))

        # 4 карточки статистики
        self._stat_total = StatCard(bar, "Всего вызовов", "📊", COLORS["accent_blue"])
        self._stat_total.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._stat_active = StatCard(bar, "Активные", "🟢", COLORS["qop_low"])
        self._stat_active.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._stat_mos = StatCard(bar, "Средний MOS", "⭐", COLORS["mos_excellent"])
        self._stat_mos.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._stat_alerts = StatCard(bar, "Алертов", "🔔", COLORS["alert_warning"])
        self._stat_alerts.pack(side="left", fill="x", expand=True)

    def _build_alerts_panel(self, parent):
        hdr = tk.Frame(parent, bg=COLORS["bg_void"])
        hdr.pack(fill="x", pady=(0, 8))

        tk.Label(hdr, text="🔔  Алерты и события",
                 font=self.fonts["heading"], bg=COLORS["bg_void"],
                 fg=COLORS["text_primary"]).pack(side="left")

        self._alert_count_badge = tk.Label(hdr, text="0",
                                           font=self.fonts["small_bold"],
                                           bg=COLORS["alert_warning"],
                                           fg=COLORS["text_white"],
                                           padx=10, pady=3)
        self._alert_count_badge.pack(side="right")

        frame = tk.Frame(parent, bg=COLORS["bg_panel"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
        frame.pack(fill="both", expand=True, pady=(0, 16))

        self._alerts_canvas = tk.Canvas(frame, bg=COLORS["bg_panel"],
                                        highlightthickness=0)
        self._alerts_inner = tk.Frame(self._alerts_canvas, bg=COLORS["bg_panel"])
        self._alerts_canvas.pack(fill="both", expand=True, padx=3, pady=3)
        self._alerts_canvas.create_window((0, 0), window=self._alerts_inner,
                                          anchor="nw")
        self._alerts_inner.bind("<Configure>",
                                lambda e: self._alerts_canvas.configure(
                                    scrollregion=self._alerts_canvas.bbox("all")))

        self._alerts_placeholder = tk.Label(
            self._alerts_inner, text="💤  Нет активных алертов",
            font=self.fonts["small"], bg=COLORS["bg_panel"],
            fg=COLORS["text_dim"], pady=40)
        self._alerts_placeholder.pack()

    def _build_controls_panel(self, parent):
        tk.Label(parent, text="⚙  Управление",
                 font=self.fonts["heading"], bg=COLORS["bg_void"],
                 fg=COLORS["text_primary"]).pack(anchor="w", pady=(0, 10))

        ctrl = tk.Frame(parent, bg=COLORS["bg_panel"],
                        highlightbackground=COLORS["border"], highlightthickness=1)
        ctrl.pack(fill="x")
        ci = tk.Frame(ctrl, bg=COLORS["bg_panel"])
        ci.pack(fill="x", padx=16, pady=14)

        # Режим работы
        tk.Label(ci, text="РЕЖИМ РАБОТЫ",
                 font=self.fonts["tiny"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_muted"]).pack(anchor="w")

        self._mode_var = tk.StringVar(value="live")
        modes = tk.Frame(ci, bg=COLORS["bg_panel"])
        modes.pack(fill="x", pady=(4, 10))

        for val, label in [("demo", "Demo (симулятор)"),
                           ("live", "Live (Asterisk AMI)")]:
            tk.Radiobutton(modes, text=label, variable=self._mode_var,
                           value=val, font=self.fonts["body"],
                           bg=COLORS["bg_panel"], fg=COLORS["text_primary"],
                           selectcolor=COLORS["bg_card"],
                           activebackground=COLORS["bg_panel"],
                           activeforeground=COLORS["text_white"],
                           command=self._on_mode_change).pack(anchor="w")

        # AMI settings
        self._ami_frame = tk.Frame(ci, bg=COLORS["bg_panel"])
        self._on_mode_change()

        tk.Label(self._ami_frame, text="ПАРАМЕТРЫ AMI",
                 font=self.fonts["tiny"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_muted"]).pack(anchor="w", pady=(4, 4))

        for label_text, var in [("Host", self._ami_host), ("Port", self._ami_port),
                                 ("User", self._ami_user), ("Password", self._ami_pass)]:
            row = tk.Frame(self._ami_frame, bg=COLORS["bg_panel"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label_text, font=self.fonts["small"],
                     bg=COLORS["bg_panel"], fg=COLORS["text_secondary"],
                     width=9, anchor="w").pack(side="left")
            tk.Entry(row, textvariable=var, font=self.fonts["small"],
                     bg=COLORS["bg_input"], fg=COLORS["text_primary"],
                     insertbackground=COLORS["text_white"],
                     highlightbackground=COLORS["border"],
                     highlightthickness=1, relief="flat").pack(side="left", fill="x", expand=True)

        tk.Frame(ci, bg=COLORS["border"], height=1).pack(fill="x", pady=12)

        # Запуск
        self._btn_start = StyledButton(
            ci, "ЗАПУСТИТЬ", COLORS["btn_success"], COLORS["btn_success_hover"],
            command=self._on_start, width=220, height=42, icon="▶")
        self._btn_start.pack(pady=(0, 8))

        tk.Frame(ci, bg=COLORS["border"], height=1).pack(fill="x", pady=12)

        tk.Label(ci, text="СЦЕНАРИИ АНОМАЛИЙ",
                 font=self.fonts["tiny"], bg=COLORS["bg_panel"],
                 fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))

        for text, color, hover, cmd, icon in [
            ("Деградация 4G", COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject("4g"), "⚠"),
            ("Перегрузка WiFi", COLORS["btn_danger"], COLORS["btn_danger_hover"],
             lambda: self._inject("wifi"), "⚠"),
            ("Снять аномалии", COLORS["btn_neutral"], COLORS["btn_neutral_hover"],
             self._clear_anomalies, "✓"),
        ]:
            StyledButton(ci, text, color, hover, command=cmd,
                         width=220, height=34, icon=icon).pack(pady=3)

    def _on_mode_change(self):
        if self._mode_var.get() == "live":
            self._ami_frame.pack(fill="x", pady=(4, 0))
        else:
            self._ami_frame.pack_forget()

    # ─── Clock & Status ───────────────────────────────────────────────────

    def _start_clock(self):
        self._update_clock()

    def _update_clock(self):
        if self._start_time:
            elapsed = int(time.time() - self._start_time)
            h = elapsed // 3600
            m = (elapsed % 3600) // 60
            s = elapsed % 60
            self._uptime_label.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.root.after(1000, self._update_clock)

    # ─── Call Cards ───────────────────────────────────────────────────────

    def _create_call_card(self, channel_id: str, caller_ip: str,
                          is_external: bool):
        card = tk.Frame(self._calls_container, bg=COLORS["bg_card"],
                        highlightbackground=COLORS["border"], highlightthickness=2)
        card.pack(fill="x", pady=(0, 12), padx=2)

        # ═══ Верхняя строка: статус + канал + IP + тип + QoP badge ═══
        top = tk.Frame(card, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=18, pady=(14, 6))

        # Живой индикатор
        live_dot = PulsingDot(top, size=12, color=COLORS["qop_low"])
        live_dot.pack(side="left", padx=(0, 10))
        live_dot.start()

        # Название канала
        tk.Label(top, text=f"📞 {channel_id}", font=self.fonts["body_bold"],
                 bg=COLORS["bg_card"], fg=COLORS["text_white"]).pack(side="left")

        # Тип сети
        net_text = "WAN" if is_external else "LAN"
        net_color = COLORS["qop_high"] if is_external else COLORS["qop_low"]
        net_bg = COLORS["qop_high_dim"] if is_external else COLORS["qop_low_dim"]
        tk.Label(top, text=f"  {net_text}  ", font=self.fonts["small_bold"],
                 bg=net_bg, fg=net_color).pack(side="left", padx=10)

        # IP
        tk.Label(top, text=caller_ip, font=self.fonts["mono"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left")

        # Duration
        dur_label = tk.Label(top, text="00:00", font=self.fonts["mono"],
                             bg=COLORS["bg_card"], fg=COLORS["accent_cyan"])
        dur_label.pack(side="left", padx=(14, 0))

        # QoP badge справа
        qop_frame = tk.Frame(top, bg=COLORS["bg_card"])
        qop_frame.pack(side="right")

        qop_label = tk.Label(qop_frame, text="АНАЛИЗ...", font=self.fonts["qop_level"],
                             bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        qop_label.pack(side="left")

        qop_sub = tk.Label(qop_frame, text="", font=self.fonts["tiny"],
                           bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        qop_sub.pack(side="left", padx=(10, 0))

        # ═══ Средняя часть: MOS gauge + метрики + qual bars ═══
        middle = tk.Frame(card, bg=COLORS["bg_card"])
        middle.pack(fill="x", padx=18, pady=(4, 4))

        # MOS gauge слева
        mos_frame = tk.Frame(middle, bg=COLORS["bg_card"])
        mos_frame.pack(side="left", padx=(0, 16))
        mos_gauge = MOSGauge(mos_frame, size=86)
        mos_gauge.pack()
        tk.Label(mos_frame, text="Quality Score", font=self.fonts["tiny"],
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]
                 ).pack(pady=(2, 0))
        mos_quality_label = tk.Label(mos_frame, text="—", font=self.fonts["small_bold"],
                                     bg=COLORS["bg_card"], fg=COLORS["text_dim"])
        mos_quality_label.pack()

        # Метрики в 2 колонки
        metrics_frame = tk.Frame(middle, bg=COLORS["bg_card"])
        metrics_frame.pack(side="left", fill="both", expand=True)

        # Первая строка: latency, jitter, loss
        row1 = tk.Frame(metrics_frame, bg=COLORS["bg_card"])
        row1.pack(fill="x")

        metric_widgets = {}
        metrics_info = [
            ("latency", "Задержка", "мс", COLORS["chart_latency"], "⏱"),
            ("jitter", "Джиттер", "мс", COLORS["chart_jitter"], "⚡"),
            ("loss", "Потери", "%", COLORS["chart_loss"], "📉"),
        ]

        for key, lbl, unit, color, icon in metrics_info:
            col = tk.Frame(row1, bg=COLORS["bg_card"])
            col.pack(side="left", expand=True, fill="x", padx=4)

            # Header
            h = tk.Frame(col, bg=COLORS["bg_card"])
            h.pack(anchor="w")
            tk.Label(h, text=icon, font=("Helvetica", 10),
                     bg=COLORS["bg_card"], fg=color).pack(side="left")
            tk.Label(h, text=lbl, font=self.fonts["metric_label"],
                     bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                     ).pack(side="left", padx=(4, 0))

            # Value
            vf = tk.Frame(col, bg=COLORS["bg_card"])
            vf.pack(anchor="w", pady=(1, 0))
            val = tk.Label(vf, text="—", font=self.fonts["metric_med"],
                           bg=COLORS["bg_card"], fg=color)
            val.pack(side="left")
            tk.Label(vf, text=f" {unit}", font=self.fonts["tiny"],
                     bg=COLORS["bg_card"], fg=COLORS["text_dim"]
                     ).pack(side="left", anchor="s", pady=3)
            metric_widgets[key] = val

        # Вторая строка: confidence, RTT, quality bar
        row2 = tk.Frame(metrics_frame, bg=COLORS["bg_card"])
        row2.pack(fill="x", pady=(4, 0))

        # Confidence
        conf_col = tk.Frame(row2, bg=COLORS["bg_card"])
        conf_col.pack(side="left", expand=True, fill="x", padx=4)

        h = tk.Frame(conf_col, bg=COLORS["bg_card"])
        h.pack(anchor="w")
        tk.Label(h, text="🎯", font=("Helvetica", 10),
                 bg=COLORS["bg_card"], fg=COLORS["accent_cyan"]).pack(side="left")
        tk.Label(h, text="Уверенность", font=self.fonts["metric_label"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=(4, 0))

        conf_val = tk.Label(conf_col, text="—", font=self.fonts["metric_med"],
                            bg=COLORS["bg_card"], fg=COLORS["accent_cyan"])
        conf_val.pack(anchor="w", pady=(1, 0))
        metric_widgets["confidence"] = conf_val

        # Quality signal bar
        qb_col = tk.Frame(row2, bg=COLORS["bg_card"])
        qb_col.pack(side="left", expand=True, fill="x", padx=4)

        h = tk.Frame(qb_col, bg=COLORS["bg_card"])
        h.pack(anchor="w")
        tk.Label(h, text="📶", font=("Helvetica", 10),
                 bg=COLORS["bg_card"], fg=COLORS["qop_low"]).pack(side="left")
        tk.Label(h, text="Сигнал", font=self.fonts["metric_label"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"]
                 ).pack(side="left", padx=(4, 0))

        quality_bar = QualityBar(qb_col, width=160, height=10)
        quality_bar.pack(anchor="w", pady=(6, 0))
        quality_val = tk.Label(qb_col, text="—", font=self.fonts["tiny"],
                               bg=COLORS["bg_card"], fg=COLORS["text_secondary"])
        quality_val.pack(anchor="w")

        # ═══ Графики ═══
        charts_section = tk.Frame(card, bg=COLORS["bg_card"])
        charts_section.pack(fill="x", padx=18, pady=(8, 14))

        chart_label_frame = tk.Frame(charts_section, bg=COLORS["bg_card"])
        chart_label_frame.pack(fill="x", pady=(0, 4))
        tk.Label(chart_label_frame, text="Метрики в реальном времени",
                 font=self.fonts["tiny"], bg=COLORS["bg_card"],
                 fg=COLORS["text_muted"]).pack(anchor="w")

        charts_frame = tk.Frame(charts_section, bg=COLORS["bg_card"])
        charts_frame.pack(fill="x")

        charts = {}
        for key, color in [("latency", COLORS["chart_latency"]),
                           ("jitter", COLORS["chart_jitter"]),
                           ("loss", COLORS["chart_loss"])]:
            chart = MetricChart(charts_frame, color=color, max_points=50, height=55)
            chart.pack(side="left", expand=True, fill="x", padx=2)
            charts[key] = chart

        # Сохраняем ссылки
        self._call_cards[channel_id] = {
            "frame": card,
            "qop_label": qop_label,
            "qop_sub": qop_sub,
            "metrics": metric_widgets,
            "charts": charts,
            "mos_gauge": mos_gauge,
            "mos_quality_label": mos_quality_label,
            "quality_bar": quality_bar,
            "quality_val": quality_val,
            "dur_label": dur_label,
            "live_dot": live_dot,
            "start_time": time.time(),
        }

        # Скрываем "нет активных"
        self._no_calls_label.config(text="")
        self._stats["total_calls"] += 1
        self._stats["active_calls"] = len(self._call_cards)
        self._update_stats_bar()

    def _update_call_card(self, channel_id: str, metrics: dict,
                          prediction: Optional[dict] = None):
        if channel_id not in self._call_cards:
            return
        card = self._call_cards[channel_id]

        lat = metrics.get("latency_ms", 0)
        jit = metrics.get("jitter_ms", 0)
        loss = metrics.get("packet_loss_pct", 0)

        # Обновить значения
        card["metrics"]["latency"].config(text=f"{lat:.0f}")
        card["metrics"]["jitter"].config(text=f"{jit:.1f}")
        card["metrics"]["loss"].config(text=f"{loss:.2f}")

        # Графики
        card["charts"]["latency"].add_point(lat)
        card["charts"]["jitter"].add_point(jit)
        card["charts"]["loss"].add_point(loss)

        # MOS
        mos = calculate_mos(lat, jit, loss)
        card["mos_gauge"].set_value(mos)
        card["mos_quality_label"].config(text=mos_label(mos), fg=mos_color(mos))

        # Quality bar (100% - нормализованная метрика)
        quality_percent = max(0, min(100, (mos / 5.0) * 100))
        card["quality_bar"].set_value(quality_percent, mos_color(mos))
        card["quality_val"].config(text=f"{quality_percent:.0f}% • {mos:.1f} MOS")

        # Duration
        elapsed = int(time.time() - card["start_time"])
        m, s = divmod(elapsed, 60)
        card["dur_label"].config(text=f"{m:02d}:{s:02d}")

        # QoP
        if prediction:
            level = prediction["level_name"]
            conf = prediction["confidence"]
            cfg = QOP_CONFIG[level]

            card["qop_label"].config(text=cfg["label"], fg=cfg["color"])
            card["qop_sub"].config(text=cfg["subtitle"], fg=cfg["color"])
            card["metrics"]["confidence"].config(text=f"{conf:.0%}")
            card["frame"].config(highlightbackground=cfg["color"])
            card["live_dot"].set_color(cfg["color"])

            # Обновить stat — распределение QoP
            self._stats["qop_distribution"][level] = \
                self._stats["qop_distribution"].get(level, 0) + 1

        # Средний MOS
        all_mos = []
        for c in self._call_cards.values():
            val = c["mos_gauge"]._value
            if val > 0:
                all_mos.append(val)
        if all_mos:
            self._stats["avg_mos"] = sum(all_mos) / len(all_mos)

        self._update_stats_bar()

    def _remove_call_card(self, channel_id: str):
        if channel_id in self._call_cards:
            self._call_cards[channel_id]["frame"].destroy()
            del self._call_cards[channel_id]
            self._stats["active_calls"] = len(self._call_cards)
            if not self._call_cards:
                self._no_calls_label.config(text="нет активных вызовов")
            self._update_stats_bar()

    def _update_stats_bar(self):
        s = self._stats
        self._stat_total.set_value(str(s["total_calls"]), "за сессию")
        self._stat_active.set_value(str(s["active_calls"]), "сейчас")

        mos_val = s["avg_mos"]
        mos_text = f"{mos_val:.2f}" if mos_val > 0 else "—"
        mos_sub = mos_label(mos_val) if mos_val > 0 else "нет данных"
        self._stat_mos.set_value(mos_text, mos_sub)

        self._stat_alerts.set_value(str(s["alerts_count"]), "всего")

    # ─── Alerts ───────────────────────────────────────────────────────────

    def _add_alert(self, severity: str, title: str, message: str):
        self._alerts_placeholder.pack_forget()

        color_map = {"info": COLORS["alert_info"],
                     "warning": COLORS["alert_warning"],
                     "critical": COLORS["alert_critical"],
                     "success": COLORS["alert_success"]}
        icon_map = {"info": "ℹ", "warning": "⚠", "critical": "🚨", "success": "✓"}
        color = color_map.get(severity, COLORS["text_secondary"])
        icon = icon_map.get(severity, "•")

        af = tk.Frame(self._alerts_inner, bg=COLORS["bg_card"],
                      highlightbackground=color, highlightthickness=2)
        af.pack(fill="x", padx=4, pady=4)

        inner = tk.Frame(af, bg=COLORS["bg_card"])
        inner.pack(fill="x", padx=10, pady=8)

        top = tk.Frame(inner, bg=COLORS["bg_card"])
        top.pack(fill="x")

        tk.Label(top, text=icon, font=("Helvetica", 14),
                 bg=COLORS["bg_card"], fg=color).pack(side="left")
        tk.Label(top, text=f" [{severity.upper()}] ", font=self.fonts["tiny"],
                 bg=COLORS["bg_card"], fg=color).pack(side="left")
        tk.Label(top, text=time.strftime("%H:%M:%S"), font=self.fonts["tiny"],
                 bg=COLORS["bg_card"], fg=COLORS["text_dim"]).pack(side="right")

        tk.Label(inner, text=title, font=self.fonts["body_bold"],
                 bg=COLORS["bg_card"], fg=COLORS["text_primary"],
                 anchor="w", wraplength=320, justify="left"
                 ).pack(fill="x", pady=(4, 2))

        tk.Label(inner, text=message, font=self.fonts["small"],
                 bg=COLORS["bg_card"], fg=COLORS["text_secondary"],
                 anchor="w", wraplength=320, justify="left"
                 ).pack(fill="x")

        self._alerts_widgets.append(af)
        if len(self._alerts_widgets) > 30:
            old = self._alerts_widgets.pop(0)
            old.destroy()

        self._stats["alerts_count"] += 1
        self._alert_count_badge.config(text=str(self._stats["alerts_count"]))
        self._update_stats_bar()

        self._alerts_canvas.update_idletasks()
        self._alerts_canvas.yview_moveto(1.0)

    # ─── Start ────────────────────────────────────────────────────────────

    def _on_start(self):
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._status_dot.start()

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
                f"✘ Ошибка: {e}", COLORS["alert_critical"]))

    def _set_status(self, text: str, color: str):
        self._status_var.set(text)
        self._status_dot.set_color(color)

    # ─── Pipeline ─────────────────────────────────────────────────────────

    def _handle_metrics_sync(self, channel_id: str, caller_ip: str,
                             is_external: bool, features: dict):
        """
        Синхронная обработка метрик в главном потоке tkinter.
        Вызывается через root.after из async callback.
        """
        # Создать карточку если её ещё нет
        if channel_id not in self._call_cards:
            self._create_call_card(channel_id, caller_ip, is_external)

        # ML-предсказание (быстрое, ~1ms)
        try:
            prediction = self._predictor.predict(features)
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return

        # Рекомендация
        rec = self._rec_engine.process_prediction(
            channel_id=channel_id,
            prediction=prediction,
            metrics={**features, "caller_ip": caller_ip},
        )

        # Обновление карточки — прямо сейчас, т.к. уже в главном потоке
        self._update_call_card(channel_id, features, prediction)

        # Алерт при смене уровня
        if rec.is_change:
            level_order = {"low": 0, "medium": 1, "high": 2}
            going_down = level_order.get(rec.level, 0) < level_order.get(rec.previous_level, 0)

            if going_down:
                sev = "critical" if rec.level == "low" else "warning"
                title = "Деградация канала — понижение профиля QoP"
            else:
                sev = "info"
                title = "Улучшение канала — повышение профиля QoP"

            msg = (f"{channel_id}: {rec.previous_level.upper()} → {rec.level.upper()}\n"
                   f"Задержка: {rec.latency_ms:.0f} мс  •  "
                   f"Джиттер: {rec.jitter_ms:.1f} мс  •  "
                   f"Потери: {rec.packet_loss_pct:.2f}%")
            self._add_alert(sev, title, msg)

    def _process_tick(self, channel_id: str, caller_ip: str,
                      is_external: bool, features: dict):
        """Для Demo режима — запуск из async потока."""
        prediction = self._predictor.predict(features)
        rec = self._rec_engine.process_prediction(
            channel_id=channel_id,
            prediction=prediction,
            metrics={**features, "caller_ip": caller_ip},
        )
        self.root.after(0, lambda: self._update_call_card(
            channel_id, features, prediction))

        if rec.is_change:
            level_order = {"low": 0, "medium": 1, "high": 2}
            going_down = level_order.get(rec.level, 0) < level_order.get(rec.previous_level, 0)

            if going_down:
                sev = "critical" if rec.level == "low" else "warning"
                title = "Деградация канала — понижение профиля QoP"
            else:
                sev = "info"
                title = "Улучшение канала — повышение профиля QoP"

            msg = (f"{channel_id}: {rec.previous_level.upper()} → {rec.level.upper()}\n"
                   f"Задержка: {rec.latency_ms:.0f} мс  •  "
                   f"Джиттер: {rec.jitter_ms:.1f} мс  •  "
                   f"Потери: {rec.packet_loss_pct:.2f}%")
            self.root.after(0, lambda s=sev, t=title, m=msg: self._add_alert(s, t, m))

    # ─── Demo Mode ────────────────────────────────────────────────────────

    async def _run_demo(self):
        self.root.after(0, lambda: self._set_status(
            "Загрузка ML-моделей...", COLORS["accent_blue"]))

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

        await asyncio.sleep(0.5)
        self.root.after(0, lambda: self._set_status(
            "Мониторинг активен • Demo • 3 вызова", COLORS["qop_low"]))

        while self._running:
            for ch_id, call in list(self._simulator.active_calls.items()):
                metrics_obj = self._simulator._generate_metrics(call)
                features = metrics_obj.to_feature_vector()
                self._process_tick(ch_id, metrics_obj.caller_ip,
                                   metrics_obj.is_external, features)
            await asyncio.sleep(2.0)

    # ─── Live Mode ────────────────────────────────────────────────────────

    async def _run_live(self):
        self.root.after(0, lambda: self._set_status(
            "Подключение к Asterisk AMI...", COLORS["accent_blue"]))

        from ml_agent.inference import QoPPredictor
        from recommendation.engine import QoPRecommendationEngine
        from monitoring.ami_collector import AMICollector, CallMetrics

        self._predictor = QoPPredictor()
        self._predictor.load()
        self._rec_engine = QoPRecommendationEngine()

        import yaml, os
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        config["asterisk"]["host"] = self._ami_host.get()
        config["asterisk"]["ami_port"] = int(self._ami_port.get())
        config["asterisk"]["ami_username"] = self._ami_user.get()
        config["asterisk"]["ami_password"] = self._ami_pass.get()

        tmp_cfg = "config_live_tmp.yaml"
        with open(tmp_cfg, "w") as f:
            yaml.dump(config, f)

        collector = AMICollector(tmp_cfg)

        async def on_metrics(metrics: CallMetrics):
            """Передаём метрики в главный поток tkinter одним callback."""
            ch_id = metrics.channel_id
            features = metrics.to_feature_vector()
            caller_ip = metrics.caller_ip
            is_ext = metrics.is_external

            logger.info(f"GUI получил метрики: {ch_id} lat={metrics.latency_ms:.1f} "
                        f"jit={metrics.jitter_ms:.1f} loss={metrics.packet_loss_pct:.2f}")

            # Всё выполняется в главном потоке tkinter
            # (избегаем race conditions с self._call_cards)
            self.root.after(0, lambda:
                self._handle_metrics_sync(ch_id, caller_ip, is_ext, features))

        def on_hangup(channel_id: str):
            """Удалить карточку вызова при завершении канала."""
            logger.info(f"GUI: удаление канала {channel_id}")
            self.root.after(0, lambda: self._remove_call_card(channel_id))

        collector.on_metrics(on_metrics)
        collector.on_hangup(on_hangup)

        try:
            await collector.connect()
            collector._running = True
            self.root.after(0, lambda: self._set_status(
                f"Подключено к {self._ami_host.get()}:{self._ami_port.get()} • Live",
                COLORS["qop_low"]))
            await asyncio.gather(
                collector._event_loop(),
                collector._aggregation_loop(),
            )
        except Exception as e:
            self.root.after(0, lambda: self._set_status(
                f"Ошибка AMI: {e}", COLORS["alert_critical"]))
            self.root.after(0, lambda: self._add_alert(
                "critical", "Ошибка подключения к AMI", str(e)))
        finally:
            if os.path.exists(tmp_cfg):
                os.remove(tmp_cfg)

    # ─── Anomaly Controls ─────────────────────────────────────────────────

    def _inject(self, scenario: str):
        if not self._simulator or not self._channels:
            self._add_alert("warning", "Недоступно в Live режиме",
                            "Сценарии аномалий работают только в Demo режиме. "
                            "Для Live используйте 'sudo tc qdisc ...' на сервере.")
            return
        if scenario == "4g":
            ch = self._channels.get("wan_4g_mobile")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=150,
                                               jitter_add=25, loss_add=5)
                self._set_status("⚠ Аномалия: деградация 4G",
                                 COLORS["alert_warning"])
        elif scenario == "wifi":
            ch = self._channels.get("wan_wifi_public")
            if ch:
                self._simulator.inject_anomaly(ch, latency_add=200,
                                               jitter_add=40, loss_add=8)
                self._set_status("⚠ Аномалия: перегрузка WiFi",
                                 COLORS["alert_critical"])

    def _clear_anomalies(self):
        if not self._simulator or not self._channels:
            return
        for ch in self._channels.values():
            self._simulator.clear_anomaly(ch)
        self._set_status("✓ Аномалии сняты", COLORS["qop_low"])

    # ─── Run ──────────────────────────────────────────────────────────────

    def run(self):
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self._running = False
        if self._loop:
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except Exception:
                pass
        self.root.destroy()


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    app = QoPDashboard()
    app.run()


if __name__ == "__main__":
    main()
