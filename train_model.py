#!/usr/bin/env python3
"""
Скрипт обучения модели.

Генерирует датасет (если нет) и обучает гибридную модель XGBoost + MLP.
Сохраняет обученные модели в ./models/
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    # Генерация датасета
    data_path = "data/training_dataset.csv"
    if not os.path.exists(data_path):
        logger.info("Датасет не найден, генерируем...")
        os.makedirs("data", exist_ok=True)
        from ml_agent.dataset_generator import generate_dataset
        generate_dataset(data_path)
    else:
        logger.info(f"Используем существующий датасет: {data_path}")

    # Обучение
    from ml_agent.trainer import ModelTrainer

    trainer = ModelTrainer(data_path=data_path)
    trainer.run_full_pipeline()

    # Проверка
    logger.info("\n" + "=" * 60)
    logger.info("Проверка загрузки моделей...")
    from ml_agent.inference import QoPPredictor

    predictor = QoPPredictor()
    predictor.load()

    # Тестовые предсказания
    test_cases = [
        {
            "name": "LAN идеальный",
            "features": {
                "latency_ms": 5, "jitter_ms": 1,
                "packet_loss_pct": 0.1, "is_external": 0, "samples_count": 10
            },
            "expected": "low",
        },
        {
            "name": "WAN плохой канал (4G)",
            "features": {
                "latency_ms": 150, "jitter_ms": 30,
                "packet_loss_pct": 5.0, "is_external": 1, "samples_count": 8
            },
            "expected": "medium",
        },
        {
            "name": "WAN хороший канал",
            "features": {
                "latency_ms": 30, "jitter_ms": 5,
                "packet_loss_pct": 0.3, "is_external": 1, "samples_count": 15
            },
            "expected": "high",
        },
    ]

    logger.info("\nТестовые предсказания:")
    all_correct = True
    for tc in test_cases:
        result = predictor.predict(tc["features"])
        status = "✓" if result["level_name"] == tc["expected"] else "✗"
        if result["level_name"] != tc["expected"]:
            all_correct = False
        logger.info(
            f"  {status} {tc['name']}: "
            f"предсказано={result['level_name'].upper()}, "
            f"ожидалось={tc['expected'].upper()}, "
            f"уверенность={result['confidence']:.2%}"
        )

    if all_correct:
        logger.info("\n✅ Все тестовые кейсы пройдены!")
    else:
        logger.warning("\n⚠ Некоторые тестовые кейсы не совпали (модель может уточниться)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
