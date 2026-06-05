"""JEPA 共用 Encoder — 7维 state ↦ 4维 latent (纯 numpy)

职责（一句话）：提供状态向量到 latent 空间的映射，供 I-JEPA 和 V-JEPA 共用，
并暴露梯度更新接口（SGD）供两者分别训练。

权重持久化到 data/jepa_encoder.npz，随 daemon 启动自动加载。
"""
import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
# 输入维度：7 个核心标量，顺序固定（改顺序会使已保存权重失效）
INPUT_DIM = 7
# Latent 维度：7维输入的主要变化方向经验上不超过 4-5 个，取 4 留冗余空间
LATENT_DIM = 4
# SGD 学习率：足够小避免权重振荡，足够大让 ~50 tick 能学到结构
LR = 0.005
# He 初始化近似：tanh 网络推荐 1/sqrt(fan_in)
INIT_STD = 1.0 / np.sqrt(INPUT_DIM)
# 权重裁剪上界（防止梯度爆炸）
W_CLIP = 5.0
B_CLIP = 2.0

# 从 entity 读取的状态维度，顺序对应 INPUT_DIM
JEPA_STATE_DIMS = [
    "energy",
    "fatigue",
    "loneliness",
    "curiosity",
    "somatic_tone",
    "unresolved",
    "info_gap",
]

DATA_DIR = Path(__file__).parent.parent.parent / "data"
WEIGHTS_PATH = DATA_DIR / "jepa_encoder.npz"


class JepaEncoder:
    """线性 + tanh encoder，7→4 维，纯 numpy，支持在线梯度更新。

    W: (LATENT_DIM, INPUT_DIM)
    b: (LATENT_DIM,)
    z = tanh(W @ x + b)
    """

    def __init__(self) -> None:
        rng = np.random.default_rng(42)
        self.W: np.ndarray = rng.normal(0.0, INIT_STD, (LATENT_DIM, INPUT_DIM))
        self.b: np.ndarray = np.zeros(LATENT_DIM)
        self._load()

    # ------------------------------------------------------------------
    # 前向
    # ------------------------------------------------------------------
    def encode(self, x: np.ndarray) -> np.ndarray:
        """x: (INPUT_DIM,) → z: (LATENT_DIM,)，tanh 激活"""
        return np.tanh(self.W @ x + self.b)

    def encode_masked(self, x: np.ndarray, visible: np.ndarray) -> np.ndarray:
        """只使用可见维度（visible[i]=1）编码，其余置 0。"""
        return self.encode(x * visible)

    # ------------------------------------------------------------------
    # 反向（手写梯度）
    # ------------------------------------------------------------------
    def gradient_step(
        self,
        x: np.ndarray,
        grad_z: np.ndarray,
        visible: Optional[np.ndarray] = None,
    ) -> None:
        """
        根据 dL/dz 做一步 SGD，更新 W 和 b。
        visible: 若提供，则只对可见列的输入计算梯度（对应 encode_masked）。
        """
        x_eff = x if visible is None else x * visible
        z = self.encode(x_eff)
        d_tanh = 1.0 - z ** 2          # tanh 导数，(LATENT_DIM,)
        delta = grad_z * d_tanh         # (LATENT_DIM,)
        self.W -= LR * np.outer(delta, x_eff)
        self.b -= LR * delta
        np.clip(self.W, -W_CLIP, W_CLIP, out=self.W)
        np.clip(self.b, -B_CLIP, B_CLIP, out=self.b)

    # ------------------------------------------------------------------
    # 工具：从 entity / snapshot 提取 state 向量
    # ------------------------------------------------------------------
    @staticmethod
    def state_vec(entity) -> np.ndarray:
        """从 entity 实例读取 JEPA_STATE_DIMS，归一化到 [-1, 1]。"""
        raw = np.array(
            [float(getattr(entity, dim, 0.0)) for dim in JEPA_STATE_DIMS],
            dtype=float,
        )
        # 各维度范围约 [0, 1]，中心化并缩放
        return np.clip(raw, 0.0, 1.0) * 2.0 - 1.0

    @staticmethod
    def state_vec_from_snapshot(snapshot: dict) -> np.ndarray:
        """从 state_snapshot dict 提取（V-JEPA 批量处理 episodes 用）。"""
        raw = np.array(
            [float(snapshot.get(dim, 0.0)) for dim in JEPA_STATE_DIMS],
            dtype=float,
        )
        return np.clip(raw, 0.0, 1.0) * 2.0 - 1.0

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def save(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            np.savez(str(WEIGHTS_PATH), W=self.W, b=self.b)
            logger.debug("[JepaEncoder] weights saved")
        except Exception as e:
            logger.debug(f"[JepaEncoder] save failed: {e}")

    def _load(self) -> None:
        try:
            if WEIGHTS_PATH.exists():
                data = np.load(str(WEIGHTS_PATH))
                loaded_W = data["W"]
                loaded_b = data["b"]
                # 维度不匹配时跳过（超参数改变了）
                if loaded_W.shape == self.W.shape and loaded_b.shape == self.b.shape:
                    self.W = loaded_W
                    self.b = loaded_b
                    logger.debug("[JepaEncoder] weights loaded")
        except Exception as e:
            logger.debug(f"[JepaEncoder] load failed, using init weights: {e}")


# --------------------------------------------------------------------------
# 模块级单例
# --------------------------------------------------------------------------
_encoder: Optional[JepaEncoder] = None


def get_encoder() -> JepaEncoder:
    global _encoder
    if _encoder is None:
        _encoder = JepaEncoder()
    return _encoder
