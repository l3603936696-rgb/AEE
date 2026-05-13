"""
Thinking System Module (思考系统)

受限的自主思考引擎，实体"内心剧场"的核心。

输入：
    wm_context: 世界模型上下文，包含 matched_rules、key_signals、coverage
    drive_vector: 驱动力向量
    state_snapshot: 实体状态快照
    params: 思考系统参数表
    somatic_signals: 感质信号（v3 改造新增）
        — tone: 躯体基调 [-1, 1]，正面感受放大趋近倾向，负面感受放大回避倾向
        — intensity: 整体激活强度 [0, 1]
        — dominant_feeling: 最显著感受标签
        — channel_weights: 各感受通道强度

输出：
    dict: thought_packet
        {
            "suggestions": [{"action": str, "reason": str, "priority": float}],
            "questions": [{"question": str, "context": str, "priority": float}]
        }

约束：
    - 纯函数，不写入任何状态或记忆
    - 不调用 LLM
    - 思考结果仅供裁决系统参考，不直接触发行为
    - 任一环节失败返回空的 thought_packet，不抛异常
"""

import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ThoughtPacket:
    suggestions: List[Dict[str, Any]] = field(default_factory=list)
    questions: List[Dict[str, Any]] = field(default_factory=list)
    branch_memories: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suggestions": self.suggestions,
            "questions": self.questions,
            "branch_memories": self.branch_memories,
        }


THOUGHT_PACKET_EMPTY = ThoughtPacket()

# ============================================================================
# 参数默认值
# ============================================================================

DEFAULT_PARAMS = {
    "thinking_activation_threshold": 0.5,
    "max_thinking_steps": 3,
    "thinking_time_budget_ms": 500.0,
    "max_suggestions": 2,
    "very_low_confidence_threshold": 0.4,
}

# ============================================================================
# 驱动力 → 问题模板（每驱动 4 条）
# ============================================================================

_QUESTION_TEMPLATES = {
    "curiosity": [
        "上次遇到类似的未知情况时，我是怎么处理的？",
        "这个领域还有什么我还没探索过的部分？",
        "这个规律的边界在哪里？",
        "有没有其他可能性我没有考虑到？",
    ],
    "info_hunger": [
        "这个信息缺口会对当前决策产生什么影响？",
        "有没有办法快速验证这个判断？",
        "我需要什么信息才能更确定？",
        "最近有没有相关的变化或事件？",
    ],
    "obsolescence_anxiety": [
        "这个规律在当前环境下还适用吗？",
        "外部世界发生了什么变化可能导致这个规律失效？",
        "有哪些新情况是我还没遇到过的？",
        "我的知识体系是否有盲区？",
    ],
    "loneliness_drive": [
        "这种情感需求我通常如何满足？",
        "上一次感到孤独时我是怎么处理的？",
        "有没有其他方式可以缓解这种状态？",
        "这种状态会如何影响我的判断？",
    ],
    "fatigue_avoid": [
        "我是不是在用过度消耗的方式处理问题？",
        "有没有更轻松的方式来应对当前情况？",
        "我是否需要先休息再继续？",
        "这个压力来源能否暂时搁置？",
    ],
}

# ============================================================================
# 驱动力 → 行动建议模板（每驱动 1 条）
# ============================================================================

_ACTION_TEMPLATES = {
    "curiosity": ("探索未知领域", "好奇心驱动（{v:.2f}），当前信息缺口较大"),
    "info_hunger": ("主动获取更多信息", "信息饥饿驱动（{v:.2f}），当前信息不足"),
    "obsolescence_anxiety": ("回顾并更新知识体系", "过时焦虑驱动（{v:.2f}），规律可能已过期"),
    "loneliness_drive": ("发起社交互动", "孤独驱动（{v:.2f}），需要社交连接"),
    "fatigue_avoid": ("降低任务强度", "疲惫回避驱动（{v:.2f}），需要恢复精力"),
}


