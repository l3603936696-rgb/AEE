"""
Observability Report — 人类可读 + JSON 报告生成器

用法：
    python -m src.observability.report        # 默认聚合摘要（<4000字符）
    python -m src.observability.report --verbose   # 完整逐模块细节
    python -m src.observability.report --json     # JSON 格式

默认输出（聚合摘要）：
    - 各 health 分组的计数
    - 异常组（sleeping/dormant/never_executed/persistent_fail）的模块名单
    - 每个 LLM 点一行式状态（mode / health / calls / 成败数）
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from .registry import (
    get_registry,
    _OBS_DIR,
    _REGISTRY_PATH,
    ModuleRecord,
    LLMCallRecord,
)


# ============================================================================
# 分组逻辑
# ============================================================================

def group_modules(registry) -> Dict[str, List[tuple]]:
    mods = registry.all_modules()
    groups = {
        "active": [],
        "sleeping": [],
        "dormant": [],
        "never_executed": [],
        "persistent_fail": [],
    }
    for name, rec in sorted(mods.items()):
        key = rec.health
        if key in groups:
            groups[key].append((name, rec))
        else:
            groups["never_executed"].append((name, rec))
    return groups


def group_llm(registry) -> Dict[str, List[tuple]]:
    calls = registry.all_llm_calls()
    groups = {
        "active": [],
        "sleeping": [],
        "dormant": [],
        "never_executed": [],
        "persistent_fail": [],
    }
    for name, rec in sorted(calls.items()):
        key = rec.health
        if key in groups:
            groups[key].append((name, rec))
        else:
            groups["never_executed"].append((name, rec))
    return groups


# ============================================================================
# 单行格式（verbose 细节用）
# ============================================================================

def _fmt_rate(successes: int, failures: int) -> str:
    total = successes + failures
    if total == 0:
        return "0/0"
    return f"{successes}/{total}"


def _fmt_ms(avg: float) -> str:
    if avg <= 0:
        return "-"
    return f"{avg:.1f}ms"


def _fmt_time(ts: float) -> str:
    if ts <= 0:
        return "never"
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts))


def format_module_row(name: str, rec: ModuleRecord) -> str:
    last_err = rec.last_error_summary[:50] if rec.last_error_summary else "-"
    conf_s = f" [x{rec.consecutive_failures}]" if rec.consecutive_failures > 0 else ""
    return (
        f"  {name:<42} {rec.calls:>4}c  "
        f"{_fmt_rate(rec.successes, rec.failures):>8}  "
        f"avg={_fmt_ms(rec.avg_duration_ms):<8}  "
        f"last={_fmt_time(rec.last_call_time)}  "
        f"err={last_err}{conf_s}"
    )


def format_llm_row(name: str, rec: LLMCallRecord) -> str:
    mode_icon = {
        "llm":      "LLM ",
        "fallback": "FALL",
        "failed":   "FAIL",
        "unknown":  "??? ",
    }.get(rec.current_mode, f"{rec.current_mode[:4]:4s}")

    return (
        f"  [{mode_icon}] {name:<34} {rec.calls:>3}c  "
        f"ok={_fmt_rate(rec.successes, rec.failures):>7}  "
        f"fb={_fmt_rate(rec.fallbacks, rec.calls - rec.fallbacks):>7}  "
        f"avg={_fmt_ms(rec.avg_duration_ms):<6}  "
        f"err={rec.last_error_summary[:55] if rec.last_error_summary else '-'}"
    )


# ============================================================================
# 紧凑摘要格式（默认，<4000 字符）
# ============================================================================

def format_summary(registry) -> str:
    """紧凑聚合摘要 — 默认输出模式。"""
    summary = registry.get_summary()
    groups = group_modules(registry)
    llm_groups = group_llm(registry)
    tick = registry.get_tick()
    mc = summary["module_counts"]
    llm_s = summary["llm_summary"]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    lines: List[str] = []
    lines.append("")
    lines.append(f"╔══════════════════════════════════════════════════════════════╗")
    lines.append(f"║  XIA 可观测性摘要  {now_str}  tick={tick}       ║")
    lines.append(f"╚══════════════════════════════════════════════════════════════╝")
    lines.append("")

    # 模块总览
    lines.append("【模块】总计={}  active={}  sleeping={}  dormant={}  never_exec={}  persistent_fail={}".format(
        mc["total_tracked"],
        mc["active"],
        mc["dormant_sleeping"] - sum(1 for _, r in groups["sleeping"] if True),
        sum(1 for _, r in groups["dormant"] if True),
        mc["never_executed"],
        mc["persistent_fail"],
    ))

    # 异常模块清单（sleeping / dormant / never_executed / persistent_fail）
    anomaly_groups = [
        ("persistent_fail", "持续失败（连续5+次异常）"),
        ("sleeping",        "休眠（近期沉默）"),
        ("dormant",         "蛰伏（调用过但沉寂）"),
        ("never_executed",  "从未执行"),
    ]
    has_anomaly = False
    for key, label in anomaly_groups:
        items = groups[key]
        if items:
            has_anomaly = True
            names = ", ".join(n for n, _ in items)
            lines.append(f"  [{label}] {names}")

    if not has_anomaly:
        lines.append("  (所有模块正常)")

    lines.append("")

    # LLM 调用总览
    sr = llm_s["success_rate"]
    sr_str = f"{sr:.1%}" if sr is not None else "N/A"
    lines.append("【LLM 调用】total={}  ok={}  fb={}  fail={}  成功率={}".format(
        llm_s["total_calls"],
        llm_s["successes"],
        llm_s["fallbacks"],
        llm_s["failures"],
        sr_str,
    ))

    # LLM 点一行式状态
    all_llm = (
        list(llm_groups["active"])
        + list(llm_groups["persistent_fail"])
        + list(llm_groups["sleeping"])
        + list(llm_groups["dormant"])
        + list(llm_groups["never_executed"])
    )
    for name, rec in all_llm:
        mode_icon = {
            "llm": "LLM", "fallback": "FBK", "failed": "FL", "unknown": "???"
        }.get(rec.current_mode, "?")
        lines.append(
            f"  [{mode_icon}|{rec.health[:3]}] {name}: {rec.calls}c "
            f"ok={rec.successes} fb={rec.fallbacks} fail={rec.failures}"
        )

    lines.append("")
    lines.append(f"Registry: {_REGISTRY_PATH}")
    return "\n".join(lines)


# ============================================================================
# 完整格式（--verbose）
# ============================================================================

def format_full(registry) -> str:
    """完整逐模块细节 — --verbose 模式。"""
    groups = group_modules(registry)
    llm_groups = group_llm(registry)
    summary = registry.get_summary()
    tick = registry.get_tick()
    mc = summary["module_counts"]
    llm_s = summary["llm_summary"]
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    lines: List[str] = []
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"  XIA 可观测性报告 [FULL]  |  {now_str}  |  tick={tick}")
    lines.append("=" * 80)
    lines.append("")
    lines.append("【模块总览】")
    lines.append(f"  总计追踪模块:  {mc['total_tracked']:>4}")
    lines.append(f"  活跃:          {mc['active']:>4}  (最近 tick 有调用)")
    lines.append(f"  休眠:          {mc['dormant_sleeping']:>4}  (调用过但近期沉默)")
    lines.append(f"  从未执行:       {mc['never_executed']:>4}  (注册过但从未调用)")
    lines.append(f"  持续失败:       {mc['persistent_fail']:>4}  (连续5次以上失败)")
    lines.append("")
    lines.append("【LLM 调用总览】")
    lines.append(f"  总调用:  {llm_s['total_calls']:>4}   成功: {llm_s['successes']:>4}   "
                 f"降级: {llm_s['fallbacks']:>4}   失败: {llm_s['failures']:>4}")
    sr = llm_s["success_rate"]
    lines.append(f"  成功率:  {sr:.1%}" if sr is not None else "  成功率:  N/A")
    lines.append("")

    # 活跃模块
    if groups["active"]:
        lines.append("【活跃】— 真正在跑的模块")
        for name, rec in groups["active"]:
            lines.append(format_module_row(name, rec))
        lines.append("")
    else:
        lines.append("【活跃】  (none)")

    # 持续失败
    if groups["persistent_fail"]:
        lines.append("【持续失败】— 连续 5+ 次异常")
        for name, rec in groups["persistent_fail"]:
            lines.append(format_module_row(name, rec))
        lines.append("")
    else:
        lines.append("【持续失败】  (none)")

    # 休眠
    if groups["sleeping"]:
        lines.append("【休眠】— 调用过但近期沉默（>20 tick 未激活）")
        for name, rec in groups["sleeping"]:
            lines.append(format_module_row(name, rec))
        lines.append("")
    else:
        lines.append("【休眠】  (none)")

    # 蛰伏
    if groups["dormant"]:
        lines.append("【蛰伏】— 调用过但沉寂")
        for name, rec in groups["dormant"]:
            lines.append(format_module_row(name, rec))
        lines.append("")
    else:
        lines.append("【蛰伏】  (none)")

    # 从未执行
    if groups["never_executed"]:
        lines.append("【从未执行】— 注册过但一次都没被调用过")
        for name, rec in groups["never_executed"]:
            lines.append(format_module_row(name, rec))
        lines.append("")
    else:
        lines.append("【从未执行】  (none)")

    # LLM 调用点
    lines.append("-" * 80)
    lines.append("【LLM 调用点状态】")
    all_llm = (
        list(llm_groups["active"])
        + list(llm_groups["persistent_fail"])
        + list(llm_groups["sleeping"])
        + list(llm_groups["dormant"])
        + list(llm_groups["never_executed"])
    )
    if all_llm:
        for name, rec in all_llm:
            lines.append(format_llm_row(name, rec))
    else:
        lines.append("  (no LLM calls tracked)")

    lines.append("")
    lines.append("-" * 80)
    lines.append(f"  Registry: {_REGISTRY_PATH}")
    lines.append(f"  Obs data: {_OBS_DIR}")
    lines.append("=" * 80)
    lines.append("")
    return "\n".join(lines)


# ============================================================================
# JSON 格式
# ============================================================================

def format_json(registry) -> Dict[str, Any]:
    summary = registry.get_summary()
    groups = group_modules(registry)
    llm_groups = group_llm(registry)

    def rec_to_dict(name: str, rec) -> Dict[str, Any]:
        return rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tick": registry.get_tick(),
        "summary": summary,
        "modules": {
            "active": {n: rec_to_dict(n, r) for n, r in groups["active"]},
            "persistent_fail": {n: rec_to_dict(n, r) for n, r in groups["persistent_fail"]},
            "sleeping": {n: rec_to_dict(n, r) for n, r in groups["sleeping"]},
            "dormant": {n: rec_to_dict(n, r) for n, r in groups["dormant"]},
            "never_executed": {n: rec_to_dict(n, r) for n, r in groups["never_executed"]},
        },
        "llm_calls": {
            "active": {n: rec_to_dict(n, r) for n, r in llm_groups["active"]},
            "persistent_fail": {n: rec_to_dict(n, r) for n, r in llm_groups["persistent_fail"]},
            "sleeping": {n: rec_to_dict(n, r) for n, r in llm_groups["sleeping"]},
            "dormant": {n: rec_to_dict(n, r) for n, r in llm_groups["dormant"]},
            "never_executed": {n: rec_to_dict(n, r) for n, r in llm_groups["never_executed"]},
        },
    }


# ============================================================================
# 入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="XIA 可观测性报告生成器")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--verbose", action="store_true", help="输出完整逐模块细节")
    parser.add_argument("--persist", action="store_true", help="强制持久化注册表")
    parser.add_argument("--reset", action="store_true", help="重置注册表")
    args = parser.parse_args()

    reg = get_registry()

    if args.reset:
        reg.reset()
        print("注册表已重置。")
        return

    if args.persist:
        reg.flush()
        print(f"已强制持久化到 {_REGISTRY_PATH}")

    if args.json:
        data = format_json(reg)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.verbose:
        text = format_full(reg)
        print(text)
    else:
        text = format_summary(reg)
        print(text)
        # 字符数提示
        char_count = len(text)
        print(f"\n  [-- report {char_count} chars --]")


if __name__ == "__main__":
    main()
