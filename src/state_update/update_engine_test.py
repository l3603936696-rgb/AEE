"""
Inline tests extracted from update_engine.py.

Run with: python -m src.state_update.update_engine_test
"""

import time as _time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.state_update.update_engine import update_state, reset_info_queue
from src.state_update.update_engine_helpers import _safe_float


def make_params() -> dict:
    return {
        "state.relief_debt_pressure_threshold": 0.5,
        "state.relief_debt_accum_rate": 0.05,
        "state.relief_debt_reduce_rate": 0.08,
        "state.time_silence_recovery_damping_factor": 0.5,
    }


def print_state(label: str, state: dict) -> None:
    numeric = {k: v for k, v in state.items() if isinstance(v, (int, float)) and not k.startswith("_")}
    print(f"  {label}: " + ", ".join(f"{k}={v:.4f}" for k, v in numeric.items()))


def main() -> None:
    print("=" * 64)
    print("State Update Engine — 算力账本 v2.0 集成测试")
    print("=" * 64)

    params = make_params()

    # Test 1: deep copy contract
    print("\n【测试 1】接口契约 — 深拷贝验证")
    reset_info_queue()
    original = {"energy": 0.8, "loneliness": 0.3}
    result = update_state(original, None, 60.0, params)
    ok1 = result is not original and original.get("energy") == 0.8
    print(f"  {'PASS' if ok1 else 'FAIL'} 输出非原对象: {result is not original}")
    print(f"  {'PASS' if original.get('energy') == 0.8 else 'FAIL'} 原对象未被修改: energy={original.get('energy')}")

    # Test 2: rest → energy rises
    print("\n【测试 2】rest 行为 → energy 因负载降低而回升")
    reset_info_queue()
    state2 = {"energy": 0.5, "loneliness": 0.5, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.7, "stress": 0.3, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.6, "time_since_last_social": 300.0, "time_since_last_info": 300.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision2 = {"action_type": "rest", "target": "self"}
    result2 = update_state(state2, decision2, 60.0, params)
    ok2 = result2["energy"] > 0.5
    print(f"  {'PASS' if ok2 else 'FAIL'} energy: 0.5 → {result2['energy']:.4f}")
    print(f"  负载分解: {result2.get('_load_breakdown', {})}")

    # Test 3: comfort → energy rises
    print("\n【测试 3】comfort 行为 → 社交输入归零，energy 回升")
    reset_info_queue()
    state3 = {"energy": 0.5, "loneliness": 0.5, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.3, "stress": 0.2, "relief_debt": 0.0, "somatic_tone": 0.3,
               "info_gap": 0.5, "time_since_last_social": 300.0, "time_since_last_info": 300.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision3 = {"action_type": "comfort", "target": "user"}
    result3 = update_state(state3, decision3, 60.0, params)
    ok3 = result3["energy"] > 0.5
    print(f"  {'PASS' if ok3 else 'FAIL'} energy: 0.5 → {result3['energy']:.4f}")
    print(f"  loneliness: {result3['loneliness']:.4f}")

    # Test 4: pending_surprises world_model=None
    print("\n【测试 4】pending_surprises → surprise 放回队尾")
    reset_info_queue()
    state4 = {"energy": 0.5, "loneliness": 0.4, "unresolved": 0.3, "boredom": 0.2,
               "fatigue": 0.2, "stress": 0.5, "relief_debt": 0.0, "somatic_tone": 0.2,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [{"magnitude": 0.5, "created_at": _time.time()}],
               "_last_prediction_error": 0.0}
    decision4 = {"action_type": "comfort", "target": "user"}
    result4 = update_state(state4, decision4, 60.0, params, wm_rules=None)
    remaining = len(result4.get("pending_surprises", []))
    ok4 = remaining == 1
    print(f"  {'PASS' if ok4 else 'FAIL'} pending_surprises: 1 → {remaining}")
    print(f"  stress: 0.5 → {result4['stress']:.4f}")

    # Test 5: explore / rest info_gap
    print("\n【测试 5】explore → 队列积压，rest → info_gap 下降")
    reset_info_queue()
    state5 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.3, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.1,
               "info_gap": 0.8, "time_since_last_social": 60.0, "time_since_last_info": 600.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision5 = {"action_type": "explore", "target": "information"}
    result5_explore = update_state(state5, decision5, 60.0, params)
    explore_delta = result5_explore["info_gap"] - 0.8
    ok5a = abs(explore_delta) < 0.05
    print(f"  {'PASS' if ok5a else 'FAIL'} explore info_gap: 0.8 → {result5_explore['info_gap']:.4f}")
    result5_rest = update_state(result5_explore, {"action_type": "rest", "target": "self"}, 60.0, params)
    rest_delta = result5_rest["info_gap"] - 0.8
    ok5b = rest_delta < -0.05
    print(f"  {'PASS' if ok5b else 'FAIL'} rest info_gap: → {result5_rest['info_gap']:.4f}")
    ok5 = ok5a and ok5b

    # Test 6: decision=None
    print("\n【测试 6】decision=None 时正常运行")
    reset_info_queue()
    state6 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    result6 = update_state(state6, None, 60.0, params)
    ok6 = isinstance(result6, dict) and "energy" in result6
    print(f"  {'PASS' if ok6 else 'FAIL'} decision=None 不抛异常, energy={result6['energy']:.4f}")

    # Test 7: pending_surprises accumulation
    print("\n【测试 7】高预测误差 → pending_surprises 积累")
    reset_info_queue()
    state7 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
               "fatigue": 0.1, "stress": 0.2, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.6}
    result7 = update_state(state7, None, 60.0, params)
    ok7 = len(result7.get("pending_surprises", [])) > 0
    print(f"  {'PASS' if ok7 else 'FAIL'} pending_surprises: {len(result7.get('pending_surprises', []))} 个")

    # Test 8: clamp bounds
    print("\n【测试 8】clamp 边界保护")
    reset_info_queue()
    state8 = {"energy": 2.0, "loneliness": -1.0, "unresolved": 5.0, "boredom": -0.5,
               "fatigue": 1.5, "stress": -0.1, "relief_debt": 0.0, "somatic_tone": 2.0,
               "info_gap": 3.0, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    result8 = update_state(state8, None, 0.0, params)
    all_clamped = all(
        0.0 <= result8[k] <= 1.0
        for k in ("energy", "loneliness", "unresolved", "boredom", "fatigue", "stress", "info_gap")
    ) and -1.0 <= result8.get("somatic_tone", 0.0) <= 1.0
    print(f"  {'PASS' if all_clamped else 'FAIL'} 所有字段在合法范围内")
    print(f"    energy={result8['energy']:.4f}, somatic_tone={result8.get('somatic_tone', 0):.4f}")

    # Test 9: negative emotion → emotional load higher
    print("\n【测试 9】somatic_tone 偏负 → emotional 占用更高")
    reset_info_queue()
    state9a = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
                "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": 0.0,
                "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
                "pending_surprises": [], "_last_prediction_error": 0.0}
    state9b = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.2, "boredom": 0.2,
                "fatigue": 0.1, "stress": 0.1, "relief_debt": 0.0, "somatic_tone": -0.7,
                "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
                "pending_surprises": [], "_last_prediction_error": 0.0}
    result9a = update_state(state9a, None, 60.0, params)
    result9b = update_state(state9b, None, 60.0, params)
    load_a = result9a.get("_load_breakdown", {})
    load_b = result9b.get("_load_breakdown", {})
    emotional_a = load_a.get("emotional", 0.0)
    emotional_b = load_b.get("emotional", 0.0)
    ok9 = emotional_b > emotional_a
    print(f"  {'PASS' if ok9 else 'FAIL'} emotional: neutral={emotional_a:.4f}, negative={emotional_b:.4f}")
    print(f"  energy: neutral={result9a['energy']:.4f}, negative={result9b['energy']:.4f}")

    # Test 10: rest → fatigue recovers faster
    print("\n【测试 10】rest 期间 → fatigue 恢复加速")
    reset_info_queue()
    state10 = {"energy": 0.5, "loneliness": 0.3, "unresolved": 0.6, "boredom": 0.2,
               "fatigue": 0.6, "stress": 0.3, "relief_debt": 0.0, "somatic_tone": 0.0,
               "info_gap": 0.5, "time_since_last_social": 60.0, "time_since_last_info": 60.0,
               "pending_surprises": [], "_last_prediction_error": 0.0}
    decision10 = {"action_type": "rest", "target": "self"}
    result10 = update_state(state10, decision10, 120.0, params)
    ok10 = result10["fatigue"] < 0.6
    print(f"  {'PASS' if ok10 else 'FAIL'} fatigue: 0.6 → {result10['fatigue']:.4f}")
    print(f"  unresolved: 0.6 → {result10['unresolved']:.4f}")

    print("\n" + "=" * 64)
    all_ok = all([ok1, ok2, ok3, ok4, ok5, ok6, ok7, all_clamped, ok9, ok10])
    print(f"测试结果: {'全部通过' if all_ok else '部分失败'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