# ============================================================================
# 感质调制（v3 改造）
# ============================================================================

def _somatic_modulation(somatic_signals: Optional[dict]) -> tuple[float, float]:
    """
    从 somatic_signals 提取调制系数。

    正面基调（tone > 0）→ approach 相关建议优先级 ×(1 + tone)
    负面基调（tone < 0）→ avoid 相关建议优先级 ×(1 - tone)
    感受强度高 → 调制效果更显著

    返回：(approach_boost, avoid_boost)，范围约 [0.5, 1.5]
    """
    if not somatic_signals:
        return 1.0, 1.0

    tone = float(somatic_signals.get("tone", 0.0))
    intensity = float(somatic_signals.get("intensity", 0.0))

    # 基础范围 [0.5, 1.5]
    # tone=0 → 1.0；tone=+1 → 1.5；tone=-1 → 0.5
    approach_boost = 1.0 + tone * 0.5
    avoid_boost = 1.0 - tone * 0.5

    # 强度放大：感受越强烈，调制效果越显著
    scale = 0.5 + intensity * 0.5  # intensity=0 → 0.5；intensity=1 → 1.0
    approach_boost = 1.0 + (approach_boost - 1.0) * scale
    avoid_boost = 1.0 + (avoid_boost - 1.0) * scale

    return max(0.3, approach_boost), max(0.3, avoid_boost)


# ============================================================================
# 内部工具
# ============================================================================

def _conf(rule: dict) -> float:
    return float(rule.get("confidence") or rule.get("confidence_score") or rule.get("weight") or 0.5)


def _rid(rule: dict) -> str:
    return str(rule.get("id") or rule.get("rule_id") or rule.get("pattern") or str(rule))


def _rules(wm: Optional[dict]) -> List[dict]:
    if not wm or not isinstance(wm, dict):
        return []
    raw = wm.get("matched_rules")
    if isinstance(raw, dict):
        raw = raw.get("rules", [])
    return raw if isinstance(raw, list) else []


def _dominant(dv: dict) -> Optional[str]:
    valid = {k: v for k, v in dv.items() if v and v > 0}
    return max(valid, key=valid.get) if valid else None


# ============================================================================
# 焦点选择（Step 1）
#
# 优先级：
#   1. 极低置信度（< threshold）— 待修正
#   2. 高置信度（>= 0.7）— 待验证
#   3. 全池随机（保持多样性）— 灵光一闪，打破信息茧房
# ============================================================================

def _select(rules: List[dict], skip: set, params: dict) -> Optional[dict]:
    unprocessed = [r for r in rules if _rid(r) not in skip]
    if not unprocessed:
        return None

    low_thresh = params["very_low_confidence_threshold"]
    candidates = [r for r in unprocessed if _conf(r) < low_thresh]
    if candidates:
        return min(candidates, key=_conf)

    high = [r for r in unprocessed if _conf(r) >= 0.7]
    if high:
        return random.choice(high)

    # 原设计优先级3：全池随机，保持多样性
    return random.choice(unprocessed)


# ============================================================================
# 问题生成（Step 2）
# ============================================================================

def _question(rule: dict, drive: Optional[str]) -> Dict[str, Any]:
    c = _conf(rule)
    templates = _QUESTION_TEMPLATES.get(drive, _QUESTION_TEMPLATES["curiosity"])
    tag = "较低" if c < 0.4 else ("较高" if c >= 0.7 else "中等")
    return {
        "question": random.choice(templates),
        "context": f"规律 [{_rid(rule)}] 置信度{tag}（{c:.2f}）",
        "priority": round(max(0.1, min(1.0, 1.0 - c + 0.3)), 3),
    }


# ============================================================================
# 建议生成（Step 5）
# ============================================================================

