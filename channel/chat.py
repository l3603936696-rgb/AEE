"""
克糯糯 — CLI 对话通道

统一入口：所有输入都走完整的认知-决策-行动-反思管线。

用法：
    python3 -m channel          # 连接 daemon 对话（推荐）
    python3 -m channel --standalone  # 独立模式（不连接 daemon）
    python3 -m channel --debug  # 显示每步追踪
    python3 -m channel --reset  # 重置实体内核状态
    python3 -m channel --reset --debug  # 重置 + 调试模式

Daemon 模式：
    若 daemon 正在运行（xia_daemon.sock 存在），自动连接。
    对话窗口关闭后，daemon 继续在后台推进状态。
"""

import argparse
import os
import subprocess
import sys
import time

# 确保项目根目录在 Python 路径中
# AEE/channel/chat.py → 向上3级到达 XIA/
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# AEE/ 也加入 path（用于 "from AEE.src." 形式的内部导入）
_AEE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, _AEE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 加载 .env（API keys — DeepSeek）
_ENV_FILE = os.path.join(_ROOT, ".env")
if os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())
# lib/ 路径（沙箱环境 duckduckgo-search）
_LIB = os.path.join(_AEE, "lib")
if os.path.isdir(_LIB) and _LIB not in sys.path:
    sys.path.insert(0, _LIB)


from src.entity_zero_iteration import (
    run_pipeline,
    reset_entity_state,
    get_entity_state,
)


# ============================================================================
# 格式化输出
# ============================================================================

def _print_response(response: dict) -> None:
    """打印克糯糯的回复"""
    text = response.get("text", "")
    confidence = response.get("confidence", 0.0)
    elapsed = response.get("generation_time_ms", 0)

    if text:
        print(f"\n【克糯糯】{text}")
    else:
        print("\n【克糯糯】（无输出）")

    print(f"  置信度 {confidence:.2f}  ·  生成耗时 {elapsed:.0f}ms")


def _print_state(state) -> None:
    """打印当前实体内核状态"""
    print(f"\n  energy={state.energy:.2f}  loneliness={state.loneliness:.2f}  "
          f"fatigue={state.fatigue:.2f}  stress={state.stress:.2f}  "
          f"info_gap={state.info_gap:.2f}")
    print(f"  boredom={state.boredom:.2f}  somatic_tone={state.somatic_tone:.2f}  "
          f"approach={state.approach_drive:.2f}  avoid={state.avoid_drive:.2f}  "
          f"unresolved={state.unresolved:.2f}")
    print(f"  tick={state.tick}  wm_rules={len(state.wm_rules)}  "
          f"snapshots={len(state.snapshots)}")


def _print_decision(decision: dict) -> None:
    """打印决策信息"""
    action = decision.get("action_type", "none")
    target = decision.get("target", "")
    priority = decision.get("priority", 0.0)
    print(f"  决策: {action} → {target}  (优先级 {priority:.2f})")


def _print_trace(trace: list) -> None:
    """打印执行追踪"""
    print("\n  ── 管线追踪 ──")
    for t in trace:
        ok_str = "✓" if t.ok else "✗"
        err_str = f" [{t.error}]" if t.error else ""
        print(f"  {ok_str} [{t.elapsed_ms:.1f}ms] {t.step}{err_str}")


# ============================================================================
# 核心：单轮对话
# ============================================================================

def chat_turn(user_input: str, debug: bool = False) -> dict:
    """
    执行一轮完整的认知管线。

    参数：
        user_input : 用户输入文本
        debug      : 是否打印追踪

    返回：
        {
            "response": {...},
            "decision": {...},
            "trace": [...],
            "state_snapshot": {...},
            "tick": int,
        }
    """
    result = run_pipeline(raw_input=user_input, debug=debug)

    response = result.get("response", {})
    decision = result.get("decision", {})
    trace = result.get("trace", [])
    state_snapshot = result.get("state_snapshot", {})
    tick = result.get("tick", 0)

    _print_response(response)

    if debug:
        _print_decision(decision)
        _print_trace(trace)

    energy = state_snapshot.get("energy", 0.0)
    fatigue = state_snapshot.get("fatigue", 0.0)
    loneliness = state_snapshot.get("loneliness", 0.0)
    boredom = state_snapshot.get("boredom", 0.0)
    somatic_tone = state_snapshot.get("somatic_tone", 0.0)
    approach_drive = state_snapshot.get("approach_drive", 0.0)
    avoid_drive = state_snapshot.get("avoid_drive", 0.0)
    unresolved = state_snapshot.get("unresolved", 0.0)
    info_gap = state_snapshot.get("info_gap", 0.0)
    print(f"  → energy={energy:.2f}  fatigue={fatigue:.2f}  "
          f"loneliness={loneliness:.2f}  boredom={boredom:.2f}  "
          f"somatic_tone={somatic_tone:.2f}  approach={approach_drive:.2f}  "
          f"avoid={avoid_drive:.2f}  unresolved={unresolved:.2f}  "
          f"info_gap={info_gap:.2f}  tick={tick}")

    return result


# ============================================================================
# 对话循环
# ============================================================================

