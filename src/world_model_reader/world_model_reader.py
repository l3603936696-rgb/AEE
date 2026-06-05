"""
World Model Reader Module (世界模型读取模块 — Read-Only)

职责：接收概念标签，查询已标签化的世界模型，输出结构化的规律摘要，
      保留多维反馈信号供裁决层使用。

设计约束：
    - 纯函数，不访问任何原对象引用
    - world_model_snapshot 必须是冻结副本（深拷贝），由调用方保证
    - 不调用 LLM
    - 任一环节失败 → 返回完整的空结构，不抛异常
    - 精确标签匹配（非子串匹配）
    - key_signals 仅暴露 v4 三通道信号维度：SEEK / AVOID / COMFORT
      危险/无聊等具体语义由裁决层叠加得出，非读取层职责
"""

from typing import List


# ============================================================================
# 异常安全的空结构构造器
# ============================================================================

def _empty_result() -> dict:
    """返回完整的空结果结构"""
    return {
        "matched_rules": [],
        "key_signals": {
            "max_seek_conf": 0.0,
            "max_avoid_conf": 0.0,
            "max_comfort_conf": 0.0,
        },
        "coverage": {
            "queried_tags": [],
            "missed_tags": [],
            "hit_rate": 0.0,
        },
    }


def _build_result(
    matched_rules: List[dict],
    queried_tags: List[str],
    missed_tags: List[str],
    hit_rate: float,
) -> dict:
    """
    根据已有数据构建最终结果。
    所有输入均已通过合法性检查。
    """
    max_seek = 0.0
    max_avoid = 0.0
    max_comfort = 0.0

    for rule in matched_rules:
        sig_type = rule.get("signal_type", "").upper()
        conf = float(rule.get("confidence", 0.0))
        if sig_type == "SEEK":
            max_seek = max(max_seek, conf)
        elif sig_type == "AVOID":
            max_avoid = max(max_avoid, conf)
        elif sig_type == "COMFORT":
            max_comfort = max(max_comfort, conf)
        # 非三通道的 signal_type 不更新 key_signals

    return {
        "matched_rules": matched_rules,
        "key_signals": {
            "max_seek_conf": max_seek,
            "max_avoid_conf": max_avoid,
            "max_comfort_conf": max_comfort,
        },
        "coverage": {
            "queried_tags": list(queried_tags),
            "missed_tags": list(missed_tags),
            "hit_rate": hit_rate,
        },
    }


# ============================================================================
# 核心查询逻辑
# ============================================================================

def _match_rule(rule: dict, tags: set) -> bool:
    """
    精确标签匹配。

    当查询标签集合包含规则的 trigger_tags 全部标签时 → 匹配。
    规则要求的标签任意一个不在查询中 → 不匹配。
    """
    try:
        trigger = rule.get("trigger_tags", [])
        if not isinstance(trigger, list):
            return False
        tag_set = set(t.strip() for t in trigger if isinstance(t, str))
        # 查询标签集合是规则触发标签集合的超集 → 匹配
        return tag_set.issubset(tags)
    except Exception:
        return False


def _classify_tag_coverage(
    matched_rules: List[dict],
    tags: List[str],
) -> List[str]:
    """
    计算 coverage.missed_tags。

    命中规则覆盖其全部 trigger_tags（而非仅交集）。
    查询标签中未被任何命中规则的 trigger_tags 包含的 → 属于 missed_tags。
    """
    try:
        tags_set = set(t for t in tags if isinstance(t, str))

        covered = set()
        for rule in matched_rules:
            for t in rule.get("trigger_tags", []):
                if isinstance(t, str):
                    covered.add(t.strip())

        missed = sorted(tags_set - covered)
        return missed
    except Exception:
        return sorted(tags)


# ============================================================================
# 主入口
# ============================================================================

def query_world_model(
    concept_tags: List[str],
    world_model_snapshot: dict,
) -> dict:
    """
    世界模型查询主入口。

    参数（仅读）：
        concept_tags:        来自概念标签层的标签列表，如 ["负面情绪", "求助"]
        world_model_snapshot: 世界模型的冻结副本（字典或不可变对象），
                            由调用方负责深拷贝后传入。

    返回 wm_context：
        {
            "matched_rules": [
                {
                    "rule_id":     str,
                    "content":     str,
                    "confidence":  float,   # [0, 1]
                    "domain":      str,
                    "signal_type": str,      # "SEEK" | "AVOID" | "COMFORT"
                    "trigger_tags": List[str],  # 用于 coverage 计算
                    "status":      str,      # "active" | "pending" | "decayed"
                }
            ],
            "key_signals": {
                "max_seek_conf":    float,  # 三通道之一
                "max_avoid_conf":    float,
                "max_comfort_conf": float,
            },
            "coverage": {
                "queried_tags": List[str],
                "missed_tags":  List[str],
                "hit_rate":     float,  # [0, 1]
            }
        }

    约束：
        - 纯函数，不访问原对象引用
        - 不调用 LLM
        - 任一环节失败 → 完整空结构，不抛异常
    """
    try:
        # ----- 参数合法性 -----
        if not isinstance(concept_tags, list):
            return _empty_result()
        if not isinstance(world_model_snapshot, dict):
            return _empty_result()

        tags = [t.strip() for t in concept_tags if isinstance(t, str)]
        tags_set = set(tags)

        # ----- 获取规律列表 -----
        rules = world_model_snapshot.get("rules", [])
        if not isinstance(rules, list):
            return _empty_result()

        # ----- 精确标签匹配 -----
        matched = []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if _match_rule(rule, tags_set):
                matched.append({
                    "rule_id":     str(rule.get("id") or rule.get("rule_id") or ""),
                    "content":     str(rule.get("content", "")),
                    "confidence":  float(rule.get("confidence", 0.0)),
                    "domain":      str(rule.get("domain", "")),
                    "signal_type": str(rule.get("signal_type", "")).upper(),
                    "trigger_tags": list(rule.get("trigger_tags", [])),
                    "status":      str(rule.get("status", "active")),
                })

        # ----- 计算 coverage -----
        missed_tags = _classify_tag_coverage(matched, tags)
        n_queried = len(tags)
        n_matched_tags = n_queried - len(missed_tags)
        hit_rate = n_matched_tags / n_queried if n_queried > 0 else 0.0

        # ----- 构建结果 -----
        return _build_result(matched, tags, missed_tags, hit_rate)

    except Exception:
        return _empty_result()