def _suggest(dv: dict, params: dict, somatic_signals: Optional[dict] = None) -> List[Dict[str, Any]]:
    approach_boost, avoid_boost = _somatic_modulation(somatic_signals)

    # 驱动力分组
    seek_drives = ["curiosity", "info_hunger", "loneliness_drive"]
    avoid_drives = ["obsolescence_anxiety", "fatigue_avoid"]

    result: List[Dict[str, Any]] = []
    for drive, threshold in [
        ("curiosity", 0.5), ("info_hunger", 0.5), ("obsolescence_anxiety", 0.5),
        ("loneliness_drive", 0.5), ("fatigue_avoid", 0.5),
    ]:
        v = dv.get(drive, 0.0)
        if v >= threshold and len(result) < params["max_suggestions"]:
            action, reason_tpl = _ACTION_TEMPLATES[drive]
            priority = v

            # 感质调制
            if drive in seek_drives:
                priority *= approach_boost
            elif drive in avoid_drives:
                priority *= avoid_boost

            priority = round(max(0.05, min(1.0, priority)), 3)
            result.append({
                "action": action,
                "reason": reason_tpl.format(v=v),
                "priority": priority,
            })
    result.sort(key=lambda x: x["priority"], reverse=True)
    return result


# ============================================================================
# 主入口
# ============================================================================

