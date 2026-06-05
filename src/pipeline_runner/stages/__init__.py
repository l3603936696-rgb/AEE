# pipeline stages package

"""
Pipeline Stages — 认知管线各阶段实现

执行顺序：
    s01_init.py          → 参数快照 + 语言模块初始化
    s02_perception.py    → 语义感知 + 驱动力 + 感质
    s02b_input_drive_map → 输入→drive空间映射（理解机制入口）
    s02c_delayed_understanding → 延迟理解层（反刍）
    s03_think.py         → 情绪粒子 + 受限思考 + 情绪衰减
    s04a_meta.py         → 元认知状态调整（MC 噪声 / 反锁 / 物理约束）
    s04b_emerge.py        → 感知 + 情绪内生 + 行为涌现 + 预测误差
    s05_behavior.py       → 连接深度 + 孤独 + 行为模式 + decision 装配
    s06_language.py       → 候选词 + 输出（daemon/LLM）+ 语言闭环
    s07a_state_update.py  → 状态回写 + BP tick + 消力系统六通道
    s07b_persist.py       → 快照 + 记忆 + episode + 时间戳
    s07c_language_finalize.py → L3b 消力闭环 + L6 + 持久化 + 返回值

理解机制三阶段：
    s02b（输入→drive映射）→ interpretation_competition（解释竞争）→ s02c（延迟理解）

每个 stage 实现 run_stage(ctx, entity) 函数。
"""