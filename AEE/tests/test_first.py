"""
XIA 第一次测试运行器

用法：
    python3 test_first.py
    python3 test_first.py --debug

测试覆盖：
    1. 模块级自测（各子模块 __main__）
    2. 同步管线集成测试（6个场景）
    3. 多轮对话压力测试
    4. 状态演化验证
"""

import sys
import time
import argparse

sys.path.insert(0, ".")
sys.path.insert(0, "./lib")

from AEE.src.entity_zero_iteration import (
    run_pipeline,
    reset_entity_state,
    get_entity_state,
)


# ============================================================================
# LLM 配置（None 表示使用 output_layer 默认的 Ollama）
# ============================================================================
# llm_callable = None  # 真实 LLM（需先启动 ollama serve）
# llm_callable = make_mock_llm()  # Mock（无需 Ollama）

# 用 mock 还是真实，取决于 Ollama 是否在跑
_USE_REAL_LLM = False  # 默认用 mock


def _get_llm_callable():
    if _USE_REAL_LLM:
        return None
    def mock_llm(system_prompt, user_prompt, temperature, max_tokens, timeout_ms):
        return "嗯，我听到了。", None
    return mock_llm


# ============================================================================
# 测试场景
# ============================================================================

SCENARIOS = [
    # (raw_input, description)
    ("你好呀！", "打招呼"),
    ("我今天特别开心！", "分享正面情绪"),
    ("怎么解决这个问题？", "求助意图"),
    ("我好烦啊，什么破事", "抱怨负面情绪"),
    ("凭什么要听你的！", "挑战对抗"),
    ("快去做作业！", "指令"),
    ("你懂什么", "质疑"),
    ("今天考试过了哈哈！", "分享好消息"),
    ("你觉得怎么样？", "征求意见"),
    (None, "内部 tick（无输入）"),
]


# ============================================================================
# 测试函数
# ============================================================================

def test_basic():
    """基础同步管线测试"""
    print("\n" + "=" * 64)
    print("测试 1：基础同步管线（6个场景）")
    print("=" * 64)

    reset_entity_state()
    entity = get_entity_state()
    llm = _get_llm_callable()

    for raw_input, desc in SCENARIOS:
        print(f"\n【{desc}】")
        label = raw_input if raw_input else "<内部 tick>"
        print(f"  输入: {label}")

        result = run_pipeline(
            raw_input=raw_input,
            entity_state=entity,
            debug=False,
            llm_callable=llm,
        )

        decision = result["decision"]
        state = result["state_snapshot"]
        drive = result["drive_vector"]

        print(f"  决策: {decision['action_type']} | {decision['target']} | p={decision['priority']:.3f}")
        print(f"  回应: {result['response']['text']}")
        print(f"  状态: energy={state['energy']:.3f} fatigue={state['fatigue']:.3f} loneliness={state['loneliness']:.3f}")
        print(f"  驱动力: curiosity={drive['curiosity']:.3f} info_hunger={drive['info_hunger']:.3f}")
        print(f"  耗时: {result['total_ms']:.1f}ms | tick={result['tick']}")

    print(f"\n最终状态: tick={entity.tick}, snapshots={len(entity.snapshots)}, memory={len(entity.memory_context)}")
    print("✓ 测试 1 完成\n")
    return entity


def test_multi_round(n=20):
    """多轮对话压力测试"""
    print("\n" + "=" * 64)
    print(f"测试 2：多轮对话压力测试（{n}轮）")
    print("=" * 64)

    reset_entity_state()
    entity = get_entity_state()
    llm = _get_llm_callable()

    dialogues = [
        "你好！",
        "最近怎么样？",
        "我今天心情不错！",
        "有什么新鲜事吗？",
        "你饿了吗？",
        "我有点累",
        "想休息一下",
        "好无聊啊",
        "有什么有趣的吗？",
        "给我讲个笑话",
    ]

    decisions = []
    start = time.time()

    for i in range(n):
        raw_input = dialogues[i % len(dialogues)]
        result = run_pipeline(
            raw_input=raw_input,
            entity_state=entity,
            debug=False,
            llm_callable=llm,
        )
        decisions.append(result["decision"]["action_type"])

    elapsed = time.time() - start
    avg_ms = (elapsed / n) * 1000

    print(f"\n  总轮数: {n}")
    print(f"  总耗时: {elapsed*1000:.1f}ms")
    print(f"  平均耗时: {avg_ms:.1f}ms/轮")
    print(f"  最终 tick: {entity.tick}")
    print(f"  最终 energy: {entity.energy:.3f}")
    print(f"  最终 fatigue: {entity.fatigue:.3f}")
    print(f"  最终 loneliness: {entity.loneliness:.3f}")
    print(f"  决策分布: seek={decisions.count('seek')} avoid={decisions.count('avoid')} comfort={decisions.count('comfort')}")
    print(f"  经验快照: {len(entity.snapshots)} 条")

    assert entity.tick == n, f"tick 应为 {n}"
    assert 0 <= entity.energy <= 1, "energy 应在 [0,1]"
    assert 0 <= entity.fatigue <= 1, "fatigue 应在 [0,1]"

    print(f"\n✓ 测试 2 完成\n")
    return entity


