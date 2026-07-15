from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from external.contracts.base_bot import ActionBot
from external.ml import xgb_features

BOT_META = {
    "schema_version": 1,
    "id": "xg_bot",
    "name": "XG Bot",
    "version": "0.1.0",
    "description": "Explainable XGBoost state-action ranker with QualifierBot fallback.",
    "author": "Lucas Starkey",
    "tags": ["research", "xgboost", "explainable"],
}

_REPO = Path(__file__).resolve().parents[3]
_RESULTS_DIR = _REPO / "operations" / "research" / "results"
_DEFAULT_MODEL = _RESULTS_DIR / "xg_bot_ranker.json"
_DEFAULT_FEATURES = _RESULTS_DIR / "xg_bot_features.json"
_LOGGER = logging.getLogger(__name__)


class XGBot(ActionBot):
    META = BOT_META

    def __init__(
        self,
        model_path: str | Path = _DEFAULT_MODEL,
        features_path: str | Path = _DEFAULT_FEATURES,
    ) -> None:
        super().__init__()
        self._model_path = Path(model_path)
        self._features_path = Path(features_path)
        self._load_attempted = False
        self._booster = None
        self._xgb = None
        self._feature_names: list[str] | None = None
        self._fallback_bot = None
        self._fallback_reason = "model was not loaded"
        self._fallback_warned = False

    def set_player(self, player):
        super().set_player(player)
        if self._fallback_bot is not None:
            self._fallback_bot.set_player(player)

    def act(self, view: Any, legal_actions: list[Any]) -> Any:
        if not legal_actions:
            return None
        if not self._load_model():
            return self._fallback_action(view, legal_actions)

        try:
            state = xgb_features.state_from_view(view)
            legal_dicts = xgb_features.actions_to_dicts(legal_actions)
            rows = xgb_features.build_action_feature_rows(
                {"player": view.player_id, "decision": view.decision, "state": state},
                legal_dicts,
            )
            matrix = xgb_features.vectorize(rows, self._feature_names)
            dmatrix = self._xgb.DMatrix(matrix)
            scores = list(self._booster.predict(dmatrix))
        except Exception as exc:
            self._fallback_reason = f"inference failed: {exc}"
            return self._fallback_action(view, legal_actions)

        if len(scores) != len(legal_actions):
            self._fallback_reason = "model returned a score count that did not match the legal action menu"
            return self._fallback_action(view, legal_actions)
        best_index = max(range(len(scores)), key=lambda index: (float(scores[index]), -index))
        return legal_actions[best_index]

    def _load_model(self) -> bool:
        if self._load_attempted:
            return self._booster is not None
        self._load_attempted = True
        if not self._model_path.exists() or not self._features_path.exists():
            self._fallback_reason = f"missing model artifacts at {self._model_path} and/or {self._features_path}"
            return False

        try:
            import xgboost as xgb

            payload = json.loads(self._features_path.read_text())
            feature_names = list(payload["feature_names"])
            booster = xgb.Booster()
            booster.load_model(str(self._model_path))
        except Exception as exc:
            self._fallback_reason = f"model load failed: {exc}"
            return False

        self._xgb = xgb
        self._booster = booster
        self._feature_names = feature_names
        return True

    def _fallback_action(self, view: Any, legal_actions: list[Any]) -> Any:
        if not self._fallback_warned:
            _LOGGER.warning("XG Bot falling back to QualifierBot: %s.", self._fallback_reason)
            self._fallback_warned = True
        if self._fallback_bot is None:
            from external.bots.qualifier_bot import QualifierBot

            self._fallback_bot = QualifierBot()
            if hasattr(self, "player"):
                self._fallback_bot.set_player(self.player)
        return self._fallback_bot.act(view, legal_actions)
