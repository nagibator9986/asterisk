"""
Консольный дашборд администратора — отображение в реальном времени.

Использует библиотеку Rich для красивого форматирования в терминале.
Показывает: активные вызовы, метрики, рекомендации QoP и алерты.
"""

import time
import logging
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.live import Live
from rich import box

from recommendation.engine import Recommendation, Alert

logger = logging.getLogger(__name__)


# Цветовая схема для уровней QoP
LEVEL_COLORS = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
}

LEVEL_ICONS = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔴",
}

SEVERITY_COLORS = {
    "info": "blue",
    "warning": "yellow",
    "critical": "red",
}


class ConsoleDashboard:
    """
    Rich-дашборд для вывода телеметрии и рекомендаций.

    Поддерживает два режима:
      - Live: обновление в реальном времени (Rich Live)
      - Log: построчный вывод (для логов и нон-интерактивного режима)
    """

    def __init__(self, live_mode: bool = True):
        self.console = Console()
        self.live_mode = live_mode

        # Текущее состояние для отображения
        self._active_channels: dict[str, dict] = {}
        self._recommendations: dict[str, Recommendation] = {}
        self._alerts: list[Alert] = []
        self._max_alerts_display = 10

        self._live: Optional[Live] = None

    def update_channel(self, channel_id: str, metrics: dict,
                       recommendation: Optional[Recommendation] = None):
        """Обновить информацию о канале."""
        self._active_channels[channel_id] = {
            "metrics": metrics,
            "timestamp": time.time(),
        }
        if recommendation:
            self._recommendations[channel_id] = recommendation

    def add_alert(self, alert: Alert):
        """Добавить алерт."""
        self._alerts.append(alert)
        if len(self._alerts) > self._max_alerts_display:
            self._alerts = self._alerts[-self._max_alerts_display:]

        if not self.live_mode:
            self._print_alert(alert)

    def remove_channel(self, channel_id: str):
        """Удалить канал из дашборда."""
        self._active_channels.pop(channel_id, None)
        self._recommendations.pop(channel_id, None)

    def render(self) -> Table:
        """Сгенерировать полный рендер дашборда."""
        # Основная таблица активных вызовов
        table = Table(
            title="📡 Активные вызовы — Мониторинг QoP",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold cyan",
        )

        table.add_column("Канал", style="bold", width=20)
        table.add_column("IP", width=16)
        table.add_column("Тип", width=5)
        table.add_column("Задержка", justify="right", width=10)
        table.add_column("Джиттер", justify="right", width=10)
        table.add_column("Потери", justify="right", width=8)
        table.add_column("QoP", justify="center", width=20)
        table.add_column("Уверенность", justify="right", width=12)

        for channel_id, data in self._active_channels.items():
            metrics = data["metrics"]
            rec = self._recommendations.get(channel_id)

            # Тип подключения
            is_ext = metrics.get("is_external", False)
            net_type = Text("WAN", style="red") if is_ext else Text("LAN", style="green")

            # Метрики с цветовой индикацией
            latency = metrics.get("latency_ms", 0)
            jitter = metrics.get("jitter_ms", 0)
            loss = metrics.get("packet_loss_pct", 0)

            lat_style = "green" if latency < 50 else ("yellow" if latency < 150 else "red")
            jit_style = "green" if jitter < 10 else ("yellow" if jitter < 30 else "red")
            loss_style = "green" if loss < 1 else ("yellow" if loss < 5 else "red")

            # QoP уровень
            if rec:
                level = rec.level
                qop_text = Text(
                    f"{LEVEL_ICONS.get(level, '')} {rec.level_display}",
                    style=f"bold {LEVEL_COLORS.get(level, 'white')}"
                )
                conf_text = Text(f"{rec.confidence:.1%}", style="bold")
            else:
                qop_text = Text("⏳ Анализ...", style="dim")
                conf_text = Text("—", style="dim")

            table.add_row(
                channel_id,
                metrics.get("caller_ip", "—"),
                net_type,
                Text(f"{latency:.0f} мс", style=lat_style),
                Text(f"{jitter:.1f} мс", style=jit_style),
                Text(f"{loss:.2f}%", style=loss_style),
                qop_text,
                conf_text,
            )

        if not self._active_channels:
            table.add_row(
                "—", "—", Text("—"), Text("—"), Text("—"), Text("—"),
                Text("Нет активных вызовов", style="dim"), Text("—")
            )

        return table

    def render_alerts(self) -> Panel:
        """Рендер панели алертов."""
        if not self._alerts:
            return Panel(
                Text("Нет активных алертов", style="dim"),
                title="🔔 Алерты",
                border_style="dim",
            )

        texts = []
        for alert in reversed(self._alerts[-5:]):
            color = SEVERITY_COLORS.get(alert.severity, "white")
            ts = time.strftime("%H:%M:%S", time.localtime(alert.timestamp))
            severity_label = alert.severity.upper()
            texts.append(
                Text.assemble(
                    (f"[{ts}] ", "dim"),
                    (f"[{severity_label}] ", f"bold {color}"),
                    (alert.title, color),
                )
            )
            texts.append(Text(f"  {alert.message}\n", style="dim"))

        combined = Text()
        for t in texts:
            combined.append(t)
            combined.append("\n")

        return Panel(
            combined,
            title="🔔 Алерты",
            border_style="yellow",
        )

    def render_full(self):
        """Полный рендер для Live-режима."""
        from rich.console import Group
        return Group(
            self.render(),
            self.render_alerts(),
        )

    def _print_alert(self, alert: Alert):
        """Вывести алерт в лог-режиме."""
        color = SEVERITY_COLORS.get(alert.severity, "white")
        self.console.print(
            f"\n[bold {color}]━━━ ALERT [{alert.severity.upper()}] ━━━[/]"
        )
        self.console.print(f"[bold]{alert.title}[/]")
        self.console.print(f"[dim]{alert.message}[/]")
        self.console.print(f"[bold {color}]━━━━━━━━━━━━━━━━━━━━━━━━━━━[/]\n")

    def print_recommendation(self, rec: Recommendation):
        """Вывести рекомендацию в лог-режиме."""
        level = rec.level
        color = LEVEL_COLORS.get(level, "white")
        icon = LEVEL_ICONS.get(level, "")

        self.console.print(
            f"  {icon} [{color}]{rec.channel_id}[/] → "
            f"[bold {color}]{rec.level_display}[/] "
            f"(уверенность: {rec.confidence:.1%})"
        )
        if rec.is_change:
            self.console.print(
                f"    [yellow]⚠ Изменение: {rec.previous_level} → {rec.level}[/]"
            )

    def print_metrics_table(self):
        """Вывести таблицу метрик в лог-режиме."""
        self.console.print(self.render())

    def print_status(self):
        """Вывести полное состояние в лог-режиме."""
        self.console.print(self.render())
        self.console.print(self.render_alerts())
