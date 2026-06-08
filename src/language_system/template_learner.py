"""
Template Learner — 模板自学习与进化（v1.0）

职责：
    1. 权重学习：从消力效率反馈中更新模板的状态权重（Hebbian-like）
    2. 模板进化：通过高效父模板交叉，产生新模板结构
    3. 持久化：保存/恢复学习状态

设计原则：
    - 加法修正：不替代 score_fn（内置评分），只叠加 learned_weights
    - 渐进学习：lr=0.02, decay=0.998，不会突变
    - 自然淘汰：新模板和旧模板平等竞争，低效率者自然沉底
    - 无 if-else 开关：所有行为通过连续数值驱动

学习闭环：
    compose_sentence(state, learned_weights)
        → 选中 template #i
        → 表达 → 消力 → efficiency
        → update_weights(#i, state, efficiency)
        → learned_weights[#i] 更新
        → 下次 compose_sentence 时，#i 的评分变化
"""

import logging
import random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── 超参 ───────────────────────────────────────────────────────────────────
_LR = 0.02              # 权重学习率
_DECAY = 0.998           # 每次更新后权重衰减（防止无限增长）
_MIN_WEIGHT = 0.001      # 低于此绝对值的权重被清除
_SPAWN_INTERVAL = 50     # 每多少次 quenching record 尝试一次进化
_SPAWN_PROB = 0.3        # 到达 interval 时的实际触发概率
_MAX_RUNTIME = 20        # 运行时模板池上限
_MIN_EFF_FOR_PARENT = 0.1  # 成为父模板的最低平均效率
_MIN_RECORDS_FOR_PARENT = 3  # 成为父模板的最低记录数


# ─── 权重学习 ────────────────────────────────────────────────────────────────

def update_weights(
    template_idx: int,
    state: Dict[str, float],
    efficiency: float,
    learned_weights: Dict[int, Dict[str, float]],
    baseline: float = 0.05,
) -> None:
    """
    根据消力反馈更新模板的学习权重（原地修改 learned_weights）。

    学习规则（类 Hebbian）：
        delta_w[dim] = lr * (state[dim] - 0.5) * (efficiency - baseline)

    - efficiency > baseline → 正向强化当前状态与模板的关联
    - efficiency < baseline → 负向弱化
    - state[dim] - 0.5 → 居中化，中性状态不产生学习信号
    """
    if template_idx < 0 or efficiency < 0.01:
        return

    advantage = efficiency - baseline
    lw = learned_weights.get(template_idx, {})

    for dim, val in state.items():
        if not isinstance(val, (int, float)):
            continue
        # 防御未归一化维度（如 time_since_last_info/social，原始计数可达上万）：
        # 学习规则 (val-0.5) 假设 val∈[0,1]，超界值会把权重放大成天文数字。
        # clamp 压回 [0,1]，是连续函数，不引入行为分支。
        val = max(0.0, min(1.0, val))
        delta = _LR * (val - 0.5) * advantage
        lw[dim] = lw.get(dim, 0.0) + delta

    # 衰减 + 清理极小权重
    to_delete = []
    for dim in lw:
        lw[dim] *= _DECAY
        if abs(lw[dim]) < _MIN_WEIGHT:
            to_delete.append(dim)
    for dim in to_delete:
        del lw[dim]

    if lw:
        learned_weights[template_idx] = lw
    elif template_idx in learned_weights:
        del learned_weights[template_idx]


def score_from_learned(
    template_idx: int,
    state: Dict[str, float],
    learned_weights: Dict[int, Dict[str, float]],
) -> float:
    """计算模板的学习权重评分（纯 dot product，无 score_fn）。"""
    lw = learned_weights.get(template_idx)
    if not lw:
        return 0.0
    return sum(w * state.get(dim, 0.0) for dim, w in lw.items())


# ─── 模板进化 ────────────────────────────────────────────────────────────────

