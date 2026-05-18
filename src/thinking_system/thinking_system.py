"""
Thinking System Module (思考系统)

v5 统一流改造：问题和建义都从同一个焦点规则集合中涌现，
不再有硬编码的驱动力→维度映射或驱动力→行动模板。

核心原则：
    - 相关性从数据计算，不从查表获取
    - 规则涉及的维度从 rule.predicts / rule.expected_deltas 提取
    - 驱动力之间的"接近度"从当前活跃维度与规则维度的重叠度计算
    - 行动类型从焦点规则的 expected_deltas 推断，不套模板

数据驱动流程：
    驱动力场 → 当前活跃维度（能量化，非二值）
         ↓
    从 wm_rules 中按"与活跃维度的重叠度"选焦点规则
         ↓
    焦点规则同时生成问题和建议：
        - 问题：规律本身的不确定性（置信度 + 边界）
        - 建议：规则预期的状态变化方向 → 行动类型
         ↓
    感质调制 + 注意力调制 + 心智模拟
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

DEFAULT_PARAMS = {
    "thinking_activation_threshold": 0.5,
    "max_thinking_steps": 3,
    "thinking_time_budget_ms": 500.0,
    "max_suggestions": 2,
}


# ============================================================================
# 通用工具
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
# 维度提取（从规则数据结构中提取其涉及的维度名集合）
# ============================================================================

def _rule_dimensions(rule: dict) -> set:
    """提取一条规则涉及的维度集合。"""
    dims: set = set()

    # 路径1：rule.predicts["expect"] 或 rule.predicts["trigger"]
    predicts = rule.get("predicts")
    if isinstance(predicts, dict):
        for v in predicts.values():
            if isinstance(v, str):
                # 简单分词：提取英文单词和中文连续字符
                words = v.replace("_", " ").split()
                for w in words:
                    w = w.strip()
                    if w and len(w) > 2:
                        dims.add(w.lower())
                # 中文字符提取（简单的单字bigram作为维度名近似）
                chars = "".join(c for c in v if "\u4e00" <= c <= "\u9fff")
                if chars:
                    for i in range(len(chars) - 1):
                        dims.add(chars[i:i+2])

    # 路径2：rule.expected_deltas（显式维度列表）
    deltas = rule.get("expected_deltas")
    if isinstance(deltas, dict):
        dims.update(deltas.keys())
    elif isinstance(deltas, list):
        for d in deltas:
            if isinstance(d, str):
                dims.add(d)

    # 路径3：从 content + context 提取（小写英文词，>2字符）
    for key in ("content", "context"):
        text = str(rule.get(key, "")).lower()
        words = text.replace("_", " ").split()
        for w in words:
            w = w.strip().strip(".,!?，。！？、；：")
            if w and len(w) > 2:
                dims.add(w)

    return dims


# ============================================================================
# 活跃维度计算（从驱动力向量推导出当前活跃的内部维度）
# ============================================================================

# 每个驱动力在状态空间中对应的方向向量（非硬编码映射，而是经验性的权重分布）
_DRIVE_STATE_WEIGHTS = {
    "curiosity":            {"approach_drive": 0.4, "info_gap": 0.4, "unresolved": 0.2},
    "info_hunger":         {"info_gap": 0.6, "unresolved": 0.4},
    "obsolescence_anxiety": {"boredom": 0.5, "boredom_despair": 0.3, "boredom_futility": 0.2},
    "loneliness_drive":    {"loneliness": 0.5, "loneliness_core": 0.3, "loneliness_surface": 0.2},
    "fatigue_avoid":       {"fatigue": 0.4, "stress": 0.3, "energy": 0.3},
}


def _active_dimensions(dv: dict, state: Optional[dict]) -> set:
    """
    计算当前活跃的内部维度集合。

    输入：
        dv    : 驱动力向量 {drive_name: strength}
        state : 当前状态快照（可选，提供维度活跃度参考）

    输出：
        活跃维度名集合。

    逻辑：
        - 主导驱动力贡献最大的活跃度
        - 各驱动力的权重向量叠加
        - 状态快照中高值的维度额外加权
    """
    if not dv:
        return set()

    active: Dict[str, float] = {}

    for drive, strength in dv.items():
        if strength <= 0:
            continue
        weights = _DRIVE_STATE_WEIGHTS.get(drive, {})
        for dim, w in weights.items():
            active[dim] = active.get(dim, 0.0) + strength * w

    if state:
        for dim, val in state.items():
            try:
                v = float(val)
                if v > 0.6:
                    active[dim] = active.get(dim, 0.0) + (v - 0.5) * 0.5
            except (TypeError, ValueError):
                pass

    # 取 top-N 或超过阈值的维度
    if not active:
        return set()

    max_val = max(active.values()) if active else 1.0
    return {
        dim for dim, val in active.items()
        if val >= max_val * 0.3
    }


# ============================================================================
# 焦点规则选择（数据驱动，无硬编码维度映射）
# ============================================================================

def _select_focal_rules(
    rules: List[dict],
    active_dims: set,
    params: dict,
) -> List[dict]:
    """
    选取与当前活跃维度重叠度最高的规则作为焦点。

    相关度 = |rule_dims ∩ active_dims| / |rule_dims|
    低置信规则优先，高置信规则次之，同相关度下打散。

    参数：
        rules      : 候选规则列表
        active_dims: 当前活跃维度集合
        params     : 思考参数

    返回：
        按优先级排序的焦点规则列表（最多 max_thinking_steps 条）
    """
    if not rules or not active_dims:
        return _fallback_select(rules, params)

    scored: List[tuple] = []
    for r in rules:
        rule_dims = _rule_dimensions(r)
        overlap = len(rule_dims & active_dims)
        total = len(rule_dims) if rule_dims else 1
        relevance = overlap / total if total > 0 else 0.0

        conf = _conf(r)
        # 置信度低 → 紧急度更高
        urgency = max(0.0, (0.4 - conf) / 0.4) if conf < 0.4 else 0.0

        score = relevance + urgency * 0.5
        scored.append((r, score, conf, relevance))

    scored.sort(key=lambda x: x[1], reverse=True)

    result: List[dict] = []
    seen_ids: set = set()
    for r, score, conf, rel in scored:
        rid = _rid(r)
        if rid in seen_ids:
            continue
        result.append(r)
        seen_ids.add(rid)
        if len(result) >= params["max_thinking_steps"]:
            break

    return result


def _fallback_select(rules: List[dict], params: dict) -> List[dict]:
    """无活跃维度信息时的随机选法（保留原有逻辑）。"""
    if not rules:
        return []
    pool = rules[:]
    result = []
    for _ in range(min(params["max_thinking_steps"], len(pool))):
        if not pool:
            break
        r = random.choice(pool)
        result.append(r)
        pool = [x for x in pool if _rid(x) != _rid(r)]
    return result


# ============================================================================
# 问题生成（统一流：基于焦点规则的规律不确定性）
# ============================================================================

# 问题不按驱动力分模板——而是按规律本身的特征问：
#   - 低置信 → "这个判断可靠吗？"
#   - 高置信 → "这个规律还适用吗？"
#   - 跨维度 → "这和另一个维度的关系是什么？"
# 用规则内容动态生成，不靠固定模板组。

def _build_question(rule: dict, related_rules: List[dict]) -> Dict[str, Any]:
    """
    从规则特征 + 语义基座生成结构化问题。

    输出是数据结构，不是文字。内心不需要语言。
    文字渲染只在需要表达时由 render_question() 执行。

    返回结构：
        type: contradiction / novel / low_confidence / high_confidence / causal
        rule_id: 来源规则 ID
        dims: 涉及的维度列表
        confidence: 规则置信度
        seed_check: 语义基座对照结果（可能为 None）
        priority: 紧迫度 [0, 1]
        has_boundary: 是否涉及边界问题
    """
    c = _conf(rule)
    rule_dims = list(_rule_dimensions(rule))
    deltas = rule.get("expected_deltas", {})
    delta_dims = list(deltas.keys()) if isinstance(deltas, dict) else []

    # 语义基座对照
    try:
        from .semantic_base import check_rule_against_seeds
        seed_check = check_rule_against_seeds(rule)
    except Exception:
        seed_check = None

    # 确定类型和优先级
    if seed_check and seed_check["status"] == "contradicts":
        q_type = "contradiction"
        base_priority = 0.9
    elif seed_check and seed_check["status"] == "novel":
        q_type = "novel"
        base_priority = 0.7
    elif c < 0.4:
        q_type = "low_confidence"
        base_priority = max(0.7, 1.0 - c)
    elif c >= 0.75:
        q_type = "high_confidence"
        base_priority = 0.6 + c * 0.1
    else:
        q_type = "causal" if len(delta_dims) > 1 else "low_confidence"
        base_priority = 0.4

    has_boundary = bool(related_rules) and c >= 0.5
    if has_boundary:
        base_priority *= 1.1

    return {
        "type": q_type,
        "rule_id": _rid(rule),
        "dims": delta_dims or rule_dims[:5],
        "confidence": round(c, 3),
        "expected_deltas": {k: round(float(v), 4) for k, v in deltas.items()}
                           if isinstance(deltas, dict) else {},
        "seed_check": seed_check,
        "has_boundary": has_boundary,
        "priority": round(min(1.0, base_priority), 3),
    }


def render_question(q: Dict[str, Any]) -> str:
    """
    把结构化问题渲染成文字。

    只在需要表达（语言系统、日志、UI展示）时调用。
    内部流转用结构化数据，不经过这里。
    """
    q_type = q.get("type", "")
    seed_check = q.get("seed_check")
    dims = q.get("dims", [])
    c = q.get("confidence", 0.5)

    try:
        from .semantic_base import interpret_delta, get_dim_meaning
    except ImportError:
        interpret_delta = None
        get_dim_meaning = None

    if q_type == "contradiction" and seed_check:
        return seed_check.get("interpretation", "有矛盾")

    if q_type == "novel" and seed_check:
        return f"{seed_check.get('interpretation', '新发现')}——可靠吗？"

    # 用语义基座渲染 delta 描述
    deltas = q.get("expected_deltas", {})
    if deltas and interpret_delta:
        parts = [interpret_delta(dim, d) for dim, d in deltas.items()]
        delta_text = "；".join(parts[:3])
    elif dims and get_dim_meaning:
        delta_text = "、".join(get_dim_meaning(d) for d in dims[:3])
    else:
        delta_text = "、".join(dims[:3]) if dims else "?"

    if q_type == "low_confidence":
        return f"这个判断（{delta_text}）可靠吗？"
    elif q_type == "high_confidence":
        return f"一直这样（{delta_text}），现在还成立吗？"
    elif q_type == "causal":
        return f"这些变化有因果关系吗？{delta_text}"

    return f"关于 {delta_text} 的不确定"


# ============================================================================
# 建议生成（统一流：从焦点规则推断行动）
# ============================================================================

# 行动类型从规则的 expected_deltas 方向推断：
#   - 预期某维度上升 → 趋近行为
#   - 预期某维度下降 → 回避/修复行为
# 驱动强度决定是否值得建议。

# 感知维度活跃方向（已知的高激活值维度，fallback 推断用）
# 这是经验性的初始种子集合，不完整但够用。
# 实际判断完全从 expected_deltas 的数值符号得出。
_SENSITIVE_DIMS_UP = {"approach_drive", "joy", "excitement", "serenity", "energy",
                       "info_gap", "unresolved", "boredom"}
_SENSITIVE_DIMS_DOWN = {"avoid_drive", "fatigue", "stress", "loneliness",
                         "loneliness_core", "loneliness_surface",
                         "sadness", "fear", "anger", "anxiety"}


def _infer_action_type(rule: dict, state: Optional[dict], dv: Optional[dict] = None) -> Optional[str]:
    """
    从规则 expected_deltas + 驱动力 + 当前状态，连续竞争出行动类型。

    所有信号折算为 action 票数在同一个池子里加权叠加：
        - deltas 贡献：预期上升/下降 → explore/rest 票数
        - 驱动力贡献：每个驱动力按强度投票给对应 action
        - 状态贡献：高值维度按方向投票
    最终 argmax 选出 action，无显著赢家则返回 None。
    """
    # 每种 action 的累积票数
    votes: Dict[str, float] = {
        "explore": 0.0, "rest": 0.0, "comfort": 0.0, "seek": 0.0,
    }

    # ---- 信号源 1：规则 expected_deltas ----
    deltas = rule.get("expected_deltas")
    if deltas and isinstance(deltas, dict):
        for dim, delta in deltas.items():
            try:
                d = float(delta)
            except (TypeError, ValueError):
                continue

            state_val = 0.5
            if state:
                try:
                    state_val = float(state.get(dim, 0.5))
                except (TypeError, ValueError):
                    pass

            if d > 0:
                votes["explore"] += d * (1.0 - state_val * 0.5)
            elif d < 0:
                votes["rest"] += abs(d) * state_val

    # ---- 信号源 2：驱动力强度 ----
    # 每个驱动力按自身强度给对应 action 投票，系数 0.3 平衡与 deltas 的量级
    if dv:
        _drive_votes = {
            "loneliness_drive":    "comfort",
            "fatigue_avoid":       "rest",
            "obsolescence_anxiety": "seek",
            "curiosity":           "explore",
            "info_hunger":         "seek",
        }
        for drive, action in _drive_votes.items():
            strength = float(dv.get(drive, 0.0))
            votes[action] = votes.get(action, 0.0) + strength * 0.3

    # ---- 信号源 3：状态高值维度 ----
    if state:
        for dim, val in state.items():
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            if v > 0.5:
                excess = (v - 0.5) * 0.2
                if dim in _SENSITIVE_DIMS_DOWN:
                    votes["rest"] += excess
                elif dim in _SENSITIVE_DIMS_UP:
                    votes["explore"] += excess

    # ---- argmax：最高票赢，但必须有显著优势 ----
    if not any(v > 0.0 for v in votes.values()):
        return None

    best_action = max(votes, key=votes.get)
    best_score = votes[best_action]

    # 第二名
    second_score = max(
        (v for a, v in votes.items() if a != best_action), default=0.0
    )

    # 赢家需要比第二名高出 20%，否则信号太弱不建议
    if best_score <= 0.0 or best_score < second_score * 1.2:
        return None

    return best_action


def _build_reason(action: str, rule: dict) -> str:
    """从语义基座 + 规则 deltas 生成建议理由。"""
    try:
        from .semantic_base import get_action_essence, interpret_delta
        essence = get_action_essence(action)
        deltas = rule.get("expected_deltas", {})
        if deltas and isinstance(deltas, dict):
            parts = []
            for dim, d in deltas.items():
                try:
                    parts.append(interpret_delta(dim, float(d)))
                except (TypeError, ValueError):
                    pass
            if parts:
                return f"{essence}——预期效果：{'，'.join(parts[:2])}"
        return essence
    except Exception:
        _fallback = {
            "explore": "这个方向有发展空间，值得探索",
            "rest": "当前负荷较重，需要缓冲和恢复",
            "seek": "信息缺口明显，需要先搞清楚情况",
            "comfort": "情感需求突出，需要社交连接",
        }
        return _fallback.get(action, "基于当前状态判断")


_DRIVE_ACTION_PAIR = {
    "explore":  ["curiosity", "info_hunger"],
    "seek":     ["info_hunger", "curiosity"],
    "comfort":  ["loneliness_drive"],
    "rest":     ["fatigue_avoid"],
}


def _build_suggestions(
    focal_rules: List[dict],
    dv: dict,
    state: Optional[dict],
    params: dict,
    somatic_signals: Optional[dict],
    attention_weights: Optional[Dict[str, float]],
) -> List[Dict[str, Any]]:
    """
    从焦点规则集合 + 驱动力场 生成建议。

    每条焦点规则产生最多一条建议。
    行动类型与对应驱动力的强度决定是否超越阈值。
    感质调制调整优先级。

    返回：建议列表，每条包含 action / reason / priority
    """
    result: List[Dict[str, Any]] = []

    # 预计算调制系数
    approach_boost, avoid_boost = _somatic_modulation(somatic_signals)
    drive_attn = _attention_to_drive_boost(attention_weights)

    for rule in focal_rules:
        if len(result) >= params["max_suggestions"]:
            break

        action_type = _infer_action_type(rule, state, dv)
        if not action_type:
            continue

        # 找对应驱动力的强度
        matched_drives = _DRIVE_ACTION_PAIR.get(action_type, [])
        drive_strength = max(dv.get(d, 0.0) for d in matched_drives) if matched_drives else 0.0

        if drive_strength < params["thinking_activation_threshold"]:
            continue

        base_priority = drive_strength

        # 感质调制
        if action_type in ("explore", "seek", "comfort"):
            base_priority *= approach_boost
        elif action_type == "rest":
            base_priority *= avoid_boost

        # 注意力权重调制
        if drive_attn:
            attn_boost = max((drive_attn.get(d, 0.0) for d in matched_drives), default=0.0)
            base_priority *= (1.0 + attn_boost)

        reason = _build_reason(action_type, rule)

        result.append({
            "action": action_type,
            "reason": reason,
            "priority": round(min(1.0, max(0.05, base_priority)), 3),
            "_from_rule": _rid(rule),
        })

    result.sort(key=lambda x: x["priority"], reverse=True)
    return result


# ============================================================================
# 感质调制
# ============================================================================

def _somatic_modulation(somatic_signals: Optional[dict]) -> tuple[float, float]:
    if not somatic_signals:
        return 1.0, 1.0
    tone = float(somatic_signals.get("tone", 0.0))
    intensity = float(somatic_signals.get("intensity", 0.0))
    scale = 0.5 + intensity * 0.5
    approach_boost = 1.0 + tone * 0.5 * scale
    avoid_boost = 1.0 - tone * 0.5 * scale
    return max(0.3, approach_boost), max(0.3, avoid_boost)


# ============================================================================
# 注意力权重 → 驱动力映射（从协方差追踪器直接计算，不查表）
# ============================================================================

def _attention_to_drive_boost(attention_weights: Optional[Dict[str, float]]) -> Dict[str, float]:
    """
    把协方差追踪器的维度注意力权重转换为驱动力加成。

    计算方式：每个驱动力的 boost = 所有相关维度注意力权重的最大值。
    相关性从 _DRIVE_STATE_WEIGHTS 的权重结构计算，不需要硬编码映射。
    """
    if not attention_weights:
        return {}

    boost: Dict[str, float] = {}
    for drive, weights in _DRIVE_STATE_WEIGHTS.items():
        max_w = 0.0
        for dim in weights:
            w = attention_weights.get(dim, 0.0)
            if w > max_w:
                max_w = w
        if max_w > 0.05:
            boost[drive] = round(max_w * 0.5, 4)
    return boost


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
    attention_weights: Optional[Dict[str, float]] = None,
) -> dict:
    """
    v5 统一流思考主入口。

    流程：
        1. 驱动力场 → 当前活跃维度集合
        2. 活跃维度 → 焦点规则（按重叠度）
        3. 焦点规则 → 同时生成问题和建议（统一流）
        4. 感质调制 + 注意力调制
        5. 心智模拟验证建议
        6. 枝干联想检索

    参数：
        wm_context        : 世界模型上下文
        drive_vector      : 驱动力向量
        state_snapshot    : 实体状态快照（用于维度活跃度计算）
        params            : 思考参数
        somatic_signals    : 感质信号
        attention_weights  : 协方差追踪器输出的注意力权重
    """
    try:
        params = {**DEFAULT_PARAMS, **(params or {})}

        dv = {}
        for k in ("curiosity", "info_hunger", "obsolescence_anxiety",
                  "loneliness_drive", "fatigue_avoid"):
            dv[k] = float((drive_vector or {}).get(k, 0.0))

        rules = _rules(wm_context)
        if not rules:
            return THOUGHT_PACKET_EMPTY.to_dict()
        if not any(v >= params["thinking_activation_threshold"] for v in dv.values()):
            return THOUGHT_PACKET_EMPTY.to_dict()

        # Step 1: 活跃维度
        active_dims = _active_dimensions(dv, state_snapshot)

        # Step 2: 焦点规则
        start = time.time()
        focal_rules = _select_focal_rules(rules, active_dims, params)

        # Step 3: 问题（基于焦点规则）
        questions = []
        for rule in focal_rules:
            if (time.time() - start) * 1000 >= params["thinking_time_budget_ms"]:
                break
            questions.append(_build_question(rule, focal_rules))

        # Step 4: 建议（从焦点规则推断 + 感质/注意力调制）
        suggestions = _build_suggestions(
            focal_rules, dv, state_snapshot, params, somatic_signals, attention_weights,
        )

        # Step 5: 心智模拟验证
        if suggestions and state_snapshot and entity_state is not None:
            try:
                from .mental_simulation import simulate_suggestions
                wm_rules = getattr(entity_state, "wm_rules", [])
                if wm_rules:
                    suggestions = simulate_suggestions(
                        suggestions, state_snapshot, wm_rules, entity=entity_state,
                    )
            except Exception:
                pass

        # Step 6: 枝干联想检索
        branch_memories = []
        if entity_state is not None and concept_tags is not None:
            try:
                from ..memory_retrieval.branch import branch_retrieval
                tag_strings = [
                    t.get("tag") if isinstance(t, dict) else str(t)
                    for t in (concept_tags or [])
                ]
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
    }

    wm = {
        "matched_rules": [
            {"id": "r1", "confidence": 0.3, "content": "loneliness上升会导致approach_drive增加",
             "expected_deltas": {"approach_drive": 0.2}},
            {"id": "r2", "confidence": 0.85, "content": "高energy时探索效果更好",
             "expected_deltas": {"approach_drive": 0.3, "fatigue": 0.1}},
            {"id": "r3", "confidence": 0.6, "content": "boredom会降低info_gap",
             "expected_deltas": {"info_gap": -0.2}},
            {"id": "r4", "confidence": 0.9, "content": "stress长期积累会导致fatigue升高",
             "expected_deltas": {"fatigue": 0.4}},
            {"id": "r5", "confidence": 0.2, "content": "孤独感与joy的关系不稳定",
             "expected_deltas": {"joy": -0.1}},
        ]
    }

    state_ex = {
        "loneliness": 0.7, "energy": 0.6, "fatigue": 0.2,
        "boredom": 0.3, "approach_drive": 0.5,
    }

    print("【统一流测试】")
    test_cases = [
        ("好奇主导", {"curiosity": 0.8, "info_hunger": 0.3, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}),
        ("孤独主导", {"curiosity": 0.2, "info_hunger": 0.2, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.9, "fatigue_avoid": 0.1}),
        ("疲惫主导", {"curiosity": 0.2, "info_hunger": 0.1, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.8}),
        ("全低(不应触发)", {"curiosity": 0.1, "info_hunger": 0.1, "obsolescence_anxiety": 0.1, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}),
        ("空wm", {}),
    ]

    for name, dv in test_cases:
        result = think(wm if name != "空wm" else {}, dv, state_ex, params)
        tag = "触发" if result["questions"] else "未触发"
        print(f"\n  {name}: {tag}")
        if result["questions"]:
            for q in result["questions"]:
                print(f"    Q: {q['question']}")
                print(f"      context: {q['context']}")
        if result["suggestions"]:
            for s in result["suggestions"]:
                print(f"    S: {s['action']} (p={s['priority']:.3f}) reason={s['reason']}")

    print("\n【感质调制测试】")
    somatic_cases = [
        ("无感质", None),
        ("正面基调", {"tone": 0.6, "intensity": 0.8}),
        ("负面基调", {"tone": -0.5, "intensity": 0.6}),
    ]
    test_dv = {"curiosity": 0.7, "info_hunger": 0.3, "obsolescence_anxiety": 0.2, "loneliness_drive": 0.1, "fatigue_avoid": 0.1}
    for name, somatic in somatic_cases:
        r = think(wm, test_dv, state_ex, params, somatic_signals=somatic)
        top = r["suggestions"][0] if r["suggestions"] else {}
        print(f"  {name} → top: {top.get('action','(无)')}(p={top.get('priority',0):.3f})")

    print("\n全部测试完成")
