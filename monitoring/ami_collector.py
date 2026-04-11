"""
AMI Telemetry Collector — Этап 2.

Асинхронный сбор RTCP-телеметрии через Asterisk Manager Interface.
Агрегирует метрики: latency, jitter, packet loss, IP-адрес клиента.
Передает нормализованные данные в ML-агент каждые N секунд.
"""

import asyncio
import logging
import time
import ipaddress
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable
from collections import defaultdict

import yaml

logger = logging.getLogger(__name__)


@dataclass
class CallMetrics:
    """Агрегированные метрики одного активного вызова."""
    channel_id: str
    caller_ip: str
    callee_ip: str
    is_external: bool  # True если хотя бы один абонент за NAT (WAN)

    # Сетевые метрики (скользящее среднее)
    latency_ms: float = 0.0      # RTT / 2
    jitter_ms: float = 0.0       # Вариация задержки
    packet_loss_pct: float = 0.0  # Потеря пакетов, %

    # Счетчики для усреднения
    _samples: int = 0
    _latency_sum: float = 0.0
    _jitter_sum: float = 0.0
    _loss_sum: float = 0.0

    timestamp: float = field(default_factory=time.time)

    def update(self, latency: float, jitter: float, loss: float):
        """Обновить метрики новым RTCP-сэмплом."""
        self._samples += 1
        self._latency_sum += latency
        self._jitter_sum += jitter
        self._loss_sum += loss

        self.latency_ms = self._latency_sum / self._samples
        self.jitter_ms = self._jitter_sum / self._samples
        self.packet_loss_pct = self._loss_sum / self._samples
        self.timestamp = time.time()

    def to_feature_vector(self) -> dict:
        """Преобразовать в вектор признаков для ML-модели."""
        return {
            "latency_ms": round(self.latency_ms, 2),
            "jitter_ms": round(self.jitter_ms, 2),
            "packet_loss_pct": round(self.packet_loss_pct, 3),
            "is_external": int(self.is_external),
            "samples_count": self._samples,
        }

    def reset_aggregation(self):
        """Сброс аккумуляторов для нового окна агрегации."""
        self._samples = 0
        self._latency_sum = 0.0
        self._jitter_sum = 0.0
        self._loss_sum = 0.0


def is_private_ip(ip_str: str) -> bool:
    """Определить, является ли IP внутренним (LAN)."""
    try:
        addr = ipaddress.ip_address(ip_str)
        # is_global корректно работает в Python 3.11+
        # (is_private ошибочно включает TEST-NET, shared, benchmarking и др.)
        return not addr.is_global
    except ValueError:
        return False