def try_spawn_template(
    template_stats: Dict[int, Tuple[float, int]],
    seed_templates: list,
    runtime_templates: list,
    spawn_counter: int,
) -> Tuple[Optional[Dict], int]:
    """
    尝试通过交叉产生新模板。

    机制：
        1. 选两个高效父模板
        2. A 的 prefix + B 的 suffix → 子模板
        3. 子模板无 score_fn，纯靠 learned_weights 竞争

    参数：
        template_stats     : {idx: (avg_efficiency, count)} 来自 QuenchingTracker
        seed_templates     : PATTERNS
        runtime_templates  : 运行时模板列表（可能被原地修改——淘汰最弱者）
        spawn_counter      : 当前计数（每次 quenching record +1）

    返回：
        (new_template | None, updated_counter)
    """
    spawn_counter += 1
    if spawn_counter < _SPAWN_INTERVAL:
        return (None, spawn_counter)
    spawn_counter = 0

    if random.random() > _SPAWN_PROB:
        return (None, spawn_counter)

    all_templates = seed_templates + runtime_templates

    # 筛选合格父模板
    parents = []
    for idx, (avg_eff, count) in template_stats.items():
        if count < _MIN_RECORDS_FOR_PARENT:
            continue
        if avg_eff < _MIN_EFF_FOR_PARENT:
            continue
        if idx >= len(all_templates):
            continue
        # 排除无 anchor 的模板（不参与交叉）
        tmpl_str = all_templates[idx]["template"]
        if "{anchor}" not in tmpl_str:
            continue
        parents.append((idx, avg_eff))

    if len(parents) < 2:
        return (None, spawn_counter)

    # 按效率排序取 top 10，随机选两个
    parents.sort(key=lambda x: x[1], reverse=True)
    pool = parents[:10]
    idx_a, idx_b = random.sample(range(len(pool)), 2)
    parent_a = all_templates[pool[idx_a][0]]
    parent_b = all_templates[pool[idx_b][0]]

    # 分解 → 交叉
    parts_a = _split_template(parent_a["template"])
    parts_b = _split_template(parent_b["template"])
    if parts_a is None or parts_b is None:
        return (None, spawn_counter)

    prefix_a, suffix_a = parts_a
    prefix_b, suffix_b = parts_b

    child_str = prefix_a + "{anchor}" + suffix_b
    existing = {t["template"] for t in all_templates}
    if child_str in existing:
        child_str = prefix_b + "{anchor}" + suffix_a
        if child_str in existing:
            return (None, spawn_counter)

    # 基本合法性检查
    if len(child_str) < 5 or len(child_str) > 40:
        return (None, spawn_counter)

    anchor_pos = _infer_anchor_pos(child_str)

    child = {
        "template": child_str,
        "score_fn": None,
        "use_connector": random.choice([True, False]),
        "anchor_pos": anchor_pos,
        "born_tick": -1,
        "parents": [parent_a["template"], parent_b["template"]],
    }

    # 容量控制
    if len(runtime_templates) >= _MAX_RUNTIME:
        _prune_weakest(runtime_templates, template_stats, len(seed_templates))

    logger.info(
        f"[TemplateLearner] Spawned '{child_str}' "
        f"from '{parent_a['template']}' × '{parent_b['template']}'"
    )
    return (child, spawn_counter)


def _split_template(template: str) -> Optional[Tuple[str, str]]:
    """将模板按 {{anchor}} 分为 (prefix, suffix)。"""
    tag = "{anchor}"
    idx = template.find(tag)
    if idx < 0:
        return None
    return (template[:idx], template[idx + len(tag):])


def _infer_anchor_pos(template: str) -> str:
    """从模板结构推断 anchor 位置标签。"""
    tag = "{anchor}"
    idx = template.find(tag)
    if idx < 0:
        return "none"
    prefix = template[:idx]
    suffix = template[idx + len(tag):]
    if not prefix:
        return "head"
    if not suffix:
        return "tail"
    if len(prefix) <= 2:
        return "adj"
    return "embed"


def _prune_weakest(
    runtime_templates: list,
    template_stats: Dict[int, Tuple[float, int]],
    seed_count: int,
) -> None:
    """移除效率最低的运行时模板。"""
    if not runtime_templates:
        return
    worst_i = 0
    worst_avg = float("inf")
    for i in range(len(runtime_templates)):
        global_idx = seed_count + i
        stats = template_stats.get(global_idx, (0.0, 0))
        avg = stats[0] / max(stats[1], 1) if stats[1] > 0 else 0.0
        if avg < worst_avg:
            worst_avg = avg
            worst_i = i
    removed = runtime_templates.pop(worst_i)
    logger.info(f"[TemplateLearner] Pruned '{removed['template']}' (avg={worst_avg:.3f})")


# ─── 持久化 ──────────────────────────────────────────────────────────────────

def to_dict(
    learned_weights: Dict[int, Dict[str, float]],
    runtime_templates: List[Dict],
    spawn_counter: int,
) -> Dict[str, Any]:
    """序列化模板学习状态。"""
    return {
        "learned_weights": {
            str(k): dict(v) for k, v in learned_weights.items()
        },
        "runtime_templates": [
            {
                "template": t["template"],
                "anchor_pos": t.get("anchor_pos", "head"),
                "use_connector": t.get("use_connector", False),
                "born_tick": t.get("born_tick", -1),
                "parents": t.get("parents", []),
            }
            for t in runtime_templates
        ],
        "spawn_counter": spawn_counter,
    }


def from_dict(data: Dict[str, Any]) -> Tuple[
    Dict[int, Dict[str, float]],  # learned_weights
    List[Dict],                    # runtime_templates
    int,                           # spawn_counter
]:
    """反序列化模板学习状态。"""
    learned_weights: Dict[int, Dict[str, float]] = {}
    for k, v in data.get("learned_weights", {}).items():
        learned_weights[int(k)] = dict(v)

    runtime_templates: List[Dict] = []
    for t in data.get("runtime_templates", []):
        runtime_templates.append({
            "template": t["template"],
            "score_fn": None,
            "anchor_pos": t.get("anchor_pos", "head"),
            "use_connector": t.get("use_connector", False),
            "born_tick": t.get("born_tick", -1),
            "parents": t.get("parents", []),
        })

    spawn_counter = int(data.get("spawn_counter", 0))
    return learned_weights, runtime_templates, spawn_counter
