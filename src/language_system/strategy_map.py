"""
StrategyMap — 策略地图（即时缓存层，v7.0）

职责：
    - 维护驱动力场状态对之间的最优表达映射
    - 记录每次消力路径（from_state → to_state → expression）
    - 泛化触发器：当某路径在 >=2 个不同情境下验证 >=3 次时，升格为 wm_rule

设计原则：
    - 参数外置：min_contexts、upgrade_threshold 从 param_snapshot 读取
    - 衰减机制：长期未使用的路径缓慢衰减
    - 升级接口：调用外置 wm_db 接口，不直接依赖世界模型实现
"""

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class StrategyEntry:
    """
    单条策略地图条目。

    属性：
        expression        : 最省力的表达
        quenching_efficiency: 该表达的消力效率
        hit_count        : 命中次数
        last_used        : 上次使用时间戳
        contexts         : 出现过的情境集合（用于泛化判断）
        from_state       : 起始驱动力场哈希
        to_state         : 目标驱动力场哈希
    """
    expression: str
    quenching_efficiency: float
    hit_count: int = 0
    last_used: float = 0.0
    contexts: Set[str] = field(default_factory=set)
    from_state: str = ""
    to_state: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expression": self.expression,
            "quenching_efficiency": self.quenching_efficiency,
            "hit_count": self.hit_count,
            "last_used": self.last_used,
            "contexts": list(self.contexts),
            "from_state": self.from_state,
            "to_state": self.to_state,
        }