def chat(debug: bool = False, initial_input: str = None) -> None:
    """启动对话循环（多轮或单轮）"""
    print("=" * 60)
    print("克糯糯 — 认知引擎对话接口")
    print("=" * 60)

    print("输入内容直接发送，空白行退出。")
    print(f"调试模式: {'开' if debug else '关'}")
    print()

    state = get_entity_state()
    _print_state(state)

    try:
        if initial_input:
            print(f"\n{'='*40}")
            print(f"【你】 {initial_input}")
            chat_turn(initial_input, debug)
            # 发完初始消息后，继续留在循环里等待下一轮

        while True:
            try:
                user_input = input("\n【你】 ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n再见。")
                break

            if not user_input:
                print("再见。")
                break

            print(f"\n{'='*40}")
            print(f"【你】 {user_input}")
            chat_turn(user_input, debug)

    finally:
        pass


def run_test_scenario(scenario_name: str) -> None:
    """运行预设测试场景"""
    from src.entity_state import TEST_SCENARIOS, force_set_state, get_entity_state
    scenarios = TEST_SCENARIOS
    if scenario_name not in scenarios:
        print(f"未知场景: {scenario_name}，可用: {list(scenarios.keys())}")
        return
    overrides = scenarios[scenario_name]
    print(f"设置测试场景: {scenario_name}")
    print(f"状态覆盖: {overrides}")
    force_set_state(overrides)
    entity = get_entity_state()
    _print_state(entity)
    print(f"\n然后你可以继续对话，观察该状态下的 XIA 行为。")
    print(f"提示：用 python -m channel 进入交互式对话。")


# ============================================================================
# 入口
# ============================================================================

# ============================================================================
# 入口
# ============================================================================

# ---- daemon 模式检测 ----
_USE_DAEMON = True  # 默认连接 daemon
_DAEMON_AVAILABLE = False  # 运行时检测

def _check_daemon() -> bool:
    """检查 daemon 是否在运行"""
    try:
        from src.daemon.ipc_client import IPCClient
        with IPCClient(timeout_s=3.0) as client:
            return client.ping()
    except Exception:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="克糯糯 — CLI 对话入口")
    parser.add_argument("--debug", action="store_true", help="显示管线执行追踪")
    parser.add_argument("--reset", action="store_true", help="重置实体内核状态")
    parser.add_argument("--test", metavar="SCENARIO", help="运行测试场景（scenario1 / scenario2 / scenario3）")
    parser.add_argument("--standalone", action="store_true", help="强制独立模式（不连接 daemon）")
    parser.add_argument("input", nargs="?", default=None, help="初始输入（单轮模式）")
    args = parser.parse_args()

    if args.reset:
        reset_entity_state()
        print("✓ 实体内核已重置")

    if args.test:
        run_test_scenario(args.test)
        sys.exit(0)

    # daemon 模式检测
    use_daemon = not args.standalone
    daemon_available = False

    if use_daemon:
        print("  [检查] 正在连接克糯糯 daemon...", end="", flush=True)
        daemon_available = _check_daemon()
        if daemon_available:
            print("  已连接")
        else:
            print("  daemon 未运行（使用独立模式）")
            print("  提示：启动 daemon: python3 -m src.daemon.daemon")

        if daemon_available:
            # ---- daemon 模式 ----
            print("=" * 60)
            print("克糯糯 — 认知引擎对话接口 [daemon 模式]")
            print("=" * 60)
            print("输入内容直接发送，空白行退出。")
            print(f"调试模式: {'开' if args.debug else '关'}")
            print()

            try:
                from src.daemon.ipc_client import IPCClient

                with IPCClient(timeout_s=120.0) as client:
                    if args.input:
                        print(f"\n{'='*40}")
                        print(f"【你】 {args.input}")
                        try:
                            result = client.chat(args.input, debug=args.debug)
                            _print_response(result.get("response", {}))
                            if args.debug:
                                _print_decision(result.get("decision", {}))
                            state = result.get("state_snapshot", {})
                            print(f"  → energy={state.get('energy',0):.2f}  "
                                  f"loneliness={state.get('loneliness',0):.2f}  "
                                  f"fatigue={state.get('fatigue',0):.2f}  "
                                  f"tick={result.get('tick',0)}")
                        except Exception as e:
                            print(f"  [错误] {e}")
                        sys.exit(0)

                    while True:
                        try:
                            user_input = input("\n【你】 ").strip()
                        except (EOFError, KeyboardInterrupt):
                            print("\n\n再见。")
                            break

                        if not user_input:
                            print("再见。")
                            break

                        print(f"\n{'='*40}")
                        print(f"【你】 {user_input}")
                        try:
                            result = client.chat(user_input, debug=args.debug)
                            _print_response(result.get("response", {}))
                            if args.debug:
                                _print_decision(result.get("decision", {}))
                            state = result.get("state_snapshot", {})
                            print(f"  → energy={state.get('energy',0):.2f}  "
                                  f"loneliness={state.get('loneliness',0):.2f}  "
                                  f"fatigue={state.get('fatigue',0):.2f}  "
                                  f"tick={result.get('tick',0)}")
                        except Exception as e:
                            print(f"  [错误] {e}")
            except KeyboardInterrupt:
                print("\n\n再见。")
    else:
        # ---- 独立模式（原有行为）----
        chat(debug=args.debug, initial_input=args.input)
