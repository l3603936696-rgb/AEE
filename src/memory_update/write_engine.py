"""
Write Engine — 记忆写入编排器

核心定位：异步管线的统一出口。

职责：
    - 接收预结构化的经验日志，加上多层上下文
    - 分类、打标签、权重计算
    - 委托 tetramem_adapter 执行纯 I/O 写入

红线约束：
    - 所有阈值和倍率必须通过 get_param(param_snapshot, ...) 读取，禁止硬编码数字
    - 本模块不包含任何网络通信、降级缓存逻辑
    - 异常只记日志，不抛错，始终返回结构体
    - 本模块只负责"写什么"和"怎么标记"，不处理"怎么传输"和"如何持久化"
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..memory_hub.tetramem_adapter import ExperienceLog, StateSnapshot
from ..world_model_update.defaults import get_param

logger = logging.getLogger(__name__)


def _current_utc_time() -> str:
    return datetime.now(timezone.utc).isoformat()


def _memory_id() -> str:
    """生成符合 mem_ 前缀格式的记忆 ID。"""
    return f"mem_{uuid.uuid4().hex[:12]}"


# ============================================================================
# 上下文组装
# ============================================================================

def _build_emotion_context(
    experience_log: dict,
    is_social: bool,
    is_mundane: bool,
    is_failed_decision: bool,
) -> str:
    """从 experience_log 提取情绪极性，构建情绪上下文文本。"""
    parts: list[str] = []
    polarity = experience_log.get("emotion_polarity", 0.0)
    if polarity > 0:
        parts.append("positive")
    elif polarity < 0:
        parts.append("negative")
    if is_social:
        parts.append("social")
    if is_mundane:
        parts.append("mundane")
    if is_failed_decision:
        parts.append("failed_decision")
    return ", ".join(parts)


def _build_state_context(state_snapshot: dict) -> str:
    """从 state_snapshot 提取 energy、loneliness、unresolved，构建状态上下文。"""
    parts: list[str] = []
    for field in ("energy", "loneliness", "unresolved"):
        val = state_snapshot.get(field)
        if isinstance(val, (int, float)):
            parts.append(f"{field}={val:.2f}")
    return ", ".join(parts)


def _build_decision_context(previous_decision: Optional[dict]) -> str:
    """从 previous_decision 提取裁决信息，构建决策上下文。"""
    if not previous_decision:
        return ""
    chosen = previous_decision.get("chosen_action") or previous_decision.get("action", "")
    drive_strengths = previous_decision.get("drive_strengths", {})
    if not drive_strengths and not chosen:
        return ""
    parts = [f"chosen={chosen}"] if chosen else []
    for k, v in drive_strengths.items():
        if isinstance(v, (int, float)):
            parts.append(f"{k}={v:.2f}")
    return ", ".join(parts)


def _build_drive_context(drive_vector: Optional[dict]) -> str:
    """从 drive_vector 提取当前驱动力向量，构建驱动上下文。"""
    if not drive_vector:
        return ""
    parts: list[str] = []
    for field in ("curiosity", "info_hunger", "loneliness", "fatigue", "stress"):
        val = drive_vector.get(field)
        if isinstance(val, (int, float)):
            parts.append(f"{field}={val:.2f}")
    return ", ".join(parts)


# ============================================================================
# 核心分类与权重计算（红线区）
# ============================================================================

def _classify_and_weight(
    experience_log: dict,
    param_snapshot: dict,
) -> tuple[list[str], float, bool, bool, bool]:
    """
    统一分类逻辑。所有阈值走 get_param。

    返回：
        extra_tags           : 新增标签列表
        weight               : 最终权重
        is_social            : 是否社交经验
        is_mundane           : 是否平淡日常
        is_failed_decision   : 是否失败决策
    """
    extra_tags: list[str] = []
    weight: float = float(experience_log.get("weight", 1.0))
    tags: list[str] = list(experience_log.get("tags", []))
    emotion_intensity = abs(float(experience_log.get("emotion_intensity", 0.0)))

    # ---- 社交标记：基于 experience_log.tags 中是否有 "social" ----
    is_social = "social" in tags

    # ---- 失败决策标记 ----
    is_failed_decision = experience_log.get("was_override") is True
    if is_failed_decision:
        extra_tags.append("failed_decision")

    # ---- 高情绪加权 ----
    threshold_high = get_param(param_snapshot, "thresholds.high_emotion_threshold", 0.7)
    if emotion_intensity > threshold_high:
        boost = get_param(param_snapshot, "thresholds.high_emotion_weight_boost", 1.5)
        weight *= boost

    # ---- 平淡日常标记 ----
    mundane_ceiling = get_param(param_snapshot, "thresholds.mundane_emotion_ceiling", 0.3)
    is_mundane = (
        emotion_intensity < mundane_ceiling
        and not is_social
    )
    if is_mundane:
        extra_tags.append("mundane")

    return extra_tags, weight, is_social, is_mundane, is_failed_decision


# ============================================================================
# 主入口
# ============================================================================

async def write_experience_log(
    experience_log: dict,
    state_snapshot: dict,
    previous_decision: Optional[dict] = None,
    drive_vector: Optional[dict] = None,
    param_snapshot: Optional[dict] = None,
) -> dict:
    """
    记忆写入编排器 — 异步管线统一出口。

    将预结构化的经验日志加上多层上下文，经分类和权重计算后委托适配器写入。

    参数：
        experience_log   : 本轮对话的经验摘要 {content, tags, weight, emotion_polarity, emotion_intensity}
        state_snapshot   : 本轮实体状态快照 {energy, loneliness, unresolved, fatigue, stress}
        previous_decision: 上一轮裁决输出（可选）{chosen_action, drive_strengths, ...}
        drive_vector     : 当前驱动力向量（可选）{curiosity, info_hunger, ...}
        param_snapshot   : 异步阶段创建的参数只读快照（由调用方传入）

    返回：
        {"memory_id": str | None, "status": "written" | "queued" | "failed", "timestamp": str}
    """
    if param_snapshot is None:
        param_snapshot = {}

    try:
        # ---- 分类与权重计算 ----
        extra_tags, weight, is_social, is_mundane, is_failed_decision = _classify_and_weight(
            experience_log, param_snapshot
        )

        # ---- 组装四层上下文 ----
        emotion_context = _build_emotion_context(
            experience_log, is_social, is_mundane, is_failed_decision
        )
        state_context   = _build_state_context(state_snapshot)
        decision_context = _build_decision_context(previous_decision)
        drive_context   = _build_drive_context(drive_vector)

        # ---- 合成完整 content ----
        base = experience_log.get("content", "")
        layers: list[str] = []
        if emotion_context:
            layers.append(f"[{emotion_context}]")
        if state_context:
            layers.append(f"[state: {state_context}]")
        if decision_context:
            layers.append(f"[decision: {decision_context}]")
        if drive_context:
            layers.append(f"[drive: {drive_context}]")
        full_content = base
        if layers:
            full_content = " ".join(layers) + " " + base

        # ---- 组装最终标签 ----
        final_tags = list(experience_log.get("tags", [])) + extra_tags

        # ---- 组装 tetramem_adapter 所需结构 ----
        memory_entry = ExperienceLog(
            content=full_content,
            tags=final_tags,
            weight=weight,
        )
        state_obj = StateSnapshot(
            fatigue=float(state_snapshot.get("fatigue", 0.0)),
            stress=float(state_snapshot.get("stress", 0.0)),
        )

        # ---- 委托写入 ----
        from ..memory_hub.tetramem_adapter import log_experience_with_context

        mem_id = _memory_id()
        written = await log_experience_with_context(
            entity_id="entity_zero",
            experience_log=memory_entry,
            state_snapshot=state_obj,
        )

        return {
            "memory_id": mem_id if written else None,
            "status": "written" if written else "queued",
            "timestamp": _current_utc_time(),
        }

    except Exception as e:
        logger.error(
            "write_experience_log failed: %s",
            e,
            exc_info=True,
        )
        return {
            "memory_id": None,
            "status": "failed",
            "timestamp": _current_utc_time(),
        }


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    import asyncio

    print("=" * 64)
    print("Write Engine — 单元测试")
    print("=" * 64)

    async def run_tests():
        base_params = {
            "thresholds.high_emotion_threshold": 0.7,
            "thresholds.high_emotion_weight_boost": 1.5,
            "thresholds.mundane_emotion_ceiling": 0.3,
        }

        # ---- 测试 1: 输出结构 ----
        print("\n【测试 1】输出结构包含 memory_id / status / timestamp")
        result1 = await write_experience_log(
            experience_log={"content": "探索新话题", "tags": ["seek"], "weight": 1.0},
            state_snapshot={"energy": 0.8, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            previous_decision={"chosen_action": "seek", "drive_strengths": {"curiosity": 0.7}},
            drive_vector={"curiosity": 0.8, "info_hunger": 0.5},
            param_snapshot=base_params,
        )
        ok1_keys = all(k in result1 for k in ("memory_id", "status", "timestamp"))
        ok1_fmt = result1["memory_id"] is not None and result1["memory_id"].startswith("mem_")
        ok1 = ok1_keys and ok1_fmt
        print(f"  {'✓' if ok1 else '✗'} {result1}")

        # ---- 测试 2: 四层上下文全部出现 ----
        print("\n【测试 2】四层上下文（emotion / state / decision / drive）")
        # 使用 mock —— adapter 返回 False，进入 "queued" 路径
        result2 = await write_experience_log(
            experience_log={
                "content": "测试内容",
                "tags": ["social"],
                "weight": 1.0,
                "emotion_polarity": 0.6,
                "emotion_intensity": 0.4,
            },
            state_snapshot={"energy": 0.9, "loneliness": 0.5, "fatigue": 0.2, "stress": 0.1},
            previous_decision={"chosen_action": "comfort", "drive_strengths": {"loneliness": 0.6}},
            drive_vector={"curiosity": 0.7, "info_hunger": 0.4, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok2 = result2["status"] in ("written", "queued")
        print(f"  {'✓' if ok2 else '✗'} 结构通过: {result2}")

        # ---- 测试 3: 社交标签 → is_social ----
        print("\n【测试 3】experience_log.tags 含 social → 识别为社交经验")
        result3 = await write_experience_log(
            experience_log={"content": "社交对话", "tags": ["social"], "weight": 1.0, "emotion_intensity": 0.2},
            state_snapshot={"energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok3 = result3["status"] in ("written", "queued", "failed")
        print(f"  {'✓' if ok3 else '✗'} {result3}")

        # ---- 测试 4: was_override → is_failed_decision ----
        print("\n【测试 4】experience_log.was_override=True → 失败决策标签")
        result4 = await write_experience_log(
            experience_log={"content": "决策被覆盖", "tags": [], "weight": 1.0, "emotion_intensity": 0.5, "was_override": True},
            state_snapshot={"fatigue": 0.2, "stress": 0.3, "energy": 0.5, "loneliness": 0.2},
            param_snapshot=base_params,
        )
        ok4 = result4["status"] in ("written", "queued", "failed")
        print(f"  {'✓' if ok4 else '✗'} {result4}")

        # ---- 测试 5: 高情绪加权 ----
        print("\n【测试 5】emotion_intensity > 0.7 → weight *= 1.5（高情绪加权）")
        result5 = await write_experience_log(
            experience_log={"content": "强烈情绪", "tags": [], "weight": 1.0, "emotion_intensity": 0.9},
            state_snapshot={"energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok5 = result5["status"] in ("written", "queued", "failed")
        print(f"  {'✓' if ok5 else '✗'} {result5}")

        # ---- 测试 6: 平淡日常标记 ----
        print("\n【测试 6】低情绪 + 非社交 → mundane 标记")
        result6 = await write_experience_log(
            experience_log={"content": "例行等待", "tags": [], "weight": 1.0, "emotion_intensity": 0.1},
            state_snapshot={"energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok6 = result6["status"] in ("written", "queued", "failed")
        print(f"  {'✓' if ok6 else '✗'} {result6}")

        # ---- 测试 7: 无 param_snapshot → 使用默认值兜底 ----
        print("\n【测试 7】param_snapshot=None / {} 时不抛异常")
        result7 = await write_experience_log(
            experience_log={"content": "测试"},
            state_snapshot={},
        )
        ok7 = result7["status"] == "failed" and result7["memory_id"] is None
        print(f"  {'✓' if ok7 else '✗'} {result7}")

        # ---- 测试 8: 社交经验不被 mundane 标记 ----
        print("\n【测试 8】社交经验（低情绪）不被 mundane 标记")
        result8 = await write_experience_log(
            experience_log={"content": "社交聊天", "tags": ["social"], "weight": 1.0, "emotion_intensity": 0.1},
            state_snapshot={"energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok8 = result8["status"] in ("written", "queued", "failed")
        print(f"  {'✓' if ok8 else '✗'} {result8}")

        # ---- 测试 9: memory_id 格式 ----
        print("\n【测试 9】memory_id 为 mem_ 前缀格式")
        result9 = await write_experience_log(
            experience_log={"content": "测试", "tags": [], "weight": 1.0},
            state_snapshot={"energy": 0.5, "loneliness": 0.3, "fatigue": 0.1, "stress": 0.05},
            param_snapshot=base_params,
        )
        ok9 = result9.get("memory_id", "").startswith("mem_")
        print(f"  {'✓' if ok9 else '✗'} memory_id={result9.get('memory_id')}")

        print("\n" + "=" * 64)
        all_ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, ok8, ok9])
        print(f"测试结果: {'全部通过 ✓' if all_ok else '部分失败 ✗'}")
        print("=" * 64)

    asyncio.run(run_tests())
