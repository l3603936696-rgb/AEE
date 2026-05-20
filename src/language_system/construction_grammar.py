"""
Construction Grammar — 构式习得（v1.0）

从成功的表达实例中自动抽取结构模式（构式），
然后用构式 + 槽位词类生成模板库里没有的新句子。

核心机制：
    1. 记录：每次成功表达 → (结构, 填充词, 状态, 效率)
    2. 抽取：共享结构 + 不同填充 → 构式 schema
    3. 槽位分类：成功填入同一槽的词形成词类
    4. 生成：构式 × 词类 → 新表达
    5. 反馈：新表达的效率反馈 → 加强/衰减构式

设计原则：
    - 全连续：构式强度、槽位亲和度、生成评分全部连续函数
    - 无预设语法：所有结构从数据中涌现
    - 和现有 compose_sentence 兼容：构式模板注入 extra_templates

术语：
    构式 (Construction)   = 形式-意义对 = (带槽结构, 驱动力 delta 模式)
    槽位 (Slot)           = 构式中可替换的位置
    词类 (Filler Class)   = 成功填入同一槽位的词的集合
    实例 (Instance)       = 一次具体的成功表达
"""

import logging
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ─── 超参 ───────────────────────────────────────────────────────────────────
_MAX_INSTANCES = 500         # 实例缓冲区上限
_MIN_INSTANCES_FOR_SCHEMA = 3  # 抽取构式的最少实例数
_MIN_EFFICIENCY = 0.0        # 记录实例的最低效率门槛（v12: 0.0=全量记录，由_update_construction区分正负样本）
_BASELINE_EFFICIENCY = 0.05  # 效率中位参考值，用于区分正负样本的分界
_STRENGTH_DECAY = 0.995      # 每次 tick 构式强度衰减
_STRENGTH_BOOST = 0.15       # 成功使用一次的强度增益
_MAX_CONSTRUCTIONS = 40      # 构式库上限
_MAX_FILLERS_PER_SLOT = 30   # 每个槽位最多记住多少个填充词
_SLOT_AFFINITY_DECAY = 0.98  # 槽位亲和度衰减
_MIN_STRENGTH = 0.01         # 低于此强度的构式被清除


# ─── 数据结构 ────────────────────────────────────────────────────────────────

class ExpressionInstance:
    """一次成功表达的记录。"""
    __slots__ = ("structure", "fillers", "drive_state", "efficiency", "tick", "action_context", "is_heard")

    def __init__(
        self,
        structure: str,       # e.g. "好{0}啊……"
        fillers: List[str],   # e.g. ["累"]
        drive_state: Dict[str, float],
        efficiency: float,
        tick: int,
        action_context: str = "",
        is_heard: bool = False,  # 来自阅读/听到的，非原创表达
    ):
        self.structure = structure
        self.fillers = fillers
        self.drive_state = drive_state
        self.efficiency = efficiency
        self.tick = tick
        self.action_context = action_context
        self.is_heard = is_heard