# ============================================================================
# 测试入口
# ============================================================================

if __name__ == "__main__":
    print("=" * 64)
    print("世界模型读取模块测试")
    print("=" * 64)

    # ----- 示例世界模型快照 -----
    SNAPSHOT = {
        "rules": [
            {
                "rule_id": "R001",
                "content": "寻求他人陪伴可缓解孤独感",
                "confidence": 0.9,
                "domain": "social",
                "signal_type": "SEEK",
                "trigger_tags": ["孤独感", "求助"],
            },
            {
                "rule_id": "R002",
                "content": "负面情绪可通过倾诉释放",
                "confidence": 0.85,
                "domain": "social",
                "signal_type": "SEEK",
                "trigger_tags": ["负面情绪", "倾诉"],
            },
            {
                "rule_id": "R003",
                "content": "危险社交场景应保持距离",
                "confidence": 0.75,
                "domain": "social",
                "signal_type": "AVOID",
                "trigger_tags": ["危险信号"],
            },
            {
                "rule_id": "R004",
                "content": "熟悉环境提供安全感",
                "confidence": 0.92,
                "domain": "comfort",
                "signal_type": "COMFORT",
                "trigger_tags": ["熟悉环境"],
            },
            {
                "rule_id": "R005",
                "content": "重复性任务导致注意力下降",
                "confidence": 0.7,
                "domain": "cognitive",
                "signal_type": "AVOID",
                "trigger_tags": ["重复性", "高强度"],
            },
        ]
    }

    # 冻结副本
    import copy
    snapshot = copy.deepcopy(SNAPSHOT)

    # ----- 工具函数测试 -----
    print("\n【 _match_rule 精确匹配测试 】")
    cases = [
        (["孤独感", "求助"], "R001", True),
        (["负面情绪", "求助"], "R001", False),   # 缺"孤独感"
        (["负面情绪", "倾诉"], "R002", True),
        (["危险信号"], "R003", True),
        (["高强度"], "R005", False),              # R005 需 ["重复性","高强度"]，缺"重复性"
        (["重复性", "高强度"], "R005", True),     # 完整匹配 R005
    ]
    for tags, rid, expected in cases:
        tags_set = set(tags)
        rule = next((r for r in SNAPSHOT["rules"] if r["rule_id"] == rid), None)
        result = _match_rule(rule, tags_set)
        status = "✓" if result == expected else "✗"
        print(f"  {status} tags={tags}, rule={rid} → {result} (期望 {expected})")

    # ----- 主入口测试 -----
    test_cases = [
        {
            "name": "正常查询 — 命中 R002（2个标签全命中）",
            "tags": ["负面情绪", "求助", "倾诉"],    # R002=["负面情绪","倾诉"] 命中，R001 缺"孤独感"
        },
        {
            "name": "查询部分命中 — 命中 R001（缺'高强度'标签）",
            "tags": ["孤独感", "求助", "高强度"],    # R001=["孤独感","求助"] 命中，missed=[高强度]
        },
        {
            "name": "空标签列表",
            "tags": [],
        },
        {
            "name": "无匹配",
            "tags": ["未知标签1", "未知标签2"],
        },
        {
            "name": "空世界模型",
            "tags": [],
            "snapshot": {},
        },
        {
            "name": "无效输入",
            "tags": None,
        },
    ]

    print("\n【 query_world_model 主入口测试 】")
    for tc in test_cases:
        tags = tc.get("tags", ["负面情绪", "求助", "倾诉"])
        snap = tc.get("snapshot", snapshot)
        ctx = query_world_model(tags, snap)

        print(f"\n  【{tc['name']}】")
        print(f"    key_signals: seek={ctx['key_signals']['max_seek_conf']:.2f}, "
              f"avoid={ctx['key_signals']['max_avoid_conf']:.2f}, "
              f"comfort={ctx['key_signals']['max_comfort_conf']:.2f}")
        print(f"    hit_rate: {ctx['coverage']['hit_rate']:.2f}")
        print(f"    queried: {ctx['coverage']['queried_tags']}")
        print(f"    missed:  {ctx['coverage']['missed_tags']}")
        for r in ctx["matched_rules"]:
            print(f"      → [{r['rule_id']}] {r['signal_type']} {r['content'][:30]}")

    print("\n" + "=" * 64)
    print("测试完成")
    print("=" * 64)
