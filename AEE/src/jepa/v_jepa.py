"""V-JEPA 短时总结 — 时序状态预测，分析近期动态模式 (纯 numpy)

职责（一句话）：每 V_JEPA_INTERVAL tick 从 episodes.db 读取最近一批有序 state，
训练时序预测器（z_t → z_{t+1}），计算 prediction_error 时序分布，产出两个信号：
  surprise_density  — 近期平均意外程度，校准 entity.curiosity 基线
  transition_ticks  — 高误差时刻，告知 I-JEPA 在这些 state 上重点学习

同时向 entity 写入 _jepa_surprise_density 供 pipeline_runner 使用。
"""
import json
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from .jepa_encoder import JepaEncoder, get_encoder, LATENT_DIM, INPUT_DIM

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
# 触发间隔：~200 tick ≈ 100 分钟（30s/tick），相当于"每小时多一点"做一次总结
V_JEPA_INTERVAL = 200
# 每次读取的 episode 数量（时序窗口大小）
LOOKBACK_EPISODES = 60
# temporal predictor 学习率
TEMP_LR = 0.005
# temporal predictor 在每次总结时的训练轮数（不是 epoch，是 online 过数次）
TRAIN_PASSES = 3
# surprise_density 高于此阈值时认为"近期动荡"（连续函数映射，不做硬切）
SURPRISE_SCALE = 2.0    # sigmoid 拉伸系数，让 density 映射到 [0,1] 的幅度更敏感
# 判定为 transition_moment 的 error 分位数（只标记最高的这些 tick）
TRANSITION_QUANTILE = 0.85
# predictor 权重保存路径
DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = DATA_DIR / "episodes.db"
TEMP_PRED_PATH = DATA_DIR / "v_jepa_predictor.npz"


