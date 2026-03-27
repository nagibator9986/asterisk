"""
Эмулятор сетевых аномалий — Этап 5.

Использует tc (traffic control) с модулем netem для внесения
искусственных задержек, потерь пакетов и джиттера.

Для работы требуются права root (sudo).
Для демонстрации без root доступен режим симуляции через AMISimulator.
"""

import subprocess
import logging
import shlex

logger = logging.getLogger(__name__)


class NetworkEmulator:
    """
    Управление сетевыми аномалиями через tc/netem.

    Предоставляет готовые сценарии деградации для демонстрации.
    """

    def __init__(self, interface: str = "eth0"):
        self.interface = interface
        self._active = False

    def apply_anomaly(self, delay_ms: int = 0, jitter_ms: int = 0,
                      loss_pct: float = 0, duplicate_pct: float = 0,
                      corrupt_pct: float = 0):
        """
        Применить сетевую аномалию через tc netem.

        Args:
            delay_ms: Добавочная задержка (мс)
            jitter_ms: Вариация задержки (мс)
            loss_pct: Потеря пакетов (%)
            duplicate_pct: Дублирование пакетов (%)
            corrupt_pct: Повреждение пакетов (%)
        """
        # Сначала удалить предыдущие правила
        self.clear()

        params = []
        if delay_ms > 0:
            params.append(f"delay {delay_ms}ms")
            if jitter_ms > 0:
                params.append(f"{jitter_ms}ms")
        if loss_pct > 0:
            params.append(f"loss {loss_pct}%")
        if duplicate_pct > 0:
            params.append(f"duplicate {duplicate_pct}%")
        if corrupt_pct > 0:
            params.append(f"corrupt {corrupt_pct}%")

        if not params:
            logger.warning("Нет параметров аномалии для применения")
            return

        cmd = f"sudo tc qdisc add dev {self.interface} root netem {' '.join(params)}"
        logger.info(f"Применение аномалии: {cmd}")

        try:
            subprocess.run(
                shlex.split(cmd),
                check=True, capture_output=True, text=True, timeout=10
            )
            self._active = True
            logger.info(
                f"Аномалия применена: delay={delay_ms}ms±{jitter_ms}ms, "
                f"loss={loss_pct}%, dup={duplicate_pct}%, corrupt={corrupt_pct}%"
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Ошибка tc: {e.stderr}")
            raise
        except FileNotFoundError:
            logger.error("tc не найден. Убедитесь, что iproute2 установлен.")
            raise

    def clear(self):
        """Удалить все правила netem."""
        cmd = f"sudo tc qdisc del dev {self.interface} root"
        try:
            subprocess.run(
                shlex.split(cmd),
                capture_output=True, text=True, timeout=10
            )
            self._active = False
            logger.info("Правила netem очищены")
        except subprocess.CalledProcessError:
            pass  # Нет активных правил — нормально

    def show_status(self) -> str:
        """Показать текущие правила tc."""
        cmd = f"tc qdisc show dev {self.interface}"
        try:
            result = subprocess.run(
                shlex.split(cmd),
                capture_output=True, text=True, timeout=10
            )
            return result.stdout
        except Exception as e:
            return f"Ошибка: {e}"

    @property
    def is_active(self) -> bool:
        return self._active


# ===== Готовые сценарии =====

class AnomalyScenarios:
    """Предопределённые сценарии деградации сети для демонстрации."""

    @staticmethod
    def mobile_4g_degradation(emulator: NetworkEmulator):
        """Имитация ухудшения 4G-соединения."""
        logger.warning("Сценарий: деградация мобильного 4G")
        emulator.apply_anomaly(delay_ms=150, jitter_ms=30, loss_pct=5)

    @staticmethod
    def provider_congestion(emulator: NetworkEmulator):
        """Имитация перегрузки провайдера."""
        logger.warning("Сценарий: перегрузка провайдера")
        emulator.apply_anomaly(delay_ms=200, jitter_ms=50, loss_pct=8)

    @staticmethod
    def wifi_interference(emulator: NetworkEmulator):
        """Имитация помех Wi-Fi."""
        logger.warning("Сценарий: интерференция Wi-Fi")
        emulator.apply_anomaly(delay_ms=80, jitter_ms=40, loss_pct=3, duplicate_pct=1)

    @staticmethod
    def satellite_link(emulator: NetworkEmulator):
        """Имитация спутникового канала (высокая задержка, стабильный)."""
        logger.warning("Сценарий: спутниковый канал")
        emulator.apply_anomaly(delay_ms=600, jitter_ms=10, loss_pct=1)

    @staticmethod
    def normal_conditions(emulator: NetworkEmulator):
        """Вернуть нормальные условия."""
        logger.info("Сценарий: нормальные условия")
        emulator.clear()