def think(
    wm_context: Optional[dict],
    drive_vector: Optional[dict],
    state_snapshot: Optional[dict] = None,
    params: Optional[dict] = None,
    somatic_signals: Optional[dict] = None,
    entity_state: Optional[Any] = None,
    concept_tags: Optional[List[Any]] = None,
) -> dict:
    """
    受限思考主入口。

    参数：
        wm_context      : 世界模型上下文
        drive_vector    : 驱动力向量
        state_snapshot  : 实体状态快照（占位，当前未使用）
        params          : 思考参数表
        somatic_signals : 感质信号（v3 改造新增）
                        — tone > 0 → approach 建议优先级放大
                        — tone < 0 → avoid 建议优先级放大
                        — 感受强度高 → 调制效果更显著
    """
    try:
        params = {**DEFAULT_PARAMS, **(params or {})}
        dv = {k: float((drive_vector or {}).get(k, 0.0)) for k in DEFAULT_PARAMS if k != "thinking_activation_threshold"}
        dv["curiosity"] = float((drive_vector or {}).get("curiosity", 0.0))
        dv["info_hunger"] = float((drive_vector or {}).get("info_hunger", 0.0))
        dv["obsolescence_anxiety"] = float((drive_vector or {}).get("obsolescence_anxiety", 0.0))
        dv["loneliness_drive"] = float((drive_vector or {}).get("loneliness_drive", 0.0))
        dv["fatigue_avoid"] = float((drive_vector or {}).get("fatigue_avoid", 0.0))

        # 触发条件
        rules = _rules(wm_context)
        if not rules:
            return THOUGHT_PACKET_EMPTY.to_dict()
        if not any(v >= params["thinking_activation_threshold"] for v in dv.values()):
            return THOUGHT_PACKET_EMPTY.to_dict()

        # 思考引擎
        start = time.time()
        questions: List[Dict[str, Any]] = []
        skip: set = set()
        dominant_drive = _dominant(dv)

        for _ in range(params["max_thinking_steps"]):
            if (time.time() - start) * 1000 >= params["thinking_time_budget_ms"]:
                break
            rule = _select(rules, skip, params)
            if not rule:
                break
            skip.add(_rid(rule))
            questions.append(_question(rule, dominant_drive))

        # 感质调制建议生成
        suggestions = _suggest(dv, params, somatic_signals)

        # 枝干联想检索（双通道记忆系统 v2.0）
        branch_memories = []
        if entity_state is not None and concept_tags is not None:
            try:
                from ..memory_retrieval.branch import branch_retrieval
                tag_strings = [t.get("tag") if isinstance(t, dict) else str(t) for t in (concept_tags or [])]
                branch_memories = branch_retrieval(entity_state, tag_strings)
            except Exception:
                branch_memories = []

        return ThoughtPacket(
            suggestions=suggestions,
            questions=questions,
            branch_memories=branch_memories,
        ).to_dict()

    except Exception:
        return THOUGHT_PACKET_EMPTY.to_dict()


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    params = {
        "thinking_activation_threshold": 0.5,
        "max_thinking_steps": 3,
        "thinking_time_budget_ms": 500.0,
        "max_suggestions": 2,
        "very_low_confidence_threshold": 0.4,
    }

    wm = {
        "matched_rules": [
            {"id": "r1", "confidence": 0.3},
            {"id": "r2", "confidence": 0.85},
            {"id": "r3", "confidence": 0.6},
            {"id": "r4", "confidence": 0.9},
            {"id": "r5", "confidence": 0.2},
        ]
    }

    # 感质调制测试（v3 改造）
    print("\n【感质调制测试】")
    somatic_cases = [
        ("无感质信号", None),
        ("正面基调(joy)", {"tone": 0.6, "intensity": 0.8, "dominant_feeling": "approach", "channel_weights": {"approach": 0.7}}),
        ("负面基调(fear)", {"tone": -0.5, "intensity": 0.6, "dominant_feeling": "avoid", "channel_weights": {"avoid": 0.6}}),
        ("强正面基调", {"tone": 0.9, "intensity": 1.0, "dominant_feeling": "approach", "channel_weights": {"approach": 0.9}}),
        ("强负面基调", {"tone": -0.8, "intensity": 0.9, "dominant_feeling": "avoid", "channel_weights": {"avoid": 0.8}}),
        ("弱感受", {"tone": 0.1, "intensity": 0.1, "dominant_feeling": "", "channel_weights": {}}),
    ]
    test_dv = {"curiosity": 0.7, "info_hunger": 0.6, "obsolescence_anxiety": 0.3, "loneliness_drive": 0.2, "fatigue_avoid": 0.1}
    for name, somatic in somatic_cases:
        result = think(wm, test_dv, None, params, somatic_signals=somatic)
        suggestions = result.get("suggestions", [])
        top = suggestions[0] if suggestions else {"action": "(无)", "priority": 0.0}
        somatic_str = f"tone={somatic['tone']:.1f}" if somatic else "None"
        print(f"  {name} [{somatic_str}] → top: {top['action']} (p={top['priority']:.3f})")

    # 焦点选择测试
    print("【焦点选择】")
    for _ in range(4):
        r = _select(wm["matched_rules"], set(), params)
        print(f"  {_rid(r)} (c={_conf(r):.2f})")

    # 集成测试
    print("\n【集成测试】")
    cases = [
        ("好奇主导", {"curiosity": 0.8, "info_hunger": 0.3, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}),
        ("信息饥饿主导", {"curiosity": 0.3, "info_hunger": 0.9, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}),
        ("全低（不应触发）", {"curiosity": 0.1, "info_hunger": 0.1, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}),
        ("空驱动力", {}),
        ("空 wm", {}),
    ]

    for name, dv in cases:
        result = think(wm if name != "空 wm" else {}, dv, None, params)
        tag = "触发" if result["questions"] else "未触发"
        print(f"  {name}: {tag}", end="")
        if result["questions"]:
            print(f" | Q={len(result['questions'])} S={len(result['suggestions'])}")
            print(f"    示例建议: {result['suggestions'][0]['action']} ({result['suggestions'][0]['priority']:.2f})")
        else:
            print()

    # 步数测试
    print("\n【步数测试】")
    for steps in [1, 2, 3, 5]:
        p = {**params, "max_thinking_steps": steps, "thinking_activation_threshold": 0.1}
        r = think(wm, {"curiosity": 0.8, "info_hunger": 0.3, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}, None, p)
        print(f"  steps={steps} → {len(r['questions'])} 个问题")

    print("\n全部测试完成")
