"""
Language System — 语言表达闭环（v7.0）

核心职责：用 LLM 代替 BGE 做语义分析闭环（v2 再部署 BGE-small）。

六大主权：
    自闭权  — avoid 高时触发防御性退行
    厌烦权  — 社交疲劳积累导致候选窗口收窄
    误解权  — 镜像学习，建立自己版本的理解
    遗忘权  — 负向关联记忆进入衰减队列
    顶撞权  — 检测外部侵入，拒绝执行次优策略
    物理重力 — fragmentation 映射为输出参数

导出：
    QuenchingTracker      — 消力效率测量
    StrategyMap           — 策略地图（即时缓存层）
    ThermalController     — 自适应温控
    MirrorLearner         — 镜像学习
    FiveRightsController  — 六大主权控制器
    SemanticAnalyzer      — LLM 语义锚点匹配（v1）
    CandidateGenerator    — 候选生成
    LinguisticAbundanceMonitor — 语言丰度监测
"""

from .quenching import QuenchingTracker
from .strategy_map import StrategyMap
from .thermal import ThermalController
from .mirror import MirrorLearner
from .five_rights import FiveRightsController
from .semantic_analyzer import SemanticAnalyzer
from .candidate_generator import CandidateGenerator
from .abundance_monitor import LinguisticAbundanceMonitor
from .somatic_concept_map import (
    get_somatic_delta,
    get_state_match_score,
    get_counter_delta,
    get_match_and_help,
    apply_help_delta,
    training_exploration_nudge,
    list_anchors,
)
from .meta_cognitive import analyze_snapshots, apply_meta_cognitive
from .somatic_dictionary import (SOMATIC_DICTIONARY, get_all_words, get_words_by_category, get_words_matching_state)
from .word_warmup import get_warm_words, generate_warmup_variants, inject_warmup_candidates
from .connector_map import (
    score_intensity_prefix,
    sample_intensity_prefix,
    score_opening_particle,
    sample_opening_particle,
    score_suffix_particle,
    sample_suffix_particle,
)
from .construction_grammar import ConstructionLearner

__all__ = [
    "QuenchingTracker",
    "StrategyMap",
    "ThermalController",
    "MirrorLearner",
    "FiveRightsController",
    "SemanticAnalyzer",
    "CandidateGenerator",
    "LinguisticAbundanceMonitor",
    "get_somatic_delta",
    "get_state_match_score",
    "get_counter_delta",
    "get_match_and_help",
    "apply_help_delta",
    "training_exploration_nudge",
    "list_anchors",
    "analyze_snapshots",
    "apply_meta_cognitive",
    "score_intensity_prefix",
    "sample_intensity_prefix",
    "score_opening_particle",
    "sample_opening_particle",
    "score_suffix_particle",
    "sample_suffix_particle",
    "ConstructionLearner",
]
