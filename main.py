#!/usr/bin/env python3
"""
Главный модуль — оркестрация всей системы.

Режимы запуска:
  python main.py            — GUI-дашборд (по умолчанию)
  python main.py gui        — GUI-дашборд с графическим интерфейсом
  python main.py demo       — Демонстрация в консоли (без Asterisk)
  python main.py live       — Подключение к реальному Asterisk через AMI
  python main.py train      — Обучение ML-модели
  python main.py scenario   — Интерактивный режим с готовыми сценариями
"""

import asyncio
import sys
import signal
import logging
import os
import time

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class QoPSystem:
    """
    Главный оркестратор системы рекомендаций QoP.

    Связывает все компоненты: мониторинг → ML → рекомендации → дашборд.
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)

        self.predictor = None
        self.rec_engine = None
        self.dashboard = None
        self._running = False

    def _load_models(self):
        """Загрузить обученные модели."""
        from ml_agent.inference import QoPPredictor

        self.predictor = QoPPredictor()
        try:
            self.predictor.load()
            logger.info("ML-модели загружены")
        except FileNotFoundError:
            logger.error(
                "Модели не найдены! Сначала обучите модель:\n"
                "  python train_model.py"
            )
            sys.exit(1)

    def _init_components(self):
        """Инициализировать рекомендательный движок и дашборд."""
        from recommendation.engine import QoPRecommendationEngine
        from dashboard.console_dashboard import ConsoleDashboard

        self.rec_engine = QoPRecommendationEngine(self.config_path)
        self.dashboard = ConsoleDashboard(live_mode=False)

        # Связать алерты с дашбордом
        self.rec_engine.on_alert(self.dashboard.add_alert)

    async def _process_metrics(self, metrics):
        """
        Callback: обработать метрики из AMI/симулятора.

        Конвейер: метрики → ML-предсказание → рекомендация → дашборд.
        """
        features = metrics.to_feature_vector()
        features["caller_ip"] = metrics.caller_ip

        # ML-предсказание
        prediction = self.predictor.predict(features)

        # Формирование рекомендации
        recommendation = self.rec_engine.process_prediction(
            channel_id=metrics.channel_id,
            prediction=prediction,
            metrics={**features, "caller_ip": metrics.caller_ip},
        )

        # Обновить дашборд
        self.dashboard.update_channel(
            metrics.channel_id, features, recommendation
        )

        # Вывести рекомендацию
        self.dashboard.print_recommendation(recommendation)

    async def run_demo(self):
        """
        Демонстрационный режим с симулятором.

        Создает виртуальные вызовы, генерирует метрики,
        через 15 секунд вносит аномалию для демонстрации алерта.
        """
        from monitoring.simulator import AMISimulator
        from rich.console import Console

        console = Console()

        self._load_models()
        self._init_components()

        simulator = AMISimulator()
        simulator.on_metrics(self._process_metrics)

        # Создать тестовые вызовы
        console.print("\n[bold cyan]═══ Запуск демонстрации ═══[/]\n")

        ch1 = simulator.add_call("lan_ideal")
        console.print(f"  [green]+ Вызов {ch1}: LAN (идеальные условия)[/]")

        ch2 = simulator.add_call("wan_wifi_public")
        console.print(f"  [yellow]+ Вызов {ch2}: WAN (публичный Wi-Fi)[/]")

        ch3 = simulator.add_call("wan_4g_mobile")
        console.print(f"  [red]+ Вызов {ch3}: WAN (мобильный 4G)[/]")

        console.print(
            "\n[dim]Система работает. Через 15 секунд будет внесена аномалия...[/]\n"
        )

        self._running = True

        async def anomaly_scenario():
            """Сценарий: внесение и снятие аномалии."""
            await asyncio.sleep(15)

            console.print("\n[bold red]━━━ ВНЕСЕНИЕ АНОМАЛИИ ━━━[/]")
            console.print(
                "[red]Имитация деградации 4G: +150мс задержка, +5% потери[/]\n"
            )
            simulator.inject_anomaly(ch2, latency_add=150, jitter_add=20, loss_add=5)

            await asyncio.sleep(20)

            console.print("\n[bold green]━━━ СНЯТИЕ АНОМАЛИИ ━━━[/]")
            console.print("[green]Канал стабилизировался[/]\n")
            simulator.clear_anomaly(ch2)

            await asyncio.sleep(15)

            # Показать итоговую таблицу
            console.print("\n[bold cyan]═══ Итоговое состояние ═══[/]")
            self.dashboard.print_status()

        async def periodic_status():
            """Периодический вывод таблицы метрик."""
            while self._running:
                await asyncio.sleep(10)
                self.dashboard.print_metrics_table()

        try:
            await asyncio.gather(
                simulator.start(interval=3.0),
                anomaly_scenario(),
                periodic_status(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            await simulator.stop()

    async def run_live(self):
        """Подключение к реальному Asterisk через AMI."""
        from monitoring.ami_collector import AMICollector

        self._load_models()
        self._init_components()

        collector = AMICollector(self.config_path)
        collector.on_metrics(self._process_metrics)

        self._running = True
        logger.info("Подключение к реальному Asterisk...")

        try:
            await collector.start()
        except KeyboardInterrupt:
            pass
        finally:
            await collector.stop()

    async def run_scenario(self):
        """
        Интерактивный режим: пользователь выбирает сценарии.
        """
        from monitoring.simulator import AMISimulator
        from rich.console import Console
        from rich.prompt import Prompt

        console = Console()

        self._load_models()
        self._init_components()

        simulator = AMISimulator()
        simulator.on_metrics(self._process_metrics)

        # Создать начальные вызовы
        channels = {}
        for profile in ["lan_ideal", "wan_wifi_public", "wan_4g_mobile"]:
            ch = simulator.add_call(profile)
            channels[profile] = ch

        console.print("\n[bold cyan]═══ Интерактивный режим ═══[/]")
        console.print("Доступные команды:")
        console.print("  [green]1[/] — Внести аномалию (деградация 4G)")
        console.print("  [green]2[/] — Внести аномалию (перегрузка провайдера)")
        console.print("  [green]3[/] — Снять все аномалии")
        console.print("  [green]4[/] — Показать текущее состояние")
        console.print("  [green]q[/] — Выход\n")

        # Запуск симулятора в фоне
        sim_task = asyncio.create_task(simulator.start(interval=3.0))

        try:
            while True:
                await asyncio.sleep(0.1)
                # Чтение команды через asyncio-совместимый способ
                cmd = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("Команда> ").strip()
                )

                if cmd == "1":
                    ch = channels.get("wan_4g_mobile")
                    if ch:
                        simulator.inject_anomaly(ch, latency_add=150, loss_add=5)
                        console.print("[red]Аномалия 4G применена[/]")
                elif cmd == "2":
                    ch = channels.get("wan_wifi_public")
                    if ch:
                        simulator.inject_anomaly(ch, latency_add=200, jitter_add=50, loss_add=8)
                        console.print("[red]Перегрузка провайдера применена[/]")
                elif cmd == "3":
                    for ch in channels.values():
                        simulator.clear_anomaly(ch)
                    console.print("[green]Все аномалии сняты[/]")
                elif cmd == "4":
                    self.dashboard.print_status()
                elif cmd == "q":
                    break
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            sim_task.cancel()
            await simulator.stop()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "gui"
    system = QoPSystem()

    if mode == "train":
        import train_model
        train_model.main()
    elif mode == "gui":
        from dashboard.gui_dashboard import QoPDashboard
        app = QoPDashboard()
        app.run()
    elif mode == "demo":
        asyncio.run(system.run_demo())
    elif mode == "live":
        asyncio.run(system.run_live())
    elif mode == "scenario":
        asyncio.run(system.run_scenario())
    else:
        print(f"Неизвестный режим: {mode}")
        print("Использование: python main.py [gui|demo|live|train|scenario]")
        sys.exit(1)


if __name__ == "__main__":
    main()