class AMICollector:
    """
    Коллектор телеметрии через Asterisk Manager Interface.

    Подключается к AMI, слушает события RTCP и Newchannel/Hangup,
    агрегирует метрики и вызывает callback для передачи в ML-агент.
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        ami_cfg = self.config["asterisk"]
        self.host = ami_cfg["host"]
        self.port = ami_cfg["ami_port"]
        self.username = ami_cfg["ami_username"]
        self.password = ami_cfg["ami_password"]

        self.aggregation_interval = self.config["monitoring"]["aggregation_interval"]

        # Активные вызовы: channel_id -> CallMetrics
        self.active_calls: dict[str, CallMetrics] = {}

        # Callback для отправки метрик в ML-агент
        self._on_metrics_callback: Optional[Callable[[CallMetrics], Awaitable[None]]] = None

        self._running = False
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    def on_metrics(self, callback: Callable[[CallMetrics], Awaitable[None]]):
        """Зарегистрировать callback для получения агрегированных метрик."""
        self._on_metrics_callback = callback

    async def connect(self):
        """Подключиться к AMI."""
        logger.info(f"Подключение к AMI {self.host}:{self.port}...")
        self._reader, self._writer = await asyncio.open_connection(
            self.host, self.port
        )

        # Прочитать приветствие
        greeting = await self._reader.readline()
        logger.info(f"AMI: {greeting.decode().strip()}")

        # Авторизация
        await self._send_action({
            "Action": "Login",
            "Username": self.username,
            "Secret": self.password,
            "Events": "on",
        })

        response = await self._read_response()
        if "Success" not in response.get("Response", ""):
            raise ConnectionError(f"AMI авторизация не удалась: {response}")

        logger.info("AMI: авторизация успешна")

    async def _send_action(self, action: dict):
        """Отправить AMI Action."""
        lines = []
        for key, value in action.items():
            lines.append(f"{key}: {value}")
        lines.append("")  # Пустая строка — конец сообщения
        lines.append("")
        message = "\r\n".join(lines)
        self._writer.write(message.encode())
        await self._writer.drain()

    async def _read_response(self) -> dict:
        """Прочитать один AMI-ответ."""
        result = {}
        while True:
            line = await self._reader.readline()
            decoded = line.decode().strip()
            if not decoded:
                break
            if ": " in decoded:
                key, value = decoded.split(": ", 1)
                result[key] = value
        return result

    async def _event_loop(self):
        """Основной цикл чтения событий AMI."""
        buffer = {}
        while self._running:
            try:
                line = await asyncio.wait_for(
                    self._reader.readline(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Ошибка чтения AMI: {e}")
                break

            decoded = line.decode().strip()

            if not decoded:
                if buffer:
                    await self._handle_event(buffer)
                    buffer = {}
                continue

            if ": " in decoded:
                key, value = decoded.split(": ", 1)
                buffer[key] = value

    async def _handle_event(self, event: dict):
        """Обработать AMI-событие."""
        event_type = event.get("Event", "")

        if event_type == "RTCPReceived":
            await self._handle_rtcp(event)
        elif event_type == "Newchannel":
            self._handle_new_channel(event)
        elif event_type in ("Hangup", "HangupRequest"):
            self._handle_hangup(event)

    async def _handle_rtcp(self, event: dict):
        """Обработать RTCP-пакет — извлечь метрики качества."""
        channel = event.get("Channel", "unknown")

        # Извлечение метрик из RTCP
        try:
            # RTT (Round-Trip Time) -> latency = RTT / 2
            rtt_str = event.get("RTT", "0.0")
            rtt = float(rtt_str.replace("ms", "").strip())
            latency = rtt / 2.0

            # Jitter
            jitter_str = event.get("IAJitter", event.get("Jitter", "0.0"))
            jitter = float(str(jitter_str).replace("ms", "").strip())

            # Packet Loss
            loss_str = event.get("PacketLoss", event.get("CumulativeLoss", "0"))
            total_str = event.get("PacketsReceived", event.get("SentPackets", "1"))
            packets_lost = int(loss_str)
            packets_total = max(int(total_str), 1)
            loss_pct = (packets_lost / packets_total) * 100.0

        except (ValueError, TypeError) as e:
            logger.debug(f"Не удалось распарсить RTCP: {e}")
            return

        # Найти или создать метрики для этого канала
        base_channel = channel.split("-")[0] if "-" in channel else channel

        if base_channel in self.active_calls:
            self.active_calls[base_channel].update(latency, jitter, loss_pct)
        else:
            # Определить IP из события
            from_ip = event.get("From", "").split(":")[0] if "From" in event else ""
            from_ip = from_ip.replace("IPAddress:", "").strip()
            is_ext = not is_private_ip(from_ip) if from_ip else True

            metrics = CallMetrics(
                channel_id=base_channel,
                caller_ip=from_ip,
                callee_ip="",
                is_external=is_ext,
            )
            metrics.update(latency, jitter, loss_pct)
            self.active_calls[base_channel] = metrics

    def _handle_new_channel(self, event: dict):
        """Зарегистрировать новый канал."""
        channel = event.get("Channel", "unknown")
        base_channel = channel.split("-")[0] if "-" in channel else channel
        logger.info(f"Новый канал: {channel}")

        if base_channel not in self.active_calls:
            caller_id = event.get("CallerIDNum", "")
            self.active_calls[base_channel] = CallMetrics(
                channel_id=base_channel,
                caller_ip="",
                callee_ip="",
                is_external=False,
            )

    def _handle_hangup(self, event: dict):
        """Удалить метрики завершенного канала."""
        channel = event.get("Channel", "unknown")
        base_channel = channel.split("-")[0] if "-" in channel else channel
        if base_channel in self.active_calls:
            logger.info(f"Канал завершен: {channel}")
            del self.active_calls[base_channel]

    async def _aggregation_loop(self):
        """Периодическая отправка агрегированных метрик в ML-агент."""
        while self._running:
            await asyncio.sleep(self.aggregation_interval)

            for channel_id, metrics in list(self.active_calls.items()):
                if metrics._samples > 0 and self._on_metrics_callback:
                    try:
                        await self._on_metrics_callback(metrics)
                    except Exception as e:
                        logger.error(f"Ошибка callback метрик: {e}")

                    metrics.reset_aggregation()

    async def start(self):
        """Запустить сбор телеметрии."""
        await self.connect()
        self._running = True

        logger.info("Запуск сбора телеметрии AMI...")
        await asyncio.gather(
            self._event_loop(),
            self._aggregation_loop(),
        )

    async def stop(self):
        """Остановить сбор."""
        self._running = False
        if self._writer:
            await self._send_action({"Action": "Logoff"})
            self._writer.close()
            await self._writer.wait_closed()
        logger.info("AMI-коллектор остановлен")

    def get_active_calls_summary(self) -> list[dict]:
        """Получить сводку по активным вызовам."""
        return [
            {
                "channel": m.channel_id,
                "caller_ip": m.caller_ip,
                "is_external": m.is_external,
                **m.to_feature_vector(),
            }
            for m in self.active_calls.values()
        ]
