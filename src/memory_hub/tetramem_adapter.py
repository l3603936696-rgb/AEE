"""
TetraMem Adapter — 外部记忆服务适配器

设计原则（核心原则：状态驱动，禁止时钟驱动）：
    - 所有操作跟随"经验流"或"动作流"，而非时钟
    - 绝对禁止任何形式的定时器、周期性任务、硬编码触发条件
    - 任一模块失败必须可跳过，不阻断主循环

环境依赖：
    - TetraMem 服务运行于 http://localhost:8100
    - docker-compose.yml 中已设置 TETRAMEM_DISABLE_REGULATION=true
      （禁用 TetraMem 自带内分泌调节，由 insula_hub 全权负责）

降级策略：
    - 经验沉淀：TetraMem 不可用时降级写 data/memories_staged.json
    - 拓扑指标：TetraMem 不可用时返回 TopoMetrics() 默认值
    - 记忆检索：TetraMem 不可用时降级读 memories_staged.json

子模块：
    tetramem_persistence.py — 降级持久层（本地 JSON 读写）
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

from src.memory_hub.tetramem_persistence import (
    MEMORIES_STAGED_PATH,
    _load_staged,
    _retrieve_from_staged,
    _normalize_tetramem_results,
)

import logging
logger = logging.getLogger(__name__)

TETRAMEM_BASE_URL = "http://localhost:8100"


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ExperienceLog:
    """经验日志结构（用于 log_experience_with_context）。"""
    content: str = ""
    tags: List[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass
class StateSnapshot:
    """状态快照（用于 log_experience_with_context）。"""
    fatigue: float = 0.0
    stress: float = 0.0


@dataclass
class TopoMetrics:
    """TetraMem 拓扑健康度指标。"""
    topological_entropy: float = 0.0
    betti_numbers: List[int] = field(default_factory=list)
    persistent_entropy: float = 0.0
    cycle_complexity: float = 0.0
    connected_components: int = 1

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TopoMetrics":
        if not isinstance(data, dict):
            return cls()
        return cls(
            topological_entropy=float(data.get("topological_entropy", 0.0)),
            betti_numbers=list(data.get("betti_numbers", [])),
            persistent_entropy=float(data.get("persistent_entropy", 0.0)),
            cycle_complexity=float(data.get("cycle_complexity", 0.0)),
            connected_components=int(data.get("connected_components", 1)),
        )


# ============================================================================
# HTTP 辅助
# ============================================================================

async def _post(endpoint: str, payload: Dict[str, Any]) -> bool:
    """向 TetraMem POST 数据，失败返回 False（不抛异常）。"""
    if not _HTTPX_AVAILABLE:
        logger.warning("httpx not available, skipping TetraMem POST to %s", endpoint)
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{TETRAMEM_BASE_URL}{endpoint}",
                json=payload,
            )
            return response.status_code == 200
    except Exception as e:
        logger.warning("TetraMem POST %s failed: %s", endpoint, e)
        return False


async def _get(endpoint: str) -> Optional[Dict[str, Any]]:
    """从 TetraMem GET 数据，失败返回 None（不抛异常）。"""
    if not _HTTPX_AVAILABLE:
        logger.warning("httpx not available, skipping TetraMem GET from %s", endpoint)
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{TETRAMEM_BASE_URL}{endpoint}")
            if response.status_code == 200:
                return response.json()
            return None
    except Exception as e:
        logger.warning("TetraMem GET %s failed: %s", endpoint, e)
        return None


# ============================================================================
# 核心 API
# ============================================================================

async def log_experience_with_context(
    entity_id: str,
    experience_log: ExperienceLog,
    state_snapshot: StateSnapshot,
) -> bool:
    """
    经验沉淀：将经验及其生理背景打包写入 TetraMem。

    降级策略：
        - TetraMem 可用 → 写入远程服务
        - TetraMem 不可用 → 降级写入 data/memories_staged.json
        - 降级写也失败 → 记日志，不抛异常
    """
    payload = {
        "entity_id": entity_id,
        "content": experience_log.content,
        "labels": experience_log.tags,
        "weight": experience_log.weight,
        "context_state": {
            "fatigue": state_snapshot.fatigue,
            "stress": state_snapshot.stress,
        },
    }
    written = await _post("/api/v1/experiences", payload)
    if written:
        return True
    return await _fallback_write(entity_id, experience_log, state_snapshot)


async def _fallback_write(
    entity_id: str,
    experience_log: ExperienceLog,
    state_snapshot: StateSnapshot,
) -> bool:
    """降级写入本地 memories_staged.json。"""
    entry = {
        "entity_id": entity_id,
        "content": experience_log.content,
        "tags": experience_log.tags,
        "weight": experience_log.weight,
        "state": {
            "fatigue": state_snapshot.fatigue,
            "stress": state_snapshot.stress,
        },
        "status": "staged",
    }
    entries = _load_staged()
    entries.append(entry)
    if len(entries) > 500:
        entries = entries[-500:]
    from src.memory_hub.tetramem_persistence import _save_staged
    _save_staged(entries)
    logger.info(f"[TetraMemAdapter] Fallback write: {experience_log.content[:50]}")
    return True


async def execute_sleep_cycle(
    entity_id: str,
    current_residue: float,
) -> float:
    """
    做梦的执行器。

    此函数不负责决定何时做梦。
    它是"睡觉"这个行为的物理执行器。
    何时调用，由 V4 的状态池（如 fatigue > 0.9）在决策层决定。
    """
    await _post("/api/v1/dreaming/trigger", {
        "entity_id": entity_id,
        "trigger_type": "sleep_action",
    })
    return current_residue * 0.95


async def get_topology_metrics() -> TopoMetrics:
    """读取 TetraMem 当前拓扑健康度指标。"""
    raw = await _get("/api/v1/topology/metrics")
    if raw is None:
        return TopoMetrics()
    return TopoMetrics.from_dict(raw)


async def retrieve_memories(
    intent: str,
    emotion: float,
    limit: int = 5,
    entity_id: str = "entity_zero",
) -> List[Dict[str, Any]]:
    """
    检索与当前情境相关的结构化记忆。

    优先从 TetraMem 检索（若服务可用），降级读 memories_staged.json。
    """
    raw = await _get(f"/api/v1/memories/retrieve?entity_id={entity_id}&intent={intent}&limit={limit}")
    if raw and isinstance(raw, list) and len(raw) > 0:
        return _normalize_tetramem_results(raw)
    return _retrieve_from_staged(intent, emotion, limit)


# ============================================================================
# 模拟模式兜底（向后兼容）
# ============================================================================

async def log_experience_fallback(
    entity_id: str,
    content: str,
    tags: List[str],
    state: Dict[str, float],
) -> bool:
    """模拟模式写入：将经验打印到日志，不抛异常。仅在 TetraMem 服务不可用时使用。"""
    logger.info(
        "[TetraMem Fallback] entity=%s content=%s tags=%s state=%s",
        entity_id, content, tags, state
    )
    return True


async def get_topology_metrics_fallback() -> TopoMetrics:
    """模拟模式读取：返回默认拓扑指标。仅在 TetraMem 服务不可用时使用。"""
    return TopoMetrics(
        topological_entropy=0.0,
        betti_numbers=[1, 0, 0],
        persistent_entropy=0.0,
        cycle_complexity=0.0,
        connected_components=1,
    )
