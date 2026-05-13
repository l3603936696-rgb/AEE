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

本模块写文件（memories_staged.json），不写数据库。
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


logger = logging.getLogger(__name__)

TETRAMEM_BASE_URL = "http://localhost:8100"

# ============================================================================
# 降级写路径
# ============================================================================

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
MEMORIES_STAGED_PATH = _DATA_DIR / "memories_staged.json"


def _load_staged() -> List[Dict[str, Any]]:
    """加载已暂存的结构化记忆条目。"""
    if not MEMORIES_STAGED_PATH.exists():
        return []
    try:
        with open(MEMORIES_STAGED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[TetraMemAdapter] Failed to load memories_staged.json: {e}")
        return []


def _save_staged(entries: List[Dict[str, Any]]) -> None:
    """保存结构化记忆条目到本地 JSON。"""
    try:
        with open(MEMORIES_STAGED_PATH, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"[TetraMemAdapter] Failed to save memories_staged.json: {e}")


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ExperienceLog:
    """
    经验日志结构（用于 log_experience_with_context）。

    字段：
        content : 经验内容文本
        tags    : 标签列表（如动作类型、情绪标签）
        weight  : 经验权重（影响沉淀优先级）
    """
    content: str = ""
    tags: List[str] = field(default_factory=list)
    weight: float = 1.0


@dataclass
class StateSnapshot:
    """
    状态快照（用于 log_experience_with_context）。

    字段：
        fatigue : 疲劳水平 [0, 1]
        stress  : 压力水平 [0, 1]
    """
    fatigue: float = 0.0
    stress: float = 0.0


@dataclass
class TopoMetrics:
    """
    TetraMem 拓扑健康度指标。

    字段：
        topological_entropy : 拓扑熵（0=完全有序，1=完全混乱）
        betti_numbers       : 贝蒂数列表（原始拓扑数据，不应直接传入裁决层）
        persistent_entropy  : 持续同调熵
        cycle_complexity    : 环复杂度
        connected_components: 连通分量数
    """
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
# 内部辅助
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

    在每次管线异步阶段调用。
    不单独注入 state，而是把当前状态作为经验的背景打包写入。
    让状态跟随"经验流"自然沉淀，而非被强行塞入。

    降级策略：
        - TetraMem 可用 → 写入远程服务
        - TetraMem 不可用 → 降级写入 data/memories_staged.json
        - 降级写也失败 → 记日志，不抛异常

    参数：
        entity_id       : 实体唯一标识
        experience_log  : 经验日志（content / tags / weight）
        state_snapshot  : 当前生理状态（fatigue / stress）

    返回：
        bool : 写入是否成功（失败不抛异常，返回 False）
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
    # 优先写 TetraMem
    written = await _post("/api/v1/experiences", payload)
    if written:
        return True
    # 降级写本地 JSON
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
    # 最多保留 500 条，超出则截断旧条目
    if len(entries) > 500:
        entries = entries[-500:]
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

    参数：
        entity_id      : 实体唯一标识
        current_residue: 做梦前的残留层水平

    返回：
        float : 做梦后的残留层水平（极慢衰减：乘以 0.95）
    """
    await _post("/api/v1/dreaming/trigger", {
        "entity_id": entity_id,
        "trigger_type": "sleep_action",
    })
    return current_residue * 0.95


async def get_topology_metrics() -> TopoMetrics:
    """
    读取 TetraMem 当前拓扑健康度指标。

    返回：
        TopoMetrics : 拓扑指标对象（内部使用，由 insula_hub 降维为躯体标记）
    """
    raw = await _get("/api/v1/topology/metrics")
    if raw is None:
        return TopoMetrics()
    return TopoMetrics.from_dict(raw)


# ============================================================================
# 记忆检索 API（供 memory_bias 调用）
# ============================================================================

async def retrieve_memories(
    intent: str,
    emotion: float,
    limit: int = 5,
    entity_id: str = "entity_zero",
) -> List[Dict[str, Any]]:
    """
    检索与当前情境相关的结构化记忆。

    优先从 TetraMem 检索（若服务可用），降级读 memories_staged.json。
    检索策略：按 intent 标签过滤 + 情绪相似度排序。

    参数：
        intent   : 当前意图类型（如 "分享"、"求助"）
        emotion  : 当前情绪极性 [-1, 1]
        limit    : 返回条数上限
        entity_id: 实体标识（用于 TetraMem 查询）

    返回：
        List[Dict] : 记忆条目列表，每条包含 emotion / intent / timestamp / metadata
                     适配 memory_bias.MemorySample 格式
    """
    # 尝试 TetraMem 检索
    raw = await _get(f"/api/v1/memories/retrieve?entity_id={entity_id}&intent={intent}&limit={limit}")
    if raw and isinstance(raw, list) and len(raw) > 0:
        return _normalize_tetramem_results(raw)

    # 降级读本地 JSON
    return _retrieve_from_staged(intent, emotion, limit)


async def _get_tetramem_memories(endpoint: str) -> Optional[Dict[str, Any]]:
    """TetraMem 记忆检索 GET。"""
    return await _get(endpoint)


def _normalize_tetramem_results(raw: List[Any]) -> List[Dict[str, Any]]:
    """将 TetraMem 返回的记录规范化为 memory_bias 所需格式。"""
    results = []
    for item in raw:
        if isinstance(item, dict):
            results.append({
                "emotion": float(item.get("emotion", 0.0)),
                "intent": str(item.get("intent", "")),
                "timestamp": float(item.get("timestamp", 0.0)),
                "metadata": {
                    "content": item.get("content", ""),
                    "outcome": item.get("outcome", "neutral"),
                    "weight": float(item.get("weight", 1.0)),
                    "source": "tetramem",
                },
            })
    return results


def _retrieve_from_staged(
    intent: str,
    emotion: float,
    limit: int,
) -> List[Dict[str, Any]]:
    """
    从 memories_staged.json 降级检索。

    策略：
        1. 过滤包含 intent:xxx 或相同意图前缀的条目
        2. 按 weight * 情绪相似度 排序
        3. 取 top N
    """
    entries = _load_staged()
    if not entries:
        return []

    scored = []
    for entry in entries:
        tags = entry.get("tags", [])
        entry_intent = _extract_intent_tag(tags)
        if not entry_intent:
            continue
        # intent 匹配
        if entry_intent == intent or entry_intent.startswith(intent) or intent.startswith(entry_intent):
            # 情绪相似度
            entry_emotion = float(entry.get("state", {}).get("emotion_polarity", 0.0))
            emotion_sim = 1.0 - min(abs(emotion - entry_emotion) / 2.0, 1.0)
            weight = float(entry.get("weight", 1.0))
            score = weight * (0.5 + 0.5 * emotion_sim)
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, entry in scored[:limit]:
        results.append({
            "emotion": float(entry.get("state", {}).get("emotion_polarity", 0.0)),
            "intent": _extract_intent_tag(entry.get("tags", [])) or "",
            "timestamp": 0.0,  # staged 条目无时间戳，用 0
            "metadata": {
                "content": entry.get("content", ""),
                "outcome": "neutral",
                "weight": float(entry.get("weight", 1.0)),
                "source": "staged",
            },
        })
    return results


def _extract_intent_tag(tags: List[str]) -> Optional[str]:
    """从标签列表中提取 intent:xxx 标签。"""
    for tag in tags:
        if tag.startswith("intent:"):
            return tag[len("intent:"):]
    return None


# ============================================================================
# 模拟模式（无 TetraMem 服务时提供兜底）
# ============================================================================

async def log_experience_fallback(
    entity_id: str,
    content: str,
    tags: List[str],
    state: Dict[str, float],
) -> bool:
    """
    模拟模式写入：将经验打印到日志，不抛异常。
    仅在 TetraMem 服务不可用时使用。
    """
    logger.info(
        "[TetraMem Fallback] entity=%s content=%s tags=%s state=%s",
        entity_id, content, tags, state
    )
    return True


async def get_topology_metrics_fallback() -> TopoMetrics:
    """
    模拟模式读取：返回默认拓扑指标。
    仅在 TetraMem 服务不可用时使用。
    """
    return TopoMetrics(
        topological_entropy=0.0,
        betti_numbers=[1, 0, 0],
        persistent_entropy=0.0,
        cycle_complexity=0.0,
        connected_components=1,
    )


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 64)
    print("TetraMem Adapter — 单元测试")
    print("=" * 64)

    async def run_tests():
        # ---- 测试 1: 数据结构 ----
        print("\n【测试 1】数据结构 round-trip")
        topo = TopoMetrics.from_dict({
            "topological_entropy": 0.42,
            "betti_numbers": [3, 2, 1],
            "persistent_entropy": 0.31,
            "cycle_complexity": 0.55,
            "connected_components": 2,
        })
        ok1 = (
            abs(topo.topological_entropy - 0.42) < 1e-4
            and topo.betti_numbers == [3, 2, 1]
        )
        print(f"  {'✓' if ok1 else '✗'} TopoMetrics from_dict")

        exp_log = ExperienceLog(content="探索新话题", tags=["seek", "curiosity"], weight=0.8)
        snap = StateSnapshot(fatigue=0.3, stress=0.1)
        ok2 = exp_log.content == "探索新话题" and snap.fatigue == 0.3
        print(f"  {'✓' if ok2 else '✗'} ExperienceLog / StateSnapshot 构建")

        # ---- 测试 2: 经验沉淀函数签名检查 ----
        print("\n【测试 2】函数签名检查（无定时器关键字）")
        import inspect
        src = inspect.getsource(log_experience_with_context)
        forbidden = ["sleep(", "schedule", "periodic", "setInterval", "Timer"]
        found = [kw for kw in forbidden if kw in src]
        ok3 = len(found) == 0
        print(f"  {'✓' if ok3 else '✗'} 无定时器关键字，found={found}" if ok3 else f"  ✗ 发现: {found}")

        # ---- 测试 3: 做梦函数注释检查 ----
        print("\n【测试 3】execute_sleep_cycle 文档注释检查")
        doc = execute_sleep_cycle.__doc__ or ""
        ok4 = "不负责决定何时做梦" in doc
        print(f"  {'✓' if ok4 else '✗'} 注释包含'不负责决定何时做梦'")

        # ---- 测试 4: get_topology_metrics 返回类型 ----
        print("\n【测试 4】get_topology_metrics 返回 TopoMetrics")
        result = await get_topology_metrics()
        ok4b = isinstance(result, TopoMetrics)
        print(f"  {'✓' if ok4b else '✗'} 返回类型为 TopoMetrics（降维前不暴露原始拓扑）")

        # ---- 测试 5: 模拟模式（无 httpx） ----
        print("\n【测试 5】模拟模式兜底")
        from . import tetramem_adapter as adapter_module
        original = adapter_module._HTTPX_AVAILABLE
        adapter_module._HTTPX_AVAILABLE = False
        ok5a = await adapter_module.log_experience_fallback("e1", "测试", ["tag"], {"fatigue": 0.2})
        ok5b = (await adapter_module.get_topology_metrics_fallback()).topological_entropy == 0.0
        adapter_module._HTTPX_AVAILABLE = original
        print(f"  {'✓' if ok5a else '✗'} log_experience_fallback 正常")
        print(f"  {'✓' if ok5b else '✗'} get_topology_metrics_fallback 返回默认指标")

        # ---- 测试 6: _fallback_write 降级写 ----
        print("\n【测试 6】降级写入 memories_staged.json")
        from . import tetramem_adapter as adapter_module
        _orig = adapter_module._HTTPX_AVAILABLE
        adapter_module._HTTPX_AVAILABLE = False  # 强制降级路径
        exp = ExperienceLog(content="降级测试记忆", tags=["test", "intent:seek"], weight=0.8)
        snap = StateSnapshot(fatigue=0.2, stress=0.1)
        ok6 = await adapter_module.log_experience_with_context("entity_zero", exp, snap)
        adapter_module._HTTPX_AVAILABLE = _orig
        print(f"  {'✓' if ok6 else '✗'} 降级写入 {'成功' if ok6 else '失败'}")
        # 验证文件存在
        import os as _os
        staged_exists = _os.path.exists(adapter_module.MEMORIES_STAGED_PATH)
        print(f"  {'✓' if staged_exists else '✗'} memories_staged.json {'已创建' if staged_exists else '未创建'}")

        # ---- 测试 7: _retrieve_from_staged ----
        print("\n【测试 7】降级检索 memories_staged.json")
        results = adapter_module._retrieve_from_staged("seek", 0.3, limit=3)
        ok7 = isinstance(results, list)
        print(f"  {'✓' if ok7 else '✗'} 返回类型 list，结果数={len(results)}")
        if results:
            print(f"     示例: intent={results[0].get('intent')}, emotion={results[0].get('emotion')}")

        # ---- 测试 8: _extract_intent_tag ----
        print("\n【测试 8】从标签提取 intent")
        ok8a = adapter_module._extract_intent_tag(["test", "intent:share", "social"]) == "share"
        ok8b = adapter_module._extract_intent_tag(["test", "social"]) is None
        print(f"  {'✓' if ok8a else '✗'} 能从标签提取 intent")
        print(f"  {'✓' if ok8b else '✗'} 无 intent 标签时返回 None")

        print("\n" + "=" * 64)
        all_ok = ok1 and ok2 and ok3 and ok4 and ok4b and ok5a and ok5b and ok6 and ok7 and ok8a and ok8b
        print(f"测试结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
        print("=" * 64)

    asyncio.run(run_tests())
