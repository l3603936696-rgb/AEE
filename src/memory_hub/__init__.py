"""
Memory Hub — 记忆与内脏感觉中枢

子模块：
    - tetramem_adapter : TetraMem 外部记忆服务适配器（含降级写/读）
    - insula_hub       : 内脏感觉中枢（拓扑指标 → 躯体标记）
    - episodes_db      : 原始事件日志持久化层（SQLite，永远先写）
"""

from .tetramem_adapter import (
    log_experience_with_context,
    execute_sleep_cycle,
    get_topology_metrics,
    retrieve_memories,
    ExperienceLog,
    StateSnapshot,
    TopoMetrics,
)

from .insula_hub import (
    calculate_memory_pressure_from_topology,
    calculate_somatic_signal,
)

from .episodes_db import (
    init_db,
    write_episode,
    write_episode_async,
    build_episode,
    get_recent_episodes,
    get_episode_by_id,
    get_episodes_for_induction,
    get_episode_count,
    prune_low_importance,
    retrieve_episodes_by_text,
    Episode,
)

__all__ = [
    # tetramem_adapter
    "log_experience_with_context",
    "execute_sleep_cycle",
    "get_topology_metrics",
    "retrieve_memories",
    "ExperienceLog",
    "StateSnapshot",
    "TopoMetrics",
    # insula_hub
    "calculate_memory_pressure_from_topology",
    "calculate_somatic_signal",
    # episodes_db
    "init_db",
    "write_episode",
    "write_episode_async",
    "build_episode",
    "get_recent_episodes",
    "get_episode_by_id",
    "get_episodes_for_induction",
    "get_episode_count",
    "prune_low_importance",
    "retrieve_episodes_by_text",
    "Episode",
]
