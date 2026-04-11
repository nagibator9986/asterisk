"""
Гибридная ML-модель — Этап 3.

Двухступенчатая архитектура:
  1. XGBoost — анализ телеметрии, выявление паттернов деградации
  2. PyTorch MLP — наложение контекста безопасности, финальная классификация QoP

Классы: 0=Low, 1=Medium, 2=High
"""

import numpy as np
import torch
import torch.nn as nn
import xgboost as xgb
import logging

logger = logging.getLogger(__name__)


class SecurityContextMLP(nn.Module):
    """
    Многослойный перцептрон для классификации QoP.

    Принимает:
      - Выход XGBoost (вероятности 3 классов)
      - Исходные признаки телеметрии
      - Контекст безопасности (is_external)

    Выдает: вероятности для 3 уровней QoP.
    """

    def __init__(self, input_dim: int = 8, hidden_dim: int = 64, num_classes: int = 3):
        super().__init__()

        self.network = nn.Sequential(
            # Первый скрытый слой
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),

            # Второй скрытый слой
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.BatchNorm1d(hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.2),

            # Третий скрытый слой
            nn.Linear(hidden_dim // 2, hidden_dim // 4),
            nn.ReLU(),

            # Выходной слой
            nn.Linear(hidden_dim // 4, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


class HybridQoPModel:
    """
    Гибридная модель XGBoost + MLP для классификации QoP.

    Поток данных:
      raw_features -> XGBoost -> xgb_probs
      [xgb_probs + raw_features + security_context] -> MLP -> QoP_level
    """

    def __init__(self):
        # XGBoost — Stage 1
        self.xgb_model: xgb.XGBClassifier = None

        # MLP — Stage 2
        # input_dim = 3 (xgb probs) + 5 (raw features) = 8
        self.mlp_model = SecurityContextMLP(input_dim=8, hidden_dim=64, num_classes=3)

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.mlp_model.to(self.device)

        self.feature_names = [
            "latency_ms", "jitter_ms", "packet_loss_pct",
            "is_external", "samples_count"
        ]

    def predict(self, features: dict) -> dict:
        """
        Предсказать уровень QoP для одного набора метрик.

        Args:
            features: dict с ключами из self.feature_names

        Returns:
            dict с полями:
              - level: int (0, 1, 2)
              - level_name: str ("low", "medium", "high")
              - confidence: float
              - probabilities: dict
              - xgb_probabilities: dict (промежуточные, от XGBoost)
        """
        if self.xgb_model is None:
            raise RuntimeError(
                "Модель не обучена. Запустите trainer.run_full_pipeline() "
                "или используйте QoPPredictor с предварительным вызовом load()."
            )

        # Подготовка входа
        x_raw = np.array([[
            features.get("latency_ms", 0),
            features.get("jitter_ms", 0),
            features.get("packet_loss_pct", 0),
            features.get("is_external", 0),
            features.get("samples_count", 1),
        ]], dtype=np.float32)

        # Stage 1: XGBoost
        xgb_probs = self.xgb_model.predict_proba(x_raw)[0]  # shape: (3,)

        # Stage 2: MLP
        # Конкатенация: [xgb_probs(3) + raw_features(5)]
        mlp_input = np.concatenate([xgb_probs, x_raw[0]])
        mlp_tensor = torch.FloatTensor(mlp_input).unsqueeze(0).to(self.device)

        self.mlp_model.eval()
        with torch.no_grad():
            logits = self.mlp_model(mlp_tensor)
            probs = torch.softmax(logits, dim=1).cpu().numpy()[0]

        predicted_class = int(np.argmax(probs))
        confidence = float(probs[predicted_class])

        level_names = {0: "low", 1: "medium", 2: "high"}

        return {
            "level": predicted_class,
            "level_name": level_names[predicted_class],
            "confidence": round(confidence, 4),
            "probabilities": {
                "low": round(float(probs[0]), 4),
                "medium": round(float(probs[1]), 4),
                "high": round(float(probs[2]), 4),
            },
            "xgb_probabilities": {
                "low": round(float(xgb_probs[0]), 4),
                "medium": round(float(xgb_probs[1]), 4),
                "high": round(float(xgb_probs[2]), 4),
            },
        }

    def predict_batch(self, features_list: list[dict]) -> list[dict]:
        """Пакетное предсказание."""
        return [self.predict(f) for f in features_list]