class StrategyMap:
    """
    策略地图：驱动力场状态对 → 最优表达。

    用法：
        strategy_map.record_path(state_A, state_B, "嗯", 0.6, "对话开场")
        best = strategy_map.get_best_path(state_A, state_B)
        strategy_map.check_generalization(wm_db)  # 触发泛化升格
    """

    def __init__(self) -> None:
        # {(from_state_hash, to_state_hash): StrategyEntry}
        self._map: Dict[tuple, StrategyEntry] = {}
        # 泛化触发器降级记录（防止同一路径反复触发）
        self._upgraded_paths: Set[tuple] = set()

    # -------------------------------------------------------------------------
    # 记录
    # -------------------------------------------------------------------------

    def record_path(
        self,
        state_A: Dict[str, float],
        state_B: Dict[str, float],
        expression: str,
        efficiency: float,
        context_label: str,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录（或更新）一条消力路径。

        参数：
            state_A       : 表达前的驱动力场
            state_B       : 表达后的驱动力场
            expression    : 实际说出的表达
            efficiency    : 消力效率
            context_label: 情境标签（用于判断泛化条件）
        """
        from_hash = self._hash_state(state_A)
        to_hash = self._hash_state(state_B)
        key = (from_hash, to_hash)

        now = time.time()
        if key in self._map:
            entry = self._map[key]
            entry.hit_count += 1
            entry.last_used = now
            entry.contexts.add(context_label)
            # 效率指数移动平均
            entry.quenching_efficiency = 0.7 * entry.quenching_efficiency + 0.3 * efficiency
        else:
            entry = StrategyEntry(
                expression=expression,
                quenching_efficiency=efficiency,
                hit_count=1,
                last_used=now,
                contexts={context_label},
                from_state=from_hash,
                to_state=to_hash,
            )
            self._map[key] = entry

    def get_best_path(
        self,
        state_A: Dict[str, float],
        state_B: Dict[str, float],
    ) -> Optional[StrategyEntry]:
        """查询从 A 到 B 的最优表达。"""
        key = (self._hash_state(state_A), self._hash_state(state_B))
        return self._map.get(key)

    def get(
        self,
        drive_state: Dict[str, float],
    ) -> Optional[StrategyEntry]:
        """
        给定当前驱动力场，返回最匹配的策略条目。

        匹配策略：查找 (current_state, *) 模式的条目，取 hit_count 最高的。
        """
        current_hash = self._hash_state(drive_state)
        candidates = [
            entry
            for (fhash, _), entry in self._map.items()
            if fhash == current_hash
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.hit_count * e.quenching_efficiency)

    def get_all_for_state(self, drive_state: Dict[str, float]) -> List[StrategyEntry]:
        """返回某状态出发的所有条目（按效率降序）。"""
        current_hash = self._hash_state(drive_state)
        candidates = [
            entry
            for (fhash, _), entry in self._map.items()
            if fhash == current_hash
        ]
        candidates.sort(key=lambda e: e.quenching_efficiency, reverse=True)
        return candidates

    # -------------------------------------------------------------------------
    # 衰减
    # -------------------------------------------------------------------------

    def decay(self, decay_rate: float = 0.001) -> int:
        """
        长期未使用的路径缓慢衰减效率。

        参数：
            decay_rate: 每轮衰减系数

        返回：
            衰减的条目数量
        """
        now = time.time()
        decayed = 0
        stale_paths: List[tuple] = []

        for key, entry in self._map.items():
            # 超过 1 小时未使用才衰减
            if now - entry.last_used > 3600:
                entry.quenching_efficiency *= (1.0 - decay_rate)
                if entry.quenching_efficiency < 0.01:
                    stale_paths.append(key)
                decayed += 1

        # 删除完全失效的路径
        for key in stale_paths:
            del self._map[key]

        return decayed

    # -------------------------------------------------------------------------
    # 泛化触发器
    # -------------------------------------------------------------------------

    def check_generalization(
        self,
        wm_db: Optional[Any] = None,
        param_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        检查所有路径，触发泛化升格。

        升格条件：
            1. hit_count >= min_contexts（默认 3）
            2. len(contexts) >= 2（至少 2 个不同情境）
            3. quenching_efficiency >= upgrade_threshold（默认 0.70）

        升格后：
            - 调用 upgrade_to_wm_rule() 将路径写入世界模型
            - 从 _map 中移除该路径（已升级为持久知识）
            - 记录到 _upgraded_paths（防止重复升级）

        参数：
            wm_db         : 世界模型数据库实例（必须提供）
            param_snapshot: 参数快照

        返回：
            List[Dict]：所有升格成功的规则
        """
        if wm_db is None:
            logger.warning("[StrategyMap] check_generalization called without wm_db, skipping")
            return []

        min_contexts = 3
        upgrade_threshold = 0.70
        if param_snapshot is not None:
            min_contexts = int(param_snapshot.get("language.quenching.min_contexts", 3))
            upgrade_threshold = float(param_snapshot.get("language.quenching.upgrade_threshold", 0.70))

        upgraded = []
        keys_to_remove: List[tuple] = []

        for key, entry in self._map.items():
            if key in self._upgraded_paths:
                continue

            if (
                entry.hit_count >= min_contexts
                and len(entry.contexts) >= 2
                and entry.quenching_efficiency >= upgrade_threshold
            ):
                rule = self._upgrade_to_wm_rule(entry, wm_db)
                if rule:
                    upgraded.append(rule)
                    self._upgraded_paths.add(key)
                    keys_to_remove.append(key)
                    logger.info(
                        f"[StrategyMap] Upgraded path: {entry.expression} "
                        f"(hits={entry.hit_count}, contexts={list(entry.contexts)}, "
                        f"efficiency={entry.quenching_efficiency:.3f})"
                    )

        for key in keys_to_remove:
            del self._map[key]

        return upgraded

    def _upgrade_to_wm_rule(self, entry: StrategyEntry, wm_db: Any) -> Optional[Dict[str, Any]]:
        """
        将策略条目升格为 wm_rule，写入世界模型。

        参数：
            entry  : StrategyEntry
            wm_db  : 世界模型数据库实例

        返回：
            写入的规则 dict，失败时返回 None
        """
        try:
            rule = {
                "type": "language_strategy",
                "from_state": entry.from_state,
                "to_state": entry.to_state,
                "expression": entry.expression,
                "efficiency": entry.quenching_efficiency,
                "contexts": list(entry.contexts),
                "confidence": min(1.0, entry.hit_count / 10),
            }
            wm_db[:] = [
                r for r in wm_db
                if not (
                    r.get("type") == "language_strategy"
                    and r.get("from_state") == rule["from_state"]
                    and r.get("to_state") == rule["to_state"]
                )
            ]
            wm_db.append(rule)
            return rule
        except Exception as e:
            logger.warning(f"[StrategyMap] upgrade_to_wm_rule failed: {e}")
            return None

    # -------------------------------------------------------------------------
    # 辅助方法
    # -------------------------------------------------------------------------

    @staticmethod
    def _hash_state(state: Dict[str, float]) -> str:
        """将驱动力场状态离散化为字符串哈希（与 QuenchingTracker 保持一致）。v11.1: 沉寂维度 0.1 桶。"""
        _COARSE = ["L", "ML", "M", "MH", "H"]
        _FINE = ["vL","L","LM","M","MH","H","H+","VH","VH+","MAX"]
        _FINE_KEYS = {"danger_level", "fatigue", "stress", "pain", "unresolved", "relief_debt"}
        parts = []
        for key in sorted(state.keys()):
            val = state[key]
            if not isinstance(val, (int, float)):
                continue
            if key in _FINE_KEYS:
                bucket = min(int(val / 0.1), 9)
                parts.append(f"{key}={_FINE[bucket]}")
            else:
                bucket = min(int(val / 0.2), 4)
                parts.append(f"{key}={_COARSE[bucket]}")
        return "|".join(parts)

    # -------------------------------------------------------------------------
    # 序列化
    # -------------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """序列化（供 EntityCore 持久化）。"""
        return {
            "map": {
                f"{k[0]}->{k[1]}": entry.to_dict()
                for k, entry in self._map.items()
            },
            "upgraded_paths": [f"{k[0]}->{k[1]}" for k in self._upgraded_paths],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StrategyMap":
        """从 dict 恢复。"""
        smap = cls()
        for key_str, entry_data in data.get("map", {}).items():
            parts = key_str.split("->")
            if len(parts) == 2:
                key = (parts[0], parts[1])
                entry = StrategyEntry(
                    expression=str(entry_data.get("expression", "")),
                    quenching_efficiency=float(entry_data.get("quenching_efficiency", 0.0)),
                    hit_count=int(entry_data.get("hit_count", 0)),
                    last_used=float(entry_data.get("last_used", 0.0)),
                    contexts=set(entry_data.get("contexts", [])),
                    from_state=str(entry_data.get("from_state", "")),
                    to_state=str(entry_data.get("to_state", "")),
                )
                smap._map[key] = entry
        for key_str in data.get("upgraded_paths", []):
            parts = key_str.split("->")
            if len(parts) == 2:
                smap._upgraded_paths.add((parts[0], parts[1]))
        return smap
