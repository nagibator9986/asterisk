"""
Движок рекомендаций QoP (Quality of Protection) — Этап 4.

Работает в режиме советника — не обрывает активные сессии,
а формирует рекомендации по уровню защиты на основе ML-предсказаний.

Уровни:
  Low    — Standard SIP + RTP (LAN, идеальные условия)
  Medium — SIP TLS only (WAN, плохой канал)
  High   — SIP TLS + SRTP (WAN, хороший канал)
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    """Единичная рекомендация по уровню защиты."""
    channel_id: str
    level: str              # "low", "medium", "high"
    level_display: str      # Человекочитаемое название
    description: str        # Описание рекомендации
    confidence: float       # Уверенность модели
    reason: str             # Причина выбора уровня
    caller_ip: str = ""
    is_external: bool = False
    timestamp: float = field(default_factory=time.time)

    # Метрики на момент рекомендации
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0

    # Предыдущий уровень (для алертов об изменении)
    previous_level: Optional[str] = None
    is_change: bool = False


@dataclass
class Alert:
    """Системный алерт для администратора."""
    severity: str           # "info", "warning", "critical"
    title: str
    message: str
    channel_id: str
    timestamp: float = field(default_factory=time.time)
    recommendation: Optional[Recommendation] = None


class QoPRecommendationEngine:
    """
    Движок формирования рекомендаций QoP.

    Принимает предсказания ML-модели и формирует
    контекстные рекомендации с алертами.
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.levels_config = self.config["recommendation"]["levels"]

        # История рекомендаций по каналам
        self._channel_levels: dict[str, str] = {}

        # Журнал алертов
        self.alerts: list[Alert] = []
        self._max_alerts = self.config["dashboard"]["alert_history_size"]

        # Callback для алертов
        self._alert_callbacks = []

    def on_alert(self, callback):
        """Зарегистрировать callback для новых алертов."""
        self._alert_callbacks.append(callback)

    def process_prediction(self, channel_id: str, prediction: dict,
                           metrics: dict) -> Recommendation:
        """
        Обработать предсказание ML-модели и сформировать рекомендацию.

        Args:
            channel_id: ID канала
            prediction: dict от HybridQoPModel.predict()
            metrics: dict с текущими метриками канала
        """
        level = prediction["level_name"]
        confidence = prediction["confidence"]
        is_ext = bool(metrics.get("is_external", False))
        caller_ip = metrics.get("caller_ip", "unknown")

        # Определить описание и причину
        level_config = self.levels_config[level]
        reason = self._generate_reason(level, metrics, is_ext)

        # Проверить изменение уровня
        previous = self._channel_levels.get(channel_id)
        is_change = previous is not None and previous != level

        rec = Recommendation(
            channel_id=channel_id,
            level=level,
            level_display=level_config["name"],
            description=level_config["description"],
            confidence=confidence,
            reason=reason,
            caller_ip=caller_ip,
            is_external=is_ext,
            latency_ms=metrics.get("latency_ms", 0),
            jitter_ms=metrics.get("jitter_ms", 0),
            packet_loss_pct=metrics.get("packet_loss_pct", 0),
            previous_level=previous,
            is_change=is_change,
        )

        # Обновить историю
        self._channel_levels[channel_id] = level

        # Сгенерировать алерт при изменении
        if is_change:
            self._generate_change_alert(rec, previous)

        return rec

    def _generate_reason(self, level: str, metrics: dict, is_external: bool) -> str:
        """Сформировать текстовое обоснование рекомендации."""
        latency = metrics.get("latency_ms", 0)
        jitter = metrics.get("jitter_ms", 0)
        loss = metrics.get("packet_loss_pct", 0)

        if level == "low":
            return (
                f"Абонент в доверенной внутренней сети (LAN). "
                f"Метрики в норме: задержка {latency:.0f}мс, джиттер {jitter:.1f}мс, "
                f"потери {loss:.2f}%. Криптографическая нагрузка не требуется."
            )
        elif level == "medium":
            return (
                f"Внешний абонент с нестабильным каналом. "
                f"Задержка {latency:.0f}мс, джиттер {jitter:.1f}мс, потери {loss:.2f}%. "
                f"Полное шифрование (SRTP) приведет к деградации голоса. "
                f"Рекомендуется защитить только сигнализацию (SIP TLS)."
            )
        else:  # high
            return (
                f"Внешний абонент с хорошим каналом. "
                f"Задержка {latency:.0f}мс, джиттер {jitter:.1f}мс, потери {loss:.2f}%. "
                f"Канал позволяет полное сквозное шифрование (SIP TLS + SRTP) "
                f"без потери качества речи."
            )

    def _generate_change_alert(self, rec: Recommendation, previous_level: str):
        """Сгенерировать алерт при изменении уровня QoP."""
        level_order = {"low": 0, "medium": 1, "high": 2}
        prev_ord = level_order.get(previous_level, 0)
        curr_ord = level_order.get(rec.level, 0)

        if curr_ord < prev_ord:
            # Понижение уровня — деградация канала
            severity = "warning" if rec.level == "medium" else "critical"
            title = "Деградация канала — понижение профиля безопасности"
            message = (
                f"Внимание! Зафиксирована деградация внешнего канала [{rec.channel_id}]. "
                f"Риск потери качества речи при полном шифровании. "
                f"Рекомендуется понижение профиля безопасности "
                f"с {previous_level.upper()} до уровня {rec.level.upper()}. "
                f"Метрики: задержка={rec.latency_ms:.0f}мс, "
                f"джиттер={rec.jitter_ms:.1f}мс, потери={rec.packet_loss_pct:.2f}%."
            )
        else:
            # Повышение уровня — улучшение канала
            severity = "info"
            title = "Улучшение канала — повышение профиля безопасности"
            message = (
                f"Канал [{rec.channel_id}] стабилизировался. "
                f"Рекомендуется повышение профиля безопасности "
                f"с {previous_level.upper()} до {rec.level.upper()}. "
                f"Метрики: задержка={rec.latency_ms:.0f}мс, "
                f"джиттер={rec.jitter_ms:.1f}мс, потери={rec.packet_loss_pct:.2f}%."
            )

        alert = Alert(
            severity=severity,
            title=title,
            message=message,
            channel_id=rec.channel_id,
            recommendation=rec,
        )

        self.alerts.append(alert)
        if len(self.alerts) > self._max_alerts:
            self.alerts = self.alerts[-self._max_alerts:]

        for cb in self._alert_callbacks:
            try:
                cb(alert)
            except Exception as e:
                logger.error(f"Ошибка alert callback: {e}")

        log_fn = logger.warning if severity in ("warning", "critical") else logger.info
        log_fn(f"[ALERT:{severity.upper()}] {title}")
        log_fn(f"  {message}")

    def clear_channel(self, channel_id: str):
        """Удалить данные канала (при hangup)."""
        self._channel_levels.pop(channel_id, None)