class Construction:
    """一个学到的构式。"""
    __slots__ = (
        "schema", "slot_fillers", "slot_affinity",
        "drive_profile", "strength", "use_count",
        "born_tick", "last_used_tick",
        "action_profile",
        "heard_ratio",  # 二手实例占比：0=原创，1=纯二手（影响强化奖励折扣）
    )

    def __init__(self, schema: str, born_tick: int = 0):
        self.schema = schema              # e.g. "好{0}啊……"
        self.slot_fillers: Dict[int, Dict[str, float]] = {}   # slot_idx → {word: affinity}
        self.slot_affinity: Dict[int, int] = {}               # slot_idx → total fill count
        self.drive_profile: Dict[str, float] = {}             # 效率加权的驱动力均值
        self.strength: float = 0.1        # 构式强度（从低起步）
        self.use_count: int = 0
        self.born_tick: int = born_tick
        self.last_used_tick: int = born_tick
        self.action_profile: Dict[str, int] = {}  # {action_type: use_count}
        self.heard_ratio: float = 0.0     # 二手实例占比（影响强化奖励折扣）

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "slot_fillers": {
                str(k): dict(v) for k, v in self.slot_fillers.items()
            },
            "drive_profile": dict(self.drive_profile),
            "strength": self.strength,
            "use_count": self.use_count,
            "born_tick": self.born_tick,
            "last_used_tick": self.last_used_tick,
            "action_profile": dict(self.action_profile),
            "heard_ratio": self.heard_ratio,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Construction":
        c = cls(d["schema"], d.get("born_tick", 0))
        c.slot_fillers = {
            int(k): dict(v) for k, v in d.get("slot_fillers", {}).items()
        }
        c.drive_profile = dict(d.get("drive_profile", {}))
        c.strength = d.get("strength", 0.1)
        c.use_count = d.get("use_count", 0)
        c.last_used_tick = d.get("last_used_tick", 0)
        c.action_profile = dict(d.get("action_profile", {}))
        c.heard_ratio = d.get("heard_ratio", 0.0)
        return c


# ─── 构式习得器 ──────────────────────────────────────────────────────────────

