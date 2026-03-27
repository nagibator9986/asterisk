"""
Симулятор AMI-событий для тестирования без реального Asterisk.

Генерирует реалистичные RTCP-метрики для демонстрации работы системы.
"""

import asyncio
import random
import time
import logging
from dataclasses import dataclass

from monitoring.ami_collector import CallMetrics, is_private_ip

logger = logging.getLogger(__name__)


@dataclass
class SimulatedCall:
    """Параметры симулированного вызова."""
    channel_id: str
    caller_ip: str
    callee_ip: str
    # Базовые характеристики канала
    base_latency: float
    base_jitter: float
    base_loss: float
    # Текущие модификаторы (для эмуляции деградации)
    latency_modifier: float = 0.0
    jitter_modifier: float = 0.0
    loss_modifier: float = 0.0


class AMISimulator:
    """
    Симулятор телеметрии для демонстрации без Asterisk.

    Создает виртуальные вызовы с разными сетевыми профилями
    (LAN, 4G, публичный Wi-Fi) и генерирует RTCP-метрики.
    """

    # Профили подключений
    PROFILES = {
        "lan_ideal": {
            "caller_ip": "192.168.1.100",
            "callee_ip": "192.168.1.101",
            "base_latency": 5.0,
            "base_jitter": 1.0,
            "base_loss": 0.1,
        },
        "wan_4g_mobile": {
            "caller_ip": "85.143.22.45",
            "callee_ip": "192.168.1.101",
            "base_latency": 80.0,
            "base_jitter": 15.0,
            "base_loss": 1.5,
        },
        "wan_wifi_public": {
            "caller_ip": "203.0.113.50",
            "callee_ip": "192.168.1.101",
            "base_latency": 45.0,
            "base_jitter": 8.0,
            "base_loss": 0.5,
        },
        "wan_degraded": {
            "caller_ip": "198.51.100.77",
            "callee_ip": "192.168.1.101",
            "base_latency": 180.0,
            "base_jitter": 40.0,
            "base_loss": 6.0,
        },
    }

    def __init__(self):
        self.active_calls: dict[str, SimulatedCall] = {}
        self._on_metrics_callback = None
        self._running = False
        self._call_counter = 0

    def on_metrics(self, callback):
        """Зарегистрировать callback для метрик."""
        self._on_metrics_callback = callback

    def add_call(self, profile_name: str) -> str:
        """Добавить симулированный вызов с указанным профилем."""
        if profile_name not in self.PROFILES:
            raise ValueError(f"Неизвестный профиль: {profile_name}")

        self._call_counter += 1
        channel_id = f"PJSIP/{self._call_counter:04d}"
        profile = self.PROFILES[profile_name]

        call = SimulatedCall(
            channel_id=channel_id,
            **profile,
        )
        self.active_calls[channel_id] = call
        logger.info(f"Симуляция: добавлен вызов {channel_id} ({profile_name})")
        return channel_id

    def inject_anomaly(self, channel_id: str, latency_add: float = 0,
                       jitter_add: float = 0, loss_add: float = 0):
        """Внести аномалию в конкретный вызов (аналог tc netem)."""
        if channel_id in self.active_calls:
            call = self.active_calls[channel_id]
            call.latency_modifier = latency_add
            call.jitter_modifier = jitter_add
            call.loss_modifier = loss_add
            logger.warning(
                f"Аномалия на {channel_id}: "
                f"+{latency_add}ms latency, +{jitter_add}ms jitter, +{loss_add}% loss"
            )

    def clear_anomaly(self, channel_id: str):
        """Убрать аномалию."""
        if channel_id in self.active_calls:
            call = self.active_calls[channel_id]
            call.latency_modifier = 0.0
            call.jitter_modifier = 0.0
            call.loss_modifier = 0.0
            logger.info(f"Аномалия снята с {channel_id}")

    def remove_call(self, channel_id: str):
        """Завершить симулированный вызов."""
        if channel_id in self.active_calls:
            del self.active_calls[channel_id]
            logger.info(f"Симуляция: вызов {channel_id} завершен")

    def _generate_metrics(self, call: SimulatedCall) -> CallMetrics:
        """Сгенерировать реалистичные метрики для одного тика."""
        # Добавляем случайные флуктуации
        noise_lat = random.gauss(0, call.base_latency * 0.1)
        noise_jit = random.gauss(0, call.base_jitter * 0.15)
        noise_loss = random.gauss(0, call.base_loss * 0.2)

        latency = max(0, call.base_latency + call.latency_modifier + noise_lat)
        jitter = max(0, call.base_jitter + call.jitter_modifier + noise_jit)
        loss = max(0, min(100, call.base_loss + call.loss_modifier + noise_loss))

        is_external = not is_private_ip(call.caller_ip)

        metrics = CallMetrics(
            channel_id=call.channel_id,
            caller_ip=call.caller_ip,
            callee_ip=call.callee_ip,
            is_external=is_external,
        )
        metrics.update(latency, jitter, loss)
        return metrics

    async def start(self, interval: float = 3.0):
        """Запустить генерацию метрик."""
        self._running = True
        logger.info("Симулятор AMI запущен")

        while self._running:
            for channel_id, call in list(self.active_calls.items()):
                metrics = self._generate_metrics(call)
                if self._on_metrics_callback:
                    try:
                        await self._on_metrics_callback(metrics)
                    except Exception as e:
                        logger.error(f"Ошибка в callback симулятора: {e}")

            await asyncio.sleep(interval)

    async def stop(self):
        """Остановить симулятор."""
        self._running = False
        logger.info("Симулятор AMI остановлен")
