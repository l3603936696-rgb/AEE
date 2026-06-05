"""I-JEPA 长期后台 — 掩码状态预测，学习 state 内部结构依赖 (纯 numpy)

职责（一句话）：每个 daemon tick 做一步在线学习——随机 mask 1-2 个 state 维度，
从可见维度的 latent embedding 预测被掩盖维度的值，更新 encoder + predictor 权重。

产出信号：
  reconstruction_error（rolling mean）— 当前 encoder 对 state 结构的理解程度。
  该值由 V-JEPA 读取，用于判断哪些时刻 I-JEPA 仍在快速学习（结构未稳定）。

不直接修改 entity 状态——只是安静地学习。
"""
import logging
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from .jepa_encoder import (
    JepaEncoder,
    get_encoder,
    INPUT_DIM,
    LATENT_DIM,
    JEPA_STATE_DIMS,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
# predictor：z_masked (LATENT_DIM,) → 每个被 mask 维度的预测值
# 用 INPUT_DIM 个独立线性头，每头 LATENT_DIM 个权重
PRED_LR = 0.01          # predictor 学习率（比 encoder 大，predictor 更浅）
ROLLING_WINDOW = 50     # rolling mean 窗口大小
SAVE_INTERVAL = 100     # 每多少 tick 保存一次权重
# mask 维度数的范围（最少 1，最多 2）
MASK_MIN = 1
MASK_MAX = 2

DATA_DIR = Path(__file__).parent.parent.parent / "data"
PRED_WEIGHTS_PATH = DATA_DIR / "i_jepa_predictor.npz"


class IJepa:
    """I-JEPA 在线学习器，每 tick 调用 step(entity) 一次。"""

    def __init__(self, encoder: Optional[JepaEncoder] = None) -> None:
        self.encoder = encoder or get_encoder()
        self._rng = np.random.default_rng()

        # predictor heads: (INPUT_DIM, LATENT_DIM)
        # heads[i] @ z → 预测 state_vec[i] 的值（标量回归）
        init_std = 1.0 / np.sqrt(LATENT_DIM)
        self._heads: np.ndarray = self._rng.normal(
            0.0, init_std, (INPUT_DIM, LATENT_DIM)
        )
        self._head_bias: np.ndarray = np.zeros(INPUT_DIM)

        # rolling error buffer
        self._error_buf: list = []
        self._tick_since_save: int = 0

        self._load()

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------
    def step(self, entity) -> float:
        """
        从 entity 提取 state，做一步在线学习。
        返回本步的 reconstruction_error（被 mask 维度的预测 MSE）。
        """
        x = self.encoder.state_vec(entity)

        # 随机选 mask 维度（1 或 2）
        n_mask = int(self._rng.integers(MASK_MIN, MASK_MAX + 1))
        masked_idx = self._rng.choice(INPUT_DIM, size=n_mask, replace=False)

        visible = np.ones(INPUT_DIM, dtype=float)
        visible[masked_idx] = 0.0

        # 前向：用可见维度编码
        z = self.encoder.encode_masked(x, visible)

        # 预测每个被 mask 维度
        y_hat = np.array([self._heads[i] @ z + self._head_bias[i] for i in masked_idx])
        y_true = x[masked_idx]

        # MSE loss
        diff = y_hat - y_true
        loss = float(np.mean(diff ** 2))

        # ---- 更新 predictor heads ----
        for k, i in enumerate(masked_idx):
            grad_head = diff[k] * z                   # dL/d(heads[i]) = diff * z
            grad_bias = diff[k]
            self._heads[i] -= PRED_LR * grad_head
            self._head_bias[i] -= PRED_LR * grad_bias
            np.clip(self._heads[i], -3.0, 3.0, out=self._heads[i])

            # ---- 反传到 encoder ----
            # dL/dz = Σ_k diff[k] * heads[i]
            grad_z = diff[k] * self._heads[i]
            self.encoder.gradient_step(x, grad_z, visible=visible)

        # rolling error
        self._error_buf.append(loss)
        if len(self._error_buf) > ROLLING_WINDOW:
            self._error_buf.pop(0)

        self._tick_since_save += 1
        if self._tick_since_save >= SAVE_INTERVAL:
            self._save()
            self.encoder.save()
            self._tick_since_save = 0

        return loss

    def rolling_error(self) -> float:
        """最近 ROLLING_WINDOW 步的平均 reconstruction_error。"""
        if not self._error_buf:
            return 1.0
        return float(np.mean(self._error_buf))

    def stats(self) -> Dict[str, float]:
        return {
            "rolling_error": self.rolling_error(),
            "buffer_len": float(len(self._error_buf)),
        }

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _save(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            np.savez(
                str(PRED_WEIGHTS_PATH),
                heads=self._heads,
                head_bias=self._head_bias,
            )
            logger.debug("[I-JEPA] predictor saved")
        except Exception as e:
            logger.debug(f"[I-JEPA] save failed: {e}")

    def _load(self) -> None:
        try:
            if PRED_WEIGHTS_PATH.exists():
                data = np.load(str(PRED_WEIGHTS_PATH))
                h = data["heads"]
                hb = data["head_bias"]
                if h.shape == self._heads.shape and hb.shape == self._head_bias.shape:
                    self._heads = h
                    self._head_bias = hb
                    logger.debug("[I-JEPA] predictor loaded")
        except Exception as e:
            logger.debug(f"[I-JEPA] load failed, using init weights: {e}")


# --------------------------------------------------------------------------
# 模块级单例
# --------------------------------------------------------------------------
_i_jepa: Optional[IJepa] = None


def get_i_jepa() -> IJepa:
    global _i_jepa
    if _i_jepa is None:
        _i_jepa = IJepa()
    return _i_jepa