def test_state_evolution():
    """状态演化验证"""
    print("\n" + "=" * 64)
    print("测试 3：状态演化验证")
    print("=" * 64)

    reset_entity_state()
    entity = get_entity_state()
    llm = _get_llm_callable()

    # 记录初始状态
    result0 = run_pipeline(raw_input="你好", entity_state=entity, debug=False, llm_callable=llm)
    e0 = entity.energy
    f0 = entity.fatigue
    print(f"\n  初始状态: energy={e0:.3f} fatigue={f0:.3f}")

    # 执行 10 轮 seek 动作
    seek_count = 0
    for i in range(10):
        result = run_pipeline(
            raw_input="给我讲个故事",
            entity_state=entity,
            debug=False,
            llm_callable=llm,
        )
        if result["decision"]["action_type"] == "seek":
            seek_count += 1

    e10 = entity.energy
    f10 = entity.fatigue
    print(f"  10轮后状态: energy={e10:.3f} fatigue={f10:.3f}")
    print(f"  seek 动作次数: {seek_count}")

    # 验证：seek 消耗能量 → energy 应该下降
    energy_decreased = e10 < e0
    print(f"  能量下降验证: {e0:.3f} → {e10:.3f} {'✓' if energy_decreased else '✗ (警告)'}")

    # 执行 5 轮 comfort 动作
    comfort_count = 0
    for i in range(5):
        result = run_pipeline(
            raw_input="休息一下吧",
            entity_state=entity,
            debug=False,
            llm_callable=llm,
        )
        if result["decision"]["action_type"] == "comfort":
            comfort_count += 1

    e15 = entity.energy
    f15 = entity.fatigue
    print(f"  5轮comfort后: energy={e15:.3f} fatigue={f15:.3f}")
    print(f"  comfort 动作次数: {comfort_count}")

    print(f"\n✓ 测试 3 完成\n")
    return entity


def test_decision_diversity():
    """决策多样性验证"""
    print("\n" + "=" * 64)
    print("测试 4：决策多样性验证（100轮随机输入）")
    print("=" * 64)

    reset_entity_state()
    entity = get_entity_state()
    llm = _get_llm_callable()

    inputs = [
        "你好！", "我开心", "我难过", "为什么", "怎么办",
        "好累啊", "哈哈", "烦死了", "开始吧", "快去做",
        "停止", "我饿了", "想睡觉", "我爱你", "滚",
        "好无聊", "真的吗", "你说的对", "不对", "加油",
    ]

    import random
    decisions = []
    for i in range(100):
        raw_input = random.choice(inputs)
        result = run_pipeline(
            raw_input=raw_input,
            entity_state=entity,
            debug=False,
            llm_callable=llm,
        )
        decisions.append(result["decision"]["action_type"])

    seek_count = decisions.count("seek")
    avoid_count = decisions.count("avoid")
    comfort_count = decisions.count("comfort")

    print(f"\n  seek:  {seek_count} ({seek_count}%)")
    print(f"  avoid: {avoid_count} ({avoid_count}%)")
    print(f"  comfort: {comfort_count} ({comfort_count}%)")

    # 验证：三类决策都应该出现（多样性）
    all_three = seek_count > 0 and avoid_count > 0 and comfort_count > 0
    print(f"  三类决策均出现: {'✓' if all_three else '✗ (警告：决策过于单一)'}")
    print(f"\n✓ 测试 4 完成\n")
    return entity


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="XIA 电子生命系统 — 第一次集成测试")
    parser.add_argument("--fast", action="store_true", help="仅运行快速测试")
    parser.add_argument("--real", action="store_true", help="使用真实 Ollama LLM（需先启动 ollama serve）")
    args = parser.parse_args()

    global _USE_REAL_LLM
    if args.real:
        _USE_REAL_LLM = True

    print("=" * 64)
    print("XIA 电子生命系统 — 第一次集成测试")
    print("=" * 64)
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"LLM: {'真实 Ollama (qwen2.5:3b)' if _USE_REAL_LLM else 'Mock（无需 Ollama）'}")
    print("=" * 64)

    all_pass = True

    try:
        test_basic()
    except Exception as e:
        print(f"✗ 测试 1 失败: {e}")
        all_pass = False

    try:
        test_multi_round(n=20)
    except Exception as e:
        print(f"✗ 测试 2 失败: {e}")
        all_pass = False

    if not args.fast:
        try:
            test_state_evolution()
        except Exception as e:
            print(f"✗ 测试 3 失败: {e}")
            all_pass = False

        try:
            test_decision_diversity()
        except Exception as e:
            print(f"✗ 测试 4 失败: {e}")
            all_pass = False

    print("=" * 64)
    if all_pass:
        print("✓ 全部测试通过")
    else:
        print("✗ 部分测试失败")
    print("=" * 64)


if __name__ == "__main__":
    main()
