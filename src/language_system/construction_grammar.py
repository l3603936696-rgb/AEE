"""
Construction Grammar — 构式习得（v1.0）

从成功的表达实例中自动抽取结构模式（构式），
然后用构式 + 槽位词类生成模板库里没有的新句子。

核心机制：
    1. 记录：每次成功表达 → (结构, 填充词, 状态, 效率)
    2. 抽取：共享结构 + 不同填充 → 构式 schema
    3. 槽位分类：成功填入同一槽位的词形成词类
    4. 生成：构式 × 词类 → 新表达
    5. 反馈：新表达的效率反馈 → 加强/衰减构式

Submodules:
    construction_schema.py  — 数据结构 + 超参数
    construction_grammar.py — ConstructionLearner 主类
    construction_utils.py   — standalone helpers
    construction_helpers.py — 内部 helper 函数（从主类提取）
"""

from .construction_schema import (
    ExpressionInstance,
    Construction,
    _drive_match_score,
    _MAX_INSTANCES,
    _MIN_INSTANCES_FOR_SCHEMA,
    _BASELINE_EFFICIENCY,
    _STRENGTH_DECAY,
    _STRENGTH_BOOST,
    _MIN_STRENGTH,
)
from .construction_helpers import (
    update_construction,
    prune_weak_constructions,
    gap_probe_mutate,
    get_construction_stats,
    make_construction_score_fn,
    make_recursive_score_fn,
)

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ─── 种子构式（保持在此文件）────────────────────────────────────────────────

_SEED_CONSTRUCTIONS: List[tuple] = [
    ("{0}吗？",     {"info_gap": 0.7, "curiosity": 0.5, "approach_drive": 0.3}),
    ("为什么{0}？", {"curiosity": 0.8, "unresolved": 0.6, "info_gap": 0.5}),
    ("{0}呢？",     {"curiosity": 0.4, "info_gap": 0.3}),
    ("不{0}",       {"avoid_drive": 0.5, "approach_drive": -0.3}),
]


# ─── 构式习得器 ─────────────────────────────────────────────────────────────

