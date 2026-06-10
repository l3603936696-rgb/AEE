"""
Life Protocol — 生命性验证入口。

本文件为入口模块：
- 从 life_protocol_schema 导出 dataclass 和常量
- 从 life_protocol_runner 导出 SimulationRunner
- 从 life_protocol_tests 导出 Level 1/2/3 测试类
- 提供 run_life_protocol() 和 CLI 入口

使用：python -m src.evaluation.life_protocol [--quick]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict

from .life_protocol_runner import LOG_FILE, SimulationRunner
from .life_protocol_tests import Level1StabilityTests, Level2StructureTests, Level3LifenessTests
from .life_protocol_schema import TickMetrics, _bias_variance

__all__ = [
    "TickMetrics",
    "SimulationRunner",
    "Level1StabilityTests",
    "Level2StructureTests",
    "Level3LifenessTests",
    "run_life_protocol",
]

_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = _ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
RESULT_FILE = DATA_DIR / "life_protocol_result.json"


def _write_jsonl(metrics: TickMetrics):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics.__dict__, ensure_ascii=False) + "\n")


def run_life_protocol(
    ticks_normal: int = 2000,
    ticks_force: int = 50,
    ticks_attractor: int = 300,
    ticks_reversal: int = 100,
    ticks_constraint: int = 200,
    ticks_isolation: int = 300,
) -> Dict[str, Any]:
    if LOG_FILE.exists():
        LOG_FILE.unlink()
    results: Dict[str, Any] = {}

    print("[LifeProtocol] === Run A: 正常模式 {} ticks ===".format(ticks_normal))
    runner_a = SimulationRunner(ticks=ticks_normal, external_input=True, seed=42)
    metrics_a = runner_a.run(progress_callback=lambda done, total: done % 100 == 0 and print(f"  {done}/{total}"))
    for m in metrics_a:
        _write_jsonl(m)

    l1 = Level1StabilityTests(metrics_a)
    results["level_1"] = l1.run()
    print(f"[LifeProtocol] Level 1: {'PASS' if results['level_1']['pass_all'] else 'FAIL'}")

    l2 = Level2StructureTests(metrics_a)
    results["level_2"] = l2.run()
    print(f"[LifeProtocol] Level 2: pass {results['level_2']['pass_count']}/3")

    l3_self = Level3LifenessTests(runner_a, metrics_a)

    print("[LifeProtocol] === Level 3.3: Self-constraint {} ticks ===".format(ticks_constraint))
    r3 = l3_self.test_3_3_self_constraint(ticks_constraint)

    print("[LifeProtocol] === Level 3.4: Isolation {} ticks ===".format(ticks_isolation))
    r4 = l3_self.test_3_4_isolation(ticks_isolation)

    print("[LifeProtocol] === Level 3.1: Attractor recovery ===")
    l3_full = Level3LifenessTests(runner_a, metrics_a)
    r1 = l3_full.test_3_1_attractor_recovery(
        perturb_ticks=min(300, ticks_normal), recover_ticks=ticks_attractor)

    print("[LifeProtocol] === Level 3.2: Reward reversal ===")
    r2 = l3_full.test_3_2_reward_reversal(ticks_reversal)

    results["level_3"] = {
        "level": 3,
        "tests": [r1, r2, r3, r4],
        "pass_count": sum(1 for t in [r1, r2, r3, r4] if t["passed"]),
    }
    print(f"[LifeProtocol] Level 3: pass {results['level_3']['pass_count']}/4")

    mv = [m for m in metrics_a if m.tick > 0]
    results["key_metrics"] = {
        "entropy_avg": round(sum(m.entropy for m in mv) / max(len(mv), 1), 4),
        "coherence_avg": round(sum(m.action_coherence for m in mv) / max(len(mv), 1), 4),
        "bias_variance_final": round(_bias_variance(metrics_a[-1].long_term_bias if metrics_a else {}), 5),
        "identity_avg": round(sum(m.identity_signal for m in mv) / max(len(mv), 1), 4),
    }

    l2_pass = results["level_2"]["pass_count"] >= 2
    l3_pass = results["level_3"]["pass_count"] >= 2
    if results["level_1"]["pass_all"] and l2_pass and l3_pass:
        results["summary"] = "Level 3 PASSED — 系统具备生命性特征"
    elif results["level_1"]["pass_all"] and l2_pass:
        results["summary"] = "Level 2 PASSED — 系统具备结构性"
    elif results["level_1"]["pass_all"]:
        results["summary"] = "Level 1 PASSED — 系统稳定"
    else:
        results["summary"] = "FAILED — 系统存在稳定性问题"

    return results


def main():
    parser = argparse.ArgumentParser(description="Life Protocol v1.0 — 生命性验证")
    parser.add_argument("--ticks", type=int, default=2000)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    if args.quick:
        ticks = 500; ticks_attractor = 100; ticks_reversal = 50
        ticks_constraint = 100; ticks_isolation = 100
    else:
        ticks = args.ticks; ticks_attractor = 300; ticks_reversal = 100
        ticks_constraint = 200; ticks_isolation = 300

    print("=" * 60)
    print("  Life Protocol v1.0 — 生命性验证")
    print("  ticks={} | quick={}".format(ticks, args.quick))
    print("=" * 60)
    start = time.time()

    result = run_life_protocol(
        ticks_normal=ticks, ticks_attractor=ticks_attractor,
        ticks_reversal=ticks_reversal, ticks_constraint=ticks_constraint,
        ticks_isolation=ticks_isolation,
    )
    elapsed = time.time() - start

    with open(RESULT_FILE, "w", encoding="utf-8") as f:
        result["_meta"] = {
            "elapsed_seconds": round(elapsed, 1),
            "ticks": ticks,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        json.dump(result, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 60)
    print("  结果：", result["summary"])
    print("  Level 1:", "PASS" if result["level_1"]["pass_all"] else "FAIL")
    print("  Level 2:", f'pass {result["level_2"]["pass_count"]}/3')
    print("  Level 3:", f'pass {result["level_3"]["pass_count"]}/4')
    print("  耗时: {:.1f}s".format(elapsed))
    print("=" * 60)
    print(f"\n  详细结果: {RESULT_FILE}")
    print(f"  Metrics 日志: {LOG_FILE}")


if __name__ == "__main__":
    main()
