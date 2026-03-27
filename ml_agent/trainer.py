"""
Пайплайн обучения гибридной модели — Этап 3.

1. Обучение XGBoost на сырых признаках
2. Генерация промежуточных признаков (XGBoost probabilities)
3. Обучение MLP на комбинированных признаках
4. Сохранение обеих моделей
"""

import os
import logging

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report, accuracy_score
import joblib

from ml_agent.models import HybridQoPModel, SecurityContextMLP

logger = logging.getLogger(__name__)


class ModelTrainer:
    """Тренер гибридной модели XGBoost + MLP."""

    def __init__(self, data_path: str = "data/training_dataset.csv"):
        self.data_path = data_path
        self.model = HybridQoPModel()
        self.scaler = StandardScaler()

    def load_data(self) -> tuple:
        """Загрузить и подготовить данные."""
        df = pd.read_csv(self.data_path)
        logger.info(f"Загружено {len(df)} сэмплов")

        feature_cols = ["latency_ms", "jitter_ms", "packet_loss_pct",
                        "is_external", "samples_count"]

        X = df[feature_cols].values.astype(np.float32)
        y = df["label"].values.astype(np.int64)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        logger.info(f"Train: {len(X_train)}, Test: {len(X_test)}")
        return X_train, X_test, y_train, y_test

    def train_xgboost(self, X_train: np.ndarray, y_train: np.ndarray,
                      X_test: np.ndarray, y_test: np.ndarray) -> xgb.XGBClassifier:
        """Этап 1: обучение XGBoost."""
        logger.info("=" * 60)
        logger.info("ЭТАП 1: Обучение XGBoost (градиентный бустинг)")
        logger.info("=" * 60)

        xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="multi:softprob",
            num_class=3,
            eval_metric="mlogloss",
            random_state=42,
            use_label_encoder=False,
        )

        xgb_model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # Оценка
        y_pred = xgb_model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        logger.info(f"XGBoost Accuracy: {acc:.4f}")
        logger.info("\n" + classification_report(
            y_test, y_pred,
            target_names=["Low", "Medium", "High"]
        ))

        # Важность признаков
        importance = xgb_model.feature_importances_
        feature_names = ["latency_ms", "jitter_ms", "packet_loss_pct",
                         "is_external", "samples_count"]
        for name, imp in sorted(zip(feature_names, importance),
                                key=lambda x: x[1], reverse=True):
            logger.info(f"  {name}: {imp:.4f}")

        self.model.xgb_model = xgb_model
        return xgb_model

    def train_mlp(self, X_train: np.ndarray, y_train: np.ndarray,
                  X_test: np.ndarray, y_test: np.ndarray,
                  epochs: int = 100, batch_size: int = 64, lr: float = 0.001):
        """Этап 2: обучение MLP на комбинированных признаках."""
        logger.info("=" * 60)
        logger.info("ЭТАП 2: Обучение MLP (многослойный перцептрон)")
        logger.info("=" * 60)

        device = self.model.device

        # Генерация XGBoost-вероятностей как дополнительных признаков
        xgb_train_probs = self.model.xgb_model.predict_proba(X_train)
        xgb_test_probs = self.model.xgb_model.predict_proba(X_test)

        # Комбинированные признаки: [xgb_probs(3) + raw_features(5)]
        X_train_combined = np.hstack([xgb_train_probs, X_train])
        X_test_combined = np.hstack([xgb_test_probs, X_test])

        # Нормализация
        X_train_scaled = self.scaler.fit_transform(X_train_combined).astype(np.float32)
        X_test_scaled = self.scaler.transform(X_test_combined).astype(np.float32)

        # PyTorch DataLoaders
        train_dataset = TensorDataset(
            torch.FloatTensor(X_train_scaled),
            torch.LongTensor(y_train)
        )
        test_dataset = TensorDataset(
            torch.FloatTensor(X_test_scaled),
            torch.LongTensor(y_test)
        )

        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        test_loader = DataLoader(test_dataset, batch_size=batch_size)

        # Оптимизатор и функция потерь
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(self.model.mlp_model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=30, gamma=0.5)

        best_acc = 0.0
        best_state = None

        for epoch in range(epochs):
            # Train
            self.model.mlp_model.train()
            total_loss = 0.0

            for batch_x, batch_y in train_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)

                optimizer.zero_grad()
                output = self.model.mlp_model(batch_x)
                loss = criterion(output, batch_y)
                loss.backward()
                optimizer.step()

                total_loss += loss.item()

            scheduler.step()

            # Eval
            if (epoch + 1) % 10 == 0 or epoch == 0:
                self.model.mlp_model.eval()
                correct = 0
                total = 0

                with torch.no_grad():
                    for batch_x, batch_y in test_loader:
                        batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                        output = self.model.mlp_model(batch_x)
                        _, predicted = torch.max(output, 1)
                        total += batch_y.size(0)
                        correct += (predicted == batch_y).sum().item()

                acc = correct / total
                avg_loss = total_loss / len(train_loader)
                logger.info(
                    f"  Epoch {epoch+1}/{epochs} — "
                    f"Loss: {avg_loss:.4f}, Test Acc: {acc:.4f}"
                )

                if acc > best_acc:
                    best_acc = acc
                    best_state = self.model.mlp_model.state_dict().copy()

        # Загрузить лучшую модель
        if best_state:
            self.model.mlp_model.load_state_dict(best_state)

        # Финальная оценка
        self.model.mlp_model.eval()
        all_preds = []
        all_true = []

        with torch.no_grad():
            for batch_x, batch_y in test_loader:
                batch_x = batch_x.to(device)
                output = self.model.mlp_model(batch_x)
                _, predicted = torch.max(output, 1)
                all_preds.extend(predicted.cpu().numpy())
                all_true.extend(batch_y.numpy())

        logger.info(f"\nMLP Best Accuracy: {best_acc:.4f}")
        logger.info("\n" + classification_report(
            all_true, all_preds,
            target_names=["Low", "Medium", "High"]
        ))

        return self.model.mlp_model

    def save_models(self, models_dir: str = "models"):
        """Сохранить обученные модели."""
        os.makedirs(models_dir, exist_ok=True)

        # XGBoost
        xgb_path = os.path.join(models_dir, "xgboost_model.json")
        self.model.xgb_model.save_model(xgb_path)
        logger.info(f"XGBoost сохранен: {xgb_path}")

        # MLP
        mlp_path = os.path.join(models_dir, "mlp_model.pth")
        torch.save(self.model.mlp_model.state_dict(), mlp_path)
        logger.info(f"MLP сохранен: {mlp_path}")

        # Scaler
        scaler_path = os.path.join(models_dir, "scaler.pkl")
        joblib.dump(self.scaler, scaler_path)
        logger.info(f"Scaler сохранен: {scaler_path}")

    def load_models(self, models_dir: str = "models"):
        """Загрузить обученные модели."""
        # XGBoost
        xgb_path = os.path.join(models_dir, "xgboost_model.json")
        self.model.xgb_model = xgb.XGBClassifier()
        self.model.xgb_model.load_model(xgb_path)

        # MLP
        mlp_path = os.path.join(models_dir, "mlp_model.pth")
        self.model.mlp_model.load_state_dict(
            torch.load(mlp_path, map_location=self.model.device, weights_only=True)
        )
        self.model.mlp_model.eval()

        # Scaler
        scaler_path = os.path.join(models_dir, "scaler.pkl")
        self.scaler = joblib.load(scaler_path)

        logger.info("Модели загружены успешно")

    def run_full_pipeline(self):
        """Полный пайплайн обучения."""
        X_train, X_test, y_train, y_test = self.load_data()

        self.train_xgboost(X_train, y_train, X_test, y_test)
        self.train_mlp(X_train, y_train, X_test, y_test)
        self.save_models()

        logger.info("=" * 60)
        logger.info("Обучение завершено! Модели сохранены в ./models/")
        logger.info("=" * 60)

        return self.model
