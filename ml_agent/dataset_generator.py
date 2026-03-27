"""
Генератор синтетического датасета — Этап 3.

Создает обучающие данные с учетом специфики WAN/LAN подключений.
Метки: 0 = Low (без шифрования), 1 = Medium (SIP TLS), 2 = High (TLS + SRTP).
"""

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Количество сэмплов на класс
SAMPLES_PER_CLASS = 3000


def generate_dataset(output_path: str = "data/training_dataset.csv") -> pd.DataFrame:
    """
    Генерация датасета с реалистичным распределением метрик.

    Признаки:
        - latency_ms: задержка (0-500 мс)
        - jitter_ms: джиттер (0-100 мс)
        - packet_loss_pct: потеря пакетов (0-15%)
        - is_external: 0 = LAN, 1 = WAN
        - samples_count: кол-во RTCP-сэмплов в окне агрегации

    Метка (label):
        0 = Low  — LAN, идеальные условия
        1 = Medium — WAN, плохой канал (шифрование голоса приведет к деградации)
        2 = High — WAN, хороший канал (можно шифровать всё)
    """
    np.random.seed(42)
    data = []

    # ===== Класс 0: Low (Стандартный SIP+RTP) =====
    # Внутренняя сеть, отличное качество
    n = SAMPLES_PER_CLASS
    latency = np.random.exponential(scale=8.0, size=n).clip(1, 30)
    jitter = np.random.exponential(scale=2.0, size=n).clip(0.1, 8)
    loss = np.random.exponential(scale=0.15, size=n).clip(0, 0.5)
    is_ext = np.zeros(n, dtype=int)  # Всегда LAN
    samples = np.random.randint(5, 30, size=n)

    for i in range(n):
        data.append({
            "latency_ms": round(latency[i], 2),
            "jitter_ms": round(jitter[i], 2),
            "packet_loss_pct": round(loss[i], 3),
            "is_external": is_ext[i],
            "samples_count": samples[i],
            "label": 0,
        })

    # ===== Класс 1: Medium (SIP TLS only) =====
    # Внешняя сеть, плохой канал — шифрование голоса нежелательно
    latency = np.random.normal(loc=120, scale=40, size=n).clip(60, 400)
    jitter = np.random.normal(loc=25, scale=12, size=n).clip(8, 80)
    loss = np.random.normal(loc=4.0, scale=2.0, size=n).clip(1.5, 15)
    is_ext = np.ones(n, dtype=int)  # Всегда WAN
    samples = np.random.randint(3, 20, size=n)

    for i in range(n):
        data.append({
            "latency_ms": round(latency[i], 2),
            "jitter_ms": round(jitter[i], 2),
            "packet_loss_pct": round(loss[i], 3),
            "is_external": is_ext[i],
            "samples_count": samples[i],
            "label": 1,
        })

    # ===== Класс 2: High (SIP TLS + SRTP) =====
    # Внешняя сеть, хороший канал — полное шифрование
    latency = np.random.normal(loc=35, scale=15, size=n).clip(10, 80)
    jitter = np.random.normal(loc=6, scale=3, size=n).clip(1, 15)
    loss = np.random.exponential(scale=0.3, size=n).clip(0, 1.5)
    is_ext = np.ones(n, dtype=int)  # Всегда WAN
    samples = np.random.randint(5, 30, size=n)

    for i in range(n):
        data.append({
            "latency_ms": round(latency[i], 2),
            "jitter_ms": round(jitter[i], 2),
            "packet_loss_pct": round(loss[i], 3),
            "is_external": is_ext[i],
            "samples_count": samples[i],
            "label": 2,
        })

    # Добавляем граничные / неоднозначные кейсы для робастности
    _add_edge_cases(data)

    df = pd.DataFrame(data)
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

    df.to_csv(output_path, index=False)
    logger.info(f"Датасет сохранен: {output_path} ({len(df)} строк)")

    # Статистика
    for label in [0, 1, 2]:
        subset = df[df["label"] == label]
        logger.info(
            f"  Класс {label}: {len(subset)} сэмплов, "
            f"latency={subset['latency_ms'].mean():.1f}±{subset['latency_ms'].std():.1f}, "
            f"jitter={subset['jitter_ms'].mean():.1f}±{subset['jitter_ms'].std():.1f}, "
            f"loss={subset['packet_loss_pct'].mean():.2f}±{subset['packet_loss_pct'].std():.2f}"
        )

    return df


def _add_edge_cases(data: list[dict]):
    """Добавить граничные кейсы для улучшения обобщающей способности."""
    np.random.seed(123)
    n_edge = 300

    # LAN с небольшой деградацией — всё ещё Low
    for _ in range(n_edge):
        data.append({
            "latency_ms": round(np.random.uniform(20, 40), 2),
            "jitter_ms": round(np.random.uniform(3, 8), 2),
            "packet_loss_pct": round(np.random.uniform(0.3, 0.8), 3),
            "is_external": 0,
            "samples_count": np.random.randint(5, 20),
            "label": 0,
        })

    # WAN переход Medium -> High (улучшение канала)
    for _ in range(n_edge):
        data.append({
            "latency_ms": round(np.random.uniform(50, 90), 2),
            "jitter_ms": round(np.random.uniform(10, 18), 2),
            "packet_loss_pct": round(np.random.uniform(1.0, 2.5), 3),
            "is_external": 1,
            "samples_count": np.random.randint(5, 15),
            "label": 2 if np.random.random() > 0.5 else 1,
        })

    # WAN с очень плохим каналом — однозначно Medium
    for _ in range(n_edge):
        data.append({
            "latency_ms": round(np.random.uniform(200, 500), 2),
            "jitter_ms": round(np.random.uniform(30, 100), 2),
            "packet_loss_pct": round(np.random.uniform(5, 15), 3),
            "is_external": 1,
            "samples_count": np.random.randint(3, 10),
            "label": 1,
        })


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    generate_dataset()
