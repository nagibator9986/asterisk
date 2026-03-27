"""
Модуль инференса — загрузка обученных моделей и предсказание в реальном времени.
"""

import os
import logging
import numpy as np
import torch
import xgboost as xgb
import joblib

from ml_agent.models import HybridQoPModel

logger = logging.getLogger(__name__)


class QoPPredictor:
    """
    Загружает обученные модели и выполняет предсказания QoP.

    Используется в runtime для обработки входящих метрик
    от AMI-коллектора.
    """

    def __init__(self, models_dir: str = "models"):
        self.models_dir = models_dir
        self.model = HybridQoPModel()
        self.scaler = None
        self._loaded = False

    def load(self):
        """Загрузить обученные модели с диска."""
        xgb_path = os.path.join(self.models_dir, "xgboost_model.json")
        mlp_path = os.path.join(self.models_dir, "mlp_model.pth")
        scaler_path = os.path.join(self.models_dir, "scaler.pkl")

        for path in [xgb_path, mlp_path, scaler_path]:
            if not os.path.exists(path):
                raise FileNotFoundError(
                    f"Модель не найдена: {path}. "
                    f"Запустите обучение: python train_model.py"
                )

        # XGBoost
        self.model.xgb_model = xgb.XGBClassifier()
        self.model.xgb_model.load_model(xgb_path)
        logger.info(f"XGBoost загружен: {xgb_path}")

        # MLP
        self.model.mlp_model.load_state_dict(
            torch.load(mlp_path, map_location=self.model.device, weights_only=True)
        )
        self.model.mlp_model.eval()
        logger.info(f"MLP загружен: {mlp_path}")

        # Scaler
        self.scaler = joblib.load(scaler_path)
        logger.info(f"Scaler загружен: {scaler_path}")

        self._loaded = True

    def predict(self, features: dict) -> dict:
        """
        Предсказать уровень QoP.

        Args:
            features: dict с ключами latency_ms, jitter_ms,
                      packet_loss_pct, is_external, samples_count

        Returns:
            dict с полями level, level_name, confidence, probabilities
        """
        if not self._loaded:
            raise RuntimeError("Модели не загружены. Вызовите load() сначала.")

        # Подготовка входных данных
        x_raw = np.array([[
            features.get("latency_ms", 0),
            features.get("jitter_ms", 0),
            features.get("packet_loss_pct", 0),
            features.get("is_external", 0),
            features.get("samples_count", 1),
        ]], dtype=np.float32)

        # Stage 1: XGBoost
        xgb_probs = self.model.xgb_model.predict_proba(x_raw)[0]

        # Stage 2: MLP (с нормализацией)
        mlp_input = np.concatenate([xgb_probs, x_raw[0]]).reshape(1, -1)
        mlp_scaled = self.scaler.transform(mlp_input).astype(np.float32)
        mlp_tensor = torch.FloatTensor(mlp_scaled).to(self.model.device)

        self.model.mlp_model.eval()
        with torch.no_grad():
            logits = self.model.mlp_model(mlp_tensor)
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

    @property
    def is_loaded(self) -> bool:
        return self._loaded