class ConstructionLearner:
    """
    从表达实例中学习构式，然后用构式生成新表达。

    闭环：
        record_instance() → 存实例
        extract_constructions() → 从实例抽取构式
        generate_candidates() → 用构式生成候选（注入 compose_sentence）
        reinforce() → 消力反馈更新构式强度
    """

    # 种子构式：最小骨架 + 初始 drive profile（可被体验覆盖）
    _SEED_CONSTRUCTIONS: List[Tuple[str, Dict[str, float]]] = [
        ("{0}吗？",     {"info_gap": 0.7, "curiosity": 0.5, "approach_drive": 0.3}),
        ("为什么{0}？", {"curiosity": 0.8, "unresolved": 0.6, "info_gap": 0.5}),
        ("{0}呢？",     {"curiosity": 0.4, "info_gap": 0.3}),
        ("不{0}",       {"avoid_drive": 0.5, "approach_drive": -0.3}),
    ]

    def __init__(self):
        self._instances: List[ExpressionInstance] = []
        self._constructions: Dict[str, Construction] = {}  # schema → Construction
        self._extract_counter: int = 0
        self._extract_interval: int = 20  # 每 20 次记录触发一次抽取
        self._seed_planted: bool = False

    def ensure_seeds(self, tick: int = 0) -> None:
        """播种子构式（只执行一次）。"""
        if self._seed_planted:
            return
        for schema, profile in self._SEED_CONSTRUCTIONS:
            if schema not in self._constructions:
                cx = Construction(schema, born_tick=tick)
                cx.drive_profile = dict(profile)
                cx.strength = 0.15  # 比默认 0.1 稍高，但远低于学到的构式
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
        """
        记录一次成功的表达实例。

        参数：
            template_str  : 使用的模板（如 "好{anchor}啊……"）
            anchor        : 填入的锚点词
            drive_state   : 当时的驱动力状态
            efficiency   : 消力效率
            tick         : 当前 tick
            second_anchor: 双锚点时的第二个词
            is_heard     : 是否来自阅读/听到的（非原创表达）
        """
        # 全量记录（v12: 去掉 efficiency 过滤，负样本也参与学习和抽取）

        # 将 {anchor}/{anchor2} 替换为位置编号 {0}/{1}
        structure = template_str
        fillers = []

        if "{anchor}" in structure:
            structure = structure.replace("{anchor}", "{0}", 1)
            fillers.append(anchor)

        if "{anchor2}" in structure and second_anchor:
            structure = structure.replace("{anchor2}", "{1}", 1)
            fillers.append(second_anchor)

        if not fillers:
            return  # 无槽模板（如"还好吧……"），不参与构式学习

        inst = ExpressionInstance(
            structure=structure,
            fillers=fillers,
            drive_state={k: v for k, v in drive_state.items()
                         if isinstance(v, (int, float))},
            efficiency=efficiency,
            tick=tick,
            action_context="",       # 来自阅读的实例无行为上下文
            is_heard=is_heard,
        )
        self._instances.append(inst)

        # 滚动窗口
        if len(self._instances) > _MAX_INSTANCES:
            self._instances = self._instances[-_MAX_INSTANCES:]

        # 如果这个结构已经是已知构式，直接更新槽位
        if structure in self._constructions:
            self._update_construction(self._constructions[structure], inst)

        # 定期触发抽取
        self._extract_counter += 1
        if self._extract_counter >= self._extract_interval:
            self._extract_counter = 0
            self.extract_constructions(tick)

    # ── 构式抽取 ──────────────────────────────────────────────────────────

    def extract_constructions(self, current_tick: int) -> int:
        """
        从实例缓冲区抽取新构式。

        规则：同一个 structure 出现 ≥ 阈值次，且有 ≥ 2 个不同的填充词 → 可以抽取。

        二手差异化门槛：
            - heard_ratio > 0.5（纯二手型）  ：≥5 次
            - 0 < heard_ratio ≤ 0.5（混合型） ：≥3 次
            - heard_ratio = 0（纯原创型）     ：≥3 次（_MIN_INSTANCES_FOR_SCHEMA）

        返回：新抽取的构式数量。
        """
        # 按结构分组
        groups: Dict[str, List[ExpressionInstance]] = defaultdict(list)
        for inst in self._instances:
            groups[inst.structure].append(inst)

        new_count = 0
        for schema, instances in groups.items():
            if schema in self._constructions:
                continue  # 已有
            if len(instances) < _MIN_INSTANCES_FOR_SCHEMA:
                continue

            # ── 二手差异化门槛 ─────────────────────────────
            heard_count = sum(1 for i in instances if i.is_heard)
            heard_ratio = heard_count / len(instances)

            if heard_ratio > 0.5:
                min_needed = 5   # 二手主导型：需更多积累才可信
            elif heard_ratio > 0:
                min_needed = 3   # 混合型：有机会出现即可
            else:
                min_needed = _MIN_INSTANCES_FOR_SCHEMA  # 纯原创型

            if len(instances) < min_needed:
                continue
            # ────────────────────────────────────────────

            # 检查槽位多样性：至少一个槽有 2+ 个不同填充词
            slot_words: Dict[int, Set[str]] = defaultdict(set)
            for inst in instances:
                for i, w in enumerate(inst.fillers):
                    slot_words[i].add(w)

            has_diversity = any(len(words) >= 2 for words in slot_words.values())
            if not has_diversity:
                continue

            # 抽取！
            cx = Construction(schema, born_tick=current_tick)
            cx.heard_ratio = heard_ratio  # 记录二手占比（影响后续强化奖励折扣）
            for inst in instances:
                self._update_construction(cx, inst)

            # 初始强度 = 实例平均效率
            avg_eff = sum(i.efficiency for i in instances) / len(instances)
            cx.strength = min(1.0, avg_eff * 2.0)

            self._constructions[schema] = cx
            new_count += 1
            logger.info(
                f"[CxG] Extracted construction: '{schema}' "
                f"strength={cx.strength:.3f} fillers={dict(slot_words)}"
            )

        # 淘汰弱构式
        self._prune(current_tick)
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
        """
        用学到的构式生成候选模板，注入 compose_sentence 的 extra_templates。

        如果提供了 recursive_generator，会尝试在构式末尾附加递归子句，
        产出 "好{anchor}啊……想找人说话但又没力气" 这类复合表达。

        返回 compose_sentence 兼容的模板 dict 列表。
        """
        if not self._constructions:
            return []

        # 递归子句（如果有生成器，预生成一个子句）
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

            # 检查 anchor 是否匹配槽 0
            slot0 = cx.slot_fillers.get(0, {})
            anchor_affinity = slot0.get(anchor, 0.0)

            # 未见过的词给基础亲和度（构式的生成力）
            # slot0 为空说明是种子构式或新抽取的，同样给基础亲和度
            if anchor_affinity < 0.01:
                anchor_affinity = cx.strength * 0.1

            if anchor_affinity < 0.001:
                continue

            # 双槽构式需要 second_anchor
            has_slot1 = "{1}" in schema
            if has_slot1 and not second_anchor:
                continue

            # 还原为 {anchor}/{anchor2} 格式
            template_str = schema.replace("{0}", "{anchor}", 1)
            if has_slot1:
                template_str = template_str.replace("{1}", "{anchor2}", 1)

            # 构建 score_fn（含行为意图亲和度）
            drive_match = _drive_match_score(drive_state, cx.drive_profile)
            _action_score = 0.0
            if action_context and action_context in cx.action_profile:
                _total_uses = sum(cx.action_profile.values())
                _action_score = cx.action_profile[action_context] / max(1, _total_uses)
            _strength = cx.strength
            _affinity = anchor_affinity
            _drive = drive_match

            def _make_score_fn(st, af, dr, ac):
                return lambda s: st * 0.35 + af * 0.25 + dr * 0.25 + ac * 0.15

            score_fn = _make_score_fn(_strength, _affinity, _drive, _action_score)
            anchor_pos = _infer_anchor_pos(template_str)

            # 平面构式候选
            candidates.append({
                "template": template_str,
                "score_fn": score_fn,
                "use_connector": False,
                "anchor_pos": anchor_pos,
                "_from_cxg": True,
            })

            # 递归构式候选：平面构式 + 子句
            if clause and not has_slot1:
                compound_template = template_str + clause
                # 递归版评分稍低（更冒险的表达）
                def _make_rec_fn(st, af, dr, ac):
                    return (st * 0.25 + af * 0.15 + dr * 0.20 + ac * 0.10) * 0.85

                candidates.append({
                    "template": compound_template,
                    "score_fn": _make_rec_fn(_strength, _affinity, _drive, _action_score),
                    "use_connector": False,
                    "anchor_pos": anchor_pos,
                    "_from_cxg": True,
                    "_recursive": True,
                })

        # 按评分排序，取 top N
        candidates.sort(
            key=lambda c: c["score_fn"](drive_state), reverse=True,
        )

        # ── 事前空白探测（v12 新增）───────────────────────────────
        # 当现有候选数量不足，且覆盖分偏低时，用 PATTERNS 克隆 + 突变生成新 schema
        _COVER_THRESHOLD = 0.15
        if len(candidates) < max_candidates:
            _best_cover = max(
                (c["score_fn"](drive_state) for c in candidates), default=0.0,
            )
            if _best_cover < _COVER_THRESHOLD:
                _new = self._gap_probe_mutate(anchor, drive_state)
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
        """
        对使用过的构式模板进行强度反馈。

        来自 compose_sentence 选中了 CxG 生成的模板后，
        消力效率反馈回来更新构式强度。
        """
        # 还原 schema
        schema = template_str.replace("{anchor}", "{0}", 1)
        schema = schema.replace("{anchor2}", "{1}", 1)

        cx = self._constructions.get(schema)
        if not cx:
            return

        # 强化/惩罚：效率高 → 加强，效率低 → 衰减
        # 二手衰减：heard_ratio 越高，奖励越低（"听来的道理，总要亲身验证后才更深刻"）
        二手衰减 = max(0.3, 1.0 - cx.heard_ratio * 0.7)
        delta = _STRENGTH_BOOST * (efficiency - 0.03) * 二手衰减
        cx.strength = max(0.0, min(1.0, cx.strength + delta))
        cx.use_count += 1
        cx.last_used_tick = tick

        # 记录行为上下文（action_profile）
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
        self._prune(current_tick)

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

    def _update_construction(
        self, cx: Construction, inst: ExpressionInstance,
    ) -> None:
        """用一个实例更新构式的槽位词类和驱动力画像（正负样本区分处理）。"""
        # 更新槽位填充词
        for i, word in enumerate(inst.fillers):
            if i not in cx.slot_fillers:
                cx.slot_fillers[i] = {}
            fillers = cx.slot_fillers[i]

            old = fillers.get(word, 0.0)
            if inst.efficiency >= _BASELINE_EFFICIENCY:
                # 正样本：高效 → EMA 强化亲和度
                fillers[word] = old * 0.7 + inst.efficiency * 0.3
            else:
                # 负样本：低效 → EMA 衰减亲和度（该词在此结构下不成立）
                decay = 0.10 * (1.0 - inst.efficiency / max(_BASELINE_EFFICIENCY, 0.001))
                fillers[word] = max(0.0, old * (1.0 - decay))

            # 限制词类大小
            if len(fillers) > _MAX_FILLERS_PER_SLOT:
                # 淘汰亲和度最低的
                weakest = min(fillers, key=fillers.get)
                del fillers[weakest]

        # 更新驱动力画像（EMA）
        n = cx.use_count + 1
        alpha = 1.0 / max(n, 1)  # 递减学习率
        for dim, val in inst.drive_state.items():
            old_val = cx.drive_profile.get(dim, 0.5)
            if inst.efficiency >= _BASELINE_EFFICIENCY:
                # 正样本：高效率实例的状态更重要，正常加权更新
                weight = min(1.0, inst.efficiency * 3.0)
                cx.drive_profile[dim] = old_val * (1 - alpha * weight) + val * alpha * weight
            else:
                # 负样本：低效 → 画像向远离此状态的方向漂移
                # 衰减系数由「有多低」决定：越低衰减越强
                neg_weight = min(1.0, (1.0 - inst.efficiency / max(_BASELINE_EFFICIENCY, 0.001)) * 0.5)
                # old_val 向 0.5（中性值）方向收缩，实现「推开」
                cx.drive_profile[dim] = old_val * (1 - alpha * neg_weight) + 0.5 * alpha * neg_weight

        cx.use_count += 1

        # 记录行为上下文（action_profile）
        _inst_action = getattr(inst, "action_context", "") or ""
        if _inst_action and _inst_action in ("explore", "seek", "avoid", "resolve", "rest"):
            if _inst_action not in cx.action_profile:
                cx.action_profile[_inst_action] = 0
            cx.action_profile[_inst_action] += 1

    # ── 空白探测：模板突变（无 LLM）────────────────────────────

    def _gap_probe_mutate(
        self, anchor: str, drive_state: Dict[str, float],
    ) -> Optional[Dict]:
        """
        在空白区尝试生成新 schema（PATTERNS 克隆 + 模板突变）。
        返回 compose_sentence 兼容模板 dict 或 None。
        """
        try:
            from ..language_system.sentence_composer import PATTERNS
        except Exception:
            return None

        if not PATTERNS:
            return None

        # 收集带锚点的 PATTERNS，优先选择长度适中的
        _candidates = []
        for _pat in PATTERNS:
            _tpl = _pat.get("template", "")
            if "{anchor}" not in _tpl and "{anchor2}" not in _tpl:
                continue
            _len_score = max(0.0, 1.0 - abs(len(_tpl) - 8) / 20.0)
            _candidates.append((_len_score, _pat, _tpl))

        if not _candidates:
            return None

        _candidates.sort(key=lambda x: x[0], reverse=True)
        _, _source_pat, _source_tpl = _candidates[0]

        # 随机选一种突变策略
        import random
        _mutations = [
            lambda s: s.replace("{anchor}", f"好{{{anchor}}}啊"),
            lambda s: s.replace("{anchor}", f"{{{anchor}}}得不行"),
            lambda s: s.replace("{anchor}", f"{{{anchor}}}是真的"),
            lambda s: s.replace("{anchor}", f"{{{anchor}}}来着"),
        ]
        _mutate_fn = random.choice(_mutations)
        _new_tpl = _mutate_fn(_source_tpl)

        if _new_tpl == _source_tpl or "{anchor}" not in _new_tpl:
            return None

        self._register_schema(_new_tpl, drive_state)
        _anchor_pos = _infer_anchor_pos(_new_tpl)
        return {
            "template": _new_tpl,
            "score_fn": lambda s, _sc=0.25: _sc,
            "use_connector": False,
            "anchor_pos": _anchor_pos,
            "_from_cxg": True,
            "_gap_probed": True,
        }

    def _register_schema(
        self, schema: str, drive_state: Dict[str, float],
    ) -> None:
        """
        将新 schema 快速注册到本地图谱（未经抽取，直接可用）。
        下次 tick 可被 _update_construction 正常更新。
        """
        _norm = schema.replace("{anchor}", "{0}")
        _norm = _norm.replace("{anchor2}", "{1}")
        if _norm not in self._constructions:
            _cx = Construction(schema=_norm, strength=0.05)
            _cx.drive_profile = {
                k: v for k, v in drive_state.items()
                if isinstance(v, (int, float))
            }
            self._constructions[_norm] = _cx

    def _prune(self, current_tick: int) -> None:
        """淘汰弱构式。"""
        to_remove = []
        for schema, cx in self._constructions.items():
            if cx.strength < _MIN_STRENGTH and cx.use_count > 5:
                to_remove.append(schema)

        for schema in to_remove:
            logger.info(f"[CxG] Pruned weak construction: '{schema}'")
            del self._constructions[schema]

        # 超过上限时淘汰最弱的
        if len(self._constructions) > _MAX_CONSTRUCTIONS:
            sorted_cx = sorted(
                self._constructions.items(),
                key=lambda x: x[1].strength,
            )
            for schema, _ in sorted_cx[:len(sorted_cx) - _MAX_CONSTRUCTIONS]:
                logger.info(f"[CxG] Pruned overflow construction: '{schema}'")
                del self._constructions[schema]

    @property
    def construction_count(self) -> int:
        return len(self._constructions)

    def get_stats(self) -> Dict[str, Any]:
        """返回构式库摘要（调试/展示用）。"""
        if not self._constructions:
            return {"count": 0, "schemas": []}
        return {
            "count": len(self._constructions),
            "schemas": [
                {
                    "schema": cx.schema,
                    "strength": round(cx.strength, 3),
                    "use_count": cx.use_count,
                    "slot_count": len(cx.slot_fillers),
                    "filler_count": sum(
                        len(f) for f in cx.slot_fillers.values()
                    ),
                }
                for cx in sorted(
                    self._constructions.values(),
                    key=lambda c: c.strength, reverse=True,
                )[:10]
            ],
            "instance_buffer": len(self._instances),
        }


# ─── 辅助函数 ────────────────────────────────────────────────────────────────

def _drive_match_score(
    current: Dict[str, float],
    profile: Dict[str, float],
) -> float:
    """当前驱动力状态和构式驱动力画像的匹配度（余弦相似度）。"""
    if not profile:
        return 0.5  # 无画像时中性分

    dot = 0.0
    norm_c = 0.0
    norm_p = 0.0
    for dim in profile:
        c = float(current.get(dim, 0.5))
        p = float(profile[dim])
        dot += c * p
        norm_c += c * c
        norm_p += p * p

    denom = math.sqrt(max(norm_c, 1e-9)) * math.sqrt(max(norm_p, 1e-9))
    return dot / denom


def _infer_anchor_pos(template_str: str) -> str:
    """从模板字符串推断 anchor 位置。"""
    if "{anchor}" not in template_str:
        return "none"
    idx = template_str.index("{anchor}")
    total = len(template_str)
    # anchor 在前 1/3 → head，后 1/3 → tail，中间 → adj/embed
    ratio = idx / max(total, 1)
    if ratio < 0.3:
        return "head"
    elif ratio > 0.65:
        return "tail"
    else:
        return "adj"