class VJepa:
    """V-JEPA 短时总结器，每 V_JEPA_INTERVAL tick 调用 summarize(entity) 一次。"""

    def __init__(self, encoder: Optional[JepaEncoder] = None) -> None:
        self.encoder = encoder or get_encoder()
        self._rng = np.random.default_rng()

        # temporal predictor: z_t → z_{t+1}，线性，LATENT_DIM → LATENT_DIM
        init_std = 1.0 / np.sqrt(LATENT_DIM)
        self._W_temp: np.ndarray = self._rng.normal(
            0.0, init_std, (LATENT_DIM, LATENT_DIM)
        )
        self._b_temp: np.ndarray = np.zeros(LATENT_DIM)

        # 上次总结时产出的结果（供外部查询）
        self._last_result: Dict = {}
        self._load()

    # ------------------------------------------------------------------
    # 主接口
    # ------------------------------------------------------------------
    def should_run(self, entity) -> bool:
        """判断是否到了触发时机。"""
        tick = int(getattr(entity, "tick", 0))
        last = int(getattr(entity, "_last_vjepa_tick", -(V_JEPA_INTERVAL + 1)))
        return (tick - last) >= V_JEPA_INTERVAL

    def summarize(self, entity) -> Dict:
        """
        执行一次短时总结。
        返回 {"surprise_density": float, "transition_ticks": List[int], "applied": bool}
        """
        snapshots = self._load_recent_snapshots()
        if len(snapshots) < 4:
            logger.debug(f"[V-JEPA] not enough episodes ({len(snapshots)}), skip")
            return {"applied": False, "reason": "not_enough_episodes"}

        # 转换为 latent 序列
        z_seq = np.array([
            self.encoder.encode(self.encoder.state_vec_from_snapshot(s))
            for s in snapshots
        ])  # (N, LATENT_DIM)

        # 训练时序预测器（多 pass）
        errors = self._train_and_eval(z_seq)

        # 计算 surprise_density（mean error，sigmoid 归一化到 [0,1]）
        mean_err = float(np.mean(errors))
        surprise_density = float(1.0 / (1.0 + np.exp(-SURPRISE_SCALE * (mean_err - 0.3))))

        # 找 transition_moments（高误差时刻）
        threshold = float(np.quantile(errors, TRANSITION_QUANTILE))
        # 用连续权重而非硬截断：error 越高权重越高
        weights = np.maximum(errors - threshold, 0.0)
        # transition_ticks: 权重 > 0 的下标（对应 episode 序号）
        transition_indices = list(np.where(weights > 0)[0].astype(int))

        # 写回 entity
        entity._last_vjepa_tick = int(getattr(entity, "tick", 0))
        entity._jepa_surprise_density = surprise_density
        entity._jepa_transition_indices = transition_indices

        self._save()
        self.encoder.save()

        result = {
            "applied": True,
            "surprise_density": surprise_density,
            "transition_ticks": transition_indices,
            "episode_count": len(snapshots),
            "mean_error": round(mean_err, 4),
        }
        self._last_result = result
        logger.info(
            f"[V-JEPA] surprise_density={surprise_density:.3f}, "
            f"transitions={len(transition_indices)}, mean_err={mean_err:.4f}"
        )
        return result

    # ------------------------------------------------------------------
    # 时序训练
    # ------------------------------------------------------------------
    def _train_and_eval(self, z_seq: np.ndarray) -> np.ndarray:
        """
        对 z 序列做 TRAIN_PASSES 遍训练，返回每步的 prediction_error（L2 距离）。
        最后一遍的 error 作为输出（代表当前 predictor 的真实误差）。
        """
        N = len(z_seq)
        final_errors = np.zeros(N - 1)

        for pass_idx in range(TRAIN_PASSES):
            errors = np.zeros(N - 1)
            for t in range(N - 1):
                z_t = z_seq[t]
                z_next = z_seq[t + 1]

                # 前向：预测 z_{t+1}
                z_hat = np.tanh(self._W_temp @ z_t + self._b_temp)

                diff = z_hat - z_next
                errors[t] = float(np.linalg.norm(diff))

                # 反向（tanh 导数）
                d_tanh = 1.0 - z_hat ** 2
                delta = diff * d_tanh
                self._W_temp -= TEMP_LR * np.outer(delta, z_t)
                self._b_temp -= TEMP_LR * delta
                np.clip(self._W_temp, -5.0, 5.0, out=self._W_temp)
                np.clip(self._b_temp, -2.0, 2.0, out=self._b_temp)

                # V-JEPA 只更新 temporal predictor；
                # encoder 权重由 I-JEPA 独家负责（它有原始 x，梯度方向正确）。

            if pass_idx == TRAIN_PASSES - 1:
                final_errors = errors

        return final_errors

    # ------------------------------------------------------------------
    # 读 episodes
    # ------------------------------------------------------------------
    def _load_recent_snapshots(self) -> List[dict]:
        """从 episodes.db 读取最近 LOOKBACK_EPISODES 条的 state_snapshot。"""
        snapshots = []
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=5)
            cur = conn.cursor()
            cur.execute(
                "SELECT state_snapshot FROM episodes "
                "ORDER BY iteration_id DESC LIMIT ?",
                (LOOKBACK_EPISODES,),
            )
            rows = cur.fetchall()
            conn.close()
            # 反转使时间正序（oldest first）
            for (raw,) in reversed(rows):
                try:
                    s = json.loads(raw) if isinstance(raw, str) else {}
                    if isinstance(s, dict):
                        snapshots.append(s)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[V-JEPA] db read failed: {e}")
        return snapshots

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _save(self) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            np.savez(
                str(TEMP_PRED_PATH),
                W_temp=self._W_temp,
                b_temp=self._b_temp,
            )
            logger.debug("[V-JEPA] predictor saved")
        except Exception as e:
            logger.debug(f"[V-JEPA] save failed: {e}")

    def _load(self) -> None:
        try:
            if TEMP_PRED_PATH.exists():
                data = np.load(str(TEMP_PRED_PATH))
                wt = data["W_temp"]
                bt = data["b_temp"]
                if wt.shape == self._W_temp.shape and bt.shape == self._b_temp.shape:
                    self._W_temp = wt
                    self._b_temp = bt
                    logger.debug("[V-JEPA] predictor loaded")
        except Exception as e:
            logger.debug(f"[V-JEPA] load failed, using init weights: {e}")

    def last_result(self) -> Dict:
        return dict(self._last_result)


# --------------------------------------------------------------------------
# 模块级单例
# --------------------------------------------------------------------------
_v_jepa: Optional[VJepa] = None


def get_v_jepa() -> VJepa:
    global _v_jepa
    if _v_jepa is None:
        _v_jepa = VJepa()
    return _v_jepa
