"""
Response Cache — 响应预热缓存

功能：
    存储最近 daemon tick 的 (drive_vector, response_text, tick) 三元组，
    对话请求到达时，在 5 维驱动力空间中做余弦相似度匹配，
    高相似度时直接返回缓存响应，跳过 LLM 调用。

驱动空间维度：
    curiosity, info_hunger, obsolescence_anxiety, loneliness_drive, fatigue_avoid

核心类：ResponseCache
    update(dv, text, tick) → 追加缓存条目
    match(query_dv)        → (best_text, similarity)
    size()                 → 缓存条目数

设计原则：
    - 连续信号路由（max() over weighted dicts）
    - 线程安全（threading.Lock）
    - 容量固定（默认 3 条），FIFO 淘汰
"""

from .response_cache import ResponseCache, CachedResponse
