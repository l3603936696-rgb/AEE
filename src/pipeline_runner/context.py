"""PipelineContext — 穿透所有 pipeline 阶段的可变上下文对象。"""

from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional


class PipelineContext(SimpleNamespace):
    """
    所有 pipeline 阶段共享的可变状态容器。

    设计原则：
    - 阶段函数签名统一为 run_stage(ctx, entity)
    - 跨阶段变量通过 ctx.var 传递，阶段内部局部变量保持为普通 Python 局部变量
    - _trace 是 orchestrator 创建的闭包，通过 ctx._trace 传入各阶段

    添加属性时无需声明，直接赋值即可（SimpleNamespace）。
    """


def make_context(
    raw_input: Optional[str] = None,
    daemon_mode: bool = False,
    no_llm: bool = False,
    llm_callable: Optional[Any] = None,
    params_override: Optional[Dict] = None,
    debug: bool = False,
) -> PipelineContext:
    ctx = PipelineContext()
    ctx.raw_input = raw_input
    ctx.daemon_mode = daemon_mode
    ctx.no_llm = no_llm
    ctx.llm_callable = llm_callable
    ctx.params_override = params_override
    ctx.debug = debug

    # 预初始化跨阶段变量的默认值，防止后续阶段读取时 AttributeError
    ctx.snapshot = None
    ctx._snapshot_dict = None
    ctx.somatic_tone_start = 0.0
    ctx.state_snapshot = {}

    # 语言模块（s01_init 写入，后续阶段读取）
    ctx._quenching = None
    ctx._strategy_map = None
    ctx._thermal = None
    ctx._mirror = None
    ctx._five_rights = None
    ctx._semantic_analyzer = None
    ctx._candidate_gen = None
    ctx._behavior_profiler = None
    ctx._decay_engine = None

    # 预初始化默认值
    ctx.decision = {}
    ctx.concept_tags = []
    ctx.drive_vector_final = {}
    ctx.semantic_packet_biased = {}
    ctx.wm_context = {}
    ctx.loneliness_target = None
    ctx.connection_signature = {}
    ctx.connection_intermediates = {}
    ctx.dispatched_actions = []

    # 感知阶段输出
    ctx.semantic_packet = {}
    ctx._cx_parse_result = {}
    ctx.user_intent_from_input = {}
    ctx._defy_result = {"defy": False, "reason": "", "efficiency_boost": 1.0}
    ctx._recalled_insights = []
    ctx.tag_strings = []
    ctx.wm_snapshot = {}
    ctx.drive_vector = {}
    ctx.drive_params = {}
    ctx.curiosity_baseline = 0.2
    ctx.info_hunger_baseline = 0.24
    ctx.somatic_signals = {}
    ctx._attention_field = None

    # 思考阶段输出
    ctx._particle_field = None
    ctx._projection_ctrl = None
    ctx.thought_packet = {"suggestions": [], "questions": []}
    ctx._question_tension = 0.0
    ctx._ur_before_quench = None
    ctx._ur_after_quench = None

    # 状态更新阶段输出
    ctx.state_after_perceive = {}
    ctx.drive_state_fresh = {}
    ctx.somatic_signals_2 = {}
    ctx.refined_tone = 0.0
    ctx._pred_err = 0.0
    ctx._computed_emotions = {}
    ctx.prediction_error = 0.0
    ctx.matched_rules = []
    ctx.emergent = None
    ctx.emergent_action = "idle"
    ctx.emergent_priority = 0.3
    ctx.emergent_tension = 0.0
    ctx.emergent_target = ""
    ctx.emergent_dom_state = ""
    ctx.emergent_suggested_tool = ""
    ctx.emergent_bv = {}
    ctx.emergent_frag_tone = ""
    ctx.decision_params = {}

    # 行为阶段输出
    ctx.selected_candidate = None
    ctx.all_results = []
    ctx.all_action_results = []
    ctx.connection_depth_eff = 0.5
    ctx.somatic_tone_end = 0.0
    ctx.somatic_tone_delta = 0.0
    ctx.loneliness_intermediates = {}
    ctx.connection_trace = {}
    ctx.counterfactual_report = {}

    # 语言/输出阶段输出
    ctx.best_candidate = None
    ctx.best_score = 0.0
    ctx.dom_word = ""
    ctx.response = {"text": "", "confidence": 0.0, "generation_time_ms": 0}
    ctx.output_expression = ""
    ctx._lang_before_state = None
    ctx._lang_expression = ""
    ctx._lang_best_candidate = None
    ctx.fragmentation = 0.0

    # 回写阶段输出
    ctx.intent_repr = {}
    ctx.new_state = {}
    ctx.total_ms = 0.0
    ctx.before_unresolved = 0.0
    ctx.mainline_result = None
    ctx.result_dict = {}

    # s07a → s07b/c 跨阶段变量（消力闭环所需的前后状态值）
    ctx._ur_before_quench = None
    ctx._ur_after_quench = None
    ctx._lone_surf_before = None
    ctx._lone_surf_after_quench = None
    ctx._boredom_before = None
    ctx._boredom_after_quench = None
    ctx._state_for_update = {}
    ctx._unresolvable_episodes = []

    # orchestrator 注入的运行时字段
    ctx._trace = None
    ctx.t0 = 0.0
    ctx.trace = []

    return ctx