class ConstructionLearner:
    """
    从表达实例中学习构式，然后用构式生成新表达。

    闭环：
        record_instance() → 存实例
        extract_constructions() → 从实例抽取构式
        generate_candidates() → 用构式生成候选（注入 compose_sentence）
        reinforce() → 消力反馈更新构式强度
    """

    def __init__(self):
        self._instances: List[ExpressionInstance] = []
        self._constructions: Dict[str, Construction] = {}
        self._extract_counter: int = 0
        self._extract_interval: int = 20
        self._seed_planted: bool = False

    def ensure_seeds(self, tick: int = 0) -> None:
        """播种子构式（只执行一次）。"""
        if self._seed_planted:
            return
        for schema, profile in _SEED_CONSTRUCTIONS:
            if schema not in self._constructions:
                cx = Construction(schema, born_tick=tick)
                cx.drive_profile = dict(profile)
                cx.strength = 0.15
                self._constructions[schema] = cx
        self._seed_planted = True

    # ── 记录实例 ──────────────────────────────────────────────────────────

    def record_instance(
        self,
        template_str: str,
        anchor: str,
        drive_state: Dict[str, float],
        efficiency: float,
        tick: int,
        second_anchor: str = "",
        is_heard: bool = False,
    ) -> None:
        """记录一次成功的表达实例。"""
        structure = template_str
        fillers = []

        if "{anchor}" in structure:
            structure = structure.replace("{anchor}", "{0}", 1)
            fillers.append(anchor)

        if "{anchor2}" in structure and second_anchor:
            structure = structure.replace("{anchor2}", "{1}", 1)
            fillers.append(second_anchor)

        if not fillers:
            return

        inst = ExpressionInstance(
            structure=structure,
            fillers=fillers,
            drive_state={k: v for k, v in drive_state.items()
                         if isinstance(v, (int, float))},
            efficiency=efficiency,
            tick=tick,
            action_context="",
            is_heard=is_heard,
        )
        self._instances.append(inst)

        if len(self._instances) > _MAX_INSTANCES:
            self._instances = self._instances[-_MAX_INSTANCES:]

        if structure in self._constructions:
            update_construction(self._constructions[structure], inst)

        self._extract_counter += 1
        if self._extract_counter >= self._extract_interval:
            self._extract_counter = 0
            self.extract_constructions(tick)

    # ── 构式抽取 ──────────────────────────────────────────────────────────

    def extract_constructions(self, current_tick: int) -> int:
        """从实例缓冲区抽取新构式。"""
        groups: Dict[str, List[ExpressionInstance]] = defaultdict(list)
        for inst in self._instances:
            groups[inst.structure].append(inst)

        new_count = 0
        for schema, instances in groups.items():
            if schema in self._constructions:
                continue
            if len(instances) < _MIN_INSTANCES_FOR_SCHEMA:
                continue

            heard_count = sum(1 for i in instances if i.is_heard)
            heard_ratio = heard_count / len(instances)

            if heard_ratio > 0.5:
                min_needed = 5
            elif heard_ratio > 0:
                min_needed = 3
            else:
                min_needed = _MIN_INSTANCES_FOR_SCHEMA

            if len(instances) < min_needed:
                continue

            slot_words: Dict[int, Set[str]] = defaultdict(set)
            for inst in instances:
                for i, w in enumerate(inst.fillers):
                    slot_words[i].add(w)

            has_diversity = any(len(words) >= 2 for words in slot_words.values())
            if not has_diversity:
                continue

            cx = Construction(schema, born_tick=current_tick)
            cx.heard_ratio = heard_ratio
            for inst in instances:
                update_construction(cx, inst)

            avg_eff = sum(i.efficiency for i in instances) / len(instances)
            cx.strength = min(1.0, avg_eff * 2.0)

            self._constructions[schema] = cx
            new_count += 1
            logger.info(
                f"[CxG] Extracted construction: '{schema}' "
                f"strength={cx.strength:.3f} fillers={dict(slot_words)}"
            )

        prune_weak_constructions(self._constructions, current_tick)
        return new_count

    # ── 生成候选 ──────────────────────────────────────────────────────────

    def generate_candidates(
        self,
        anchor: str,
        drive_state: Dict[str, float],
        max_candidates: int = 3,
        second_anchor: str = "",
        recursive_generator: Any = None,
        anchor_words: Optional[List[str]] = None,
        action_context: str = "",
    ) -> List[Dict]:
        """用学到的构式生成候选模板，注入 compose_sentence 的 extra_templates。"""
        if not self._constructions:
            return []

        clause = None
        if recursive_generator is not None:
            clause = recursive_generator.generate_clause(
                drive_state, anchor_words or [], depth=0,
                avoid_words=[anchor],
            )

        candidates = []
        for schema, cx in self._constructions.items():
            if cx.strength < _MIN_STRENGTH:
                continue

            slot0 = cx.slot_fillers.get(0, {})
            anchor_affinity = slot0.get(anchor, 0.0)

            if anchor_affinity < 0.01:
                anchor_affinity = cx.strength * 0.1
            if anchor_affinity < 0.001:
                continue

            has_slot1 = "{1}" in schema
            if has_slot1 and not second_anchor:
                continue

            template_str = schema.replace("{0}", "{anchor}", 1)
            if has_slot1:
                template_str = template_str.replace("{1}", "{anchor2}", 1)

            drive_match = _drive_match_score(drive_state, cx.drive_profile)
            action_score = 0.0
            if action_context and action_context in cx.action_profile:
                total_uses = sum(cx.action_profile.values())
                action_score = cx.action_profile[action_context] / max(1, total_uses)

            score_fn = make_construction_score_fn(
                cx.strength, anchor_affinity, drive_match, action_score,
            )

            candidates.append({
                "template": template_str,
                "score_fn": score_fn,
                "use_connector": False,
                "anchor_pos": "tail",
                "_from_cxg": True,
            })

            if clause and not has_slot1:
                compound_template = template_str + clause
                rec_score = make_recursive_score_fn(
                    cx.strength, anchor_affinity, drive_match, action_score,
                )
                candidates.append({
                    "template": compound_template,
                    "score_fn": lambda s, sc=rec_score: sc,
                    "use_connector": False,
                    "anchor_pos": "tail",
                    "_from_cxg": True,
                    "_recursive": True,
                })

        candidates.sort(
            key=lambda c: c["score_fn"](drive_state), reverse=True,
        )

        _COVER_THRESHOLD = 0.15
        if len(candidates) < max_candidates:
            best_cover = max(
                (c["score_fn"](drive_state) for c in candidates), default=0.0,
            )
            if best_cover < _COVER_THRESHOLD:
                _new = gap_probe_mutate(
                    anchor, drive_state,
                    lambda s, ds: self._register_schema(s, ds),
                )
                if _new:
                    candidates.append(_new)
                    candidates.sort(
                        key=lambda c: c["score_fn"](drive_state), reverse=True,
                    )

        return candidates[:max_candidates]

    # ── 反馈强化 ──────────────────────────────────────────────────────────

    def reinforce(
        self,
        template_str: str,
        efficiency: float,
        tick: int,
        action_context: str = "",
    ) -> None:
        """对使用过的构式模板进行强度反馈。"""
        schema = template_str.replace("{anchor}", "{0}", 1)
        schema = schema.replace("{anchor2}", "{1}", 1)

        cx = self._constructions.get(schema)
        if not cx:
            return

        heard_decay = max(0.3, 1.0 - cx.heard_ratio * 0.7)
        delta = _STRENGTH_BOOST * (efficiency - 0.03) * heard_decay
        cx.strength = max(0.0, min(1.0, cx.strength + delta))
        cx.use_count += 1
        cx.last_used_tick = tick

        if action_context and action_context in ("explore", "seek", "avoid", "resolve", "rest"):
            if action_context not in cx.action_profile:
                cx.action_profile[action_context] = 0
            cx.action_profile[action_context] += 1

        logger.debug(
            f"[CxG] Reinforced '{schema}' "
            f"eff={efficiency:.3f} Δ={delta:+.3f} → strength={cx.strength:.3f}"
        )

    # ── 周期衰减 ──────────────────────────────────────────────────────────

    def decay_all(self, current_tick: int) -> None:
        """每 tick 调用，衰减所有构式强度。"""
        for cx in self._constructions.values():
            cx.strength *= _STRENGTH_DECAY
        prune_weak_constructions(self._constructions, current_tick)

    # ── 序列化 ────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "constructions": {
                k: v.to_dict() for k, v in self._constructions.items()
            },
            "extract_counter": self._extract_counter,
            "seed_planted": self._seed_planted,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConstructionLearner":
        learner = cls()
        for k, v in d.get("constructions", {}).items():
            learner._constructions[k] = Construction.from_dict(v)
        learner._extract_counter = d.get("extract_counter", 0)
        learner._seed_planted = d.get("seed_planted", False)
        return learner

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _register_schema(
        self, schema: str, drive_state: Dict[str, float],
    ) -> None:
        """将新 schema 快速注册到本地图谱。"""
        norm = schema.replace("{anchor}", "{0}")
        norm = norm.replace("{anchor2}", "{1}")
        if norm not in self._constructions:
            cx = Construction(schema=norm, strength=0.05)
            cx.drive_profile = {
                k: v for k, v in drive_state.items()
                if isinstance(v, (int, float))
            }
            self._constructions[norm] = cx

    @property
    def construction_count(self) -> int:
        return len(self._constructions)

    def get_stats(self) -> Dict[str, Any]:
        """返回构式库摘要（调试/展示用）。"""
        return get_construction_stats(self._constructions)
