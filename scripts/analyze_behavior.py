#!/usr/bin/env python3
"""
XIA 行为日志分析器
将 manifest.jsonl 转换为可读的行为轨迹和情绪曲线

输出：
  - data/timeline.txt   行为时间线
  - data/curve.csv      情绪曲线数据
  - data/highlights.txt 关键片段
"""

import json
import csv
import os
import sys
from datetime import datetime
from collections import defaultdict

MANIFEST_PATH = "/home/bcyq/XIA/data/xia_voice/manifest.jsonl"
OUTPUT_DIR = "/home/bcyq/XIA/data/behavior_analysis"


# ─────────────────────────────────────────────────────────────
# 行为摘要生成
# ─────────────────────────────────────────────────────────────
_ACTION_LABELS = {
    "voice":   "表达",
    "reach":   "敲门",
    "silence": "沉默",
    "comfort": "安慰",
    "search":  "搜索",
    "rest":    "休息",
    "unknown": "未知",
}

def summarize_action(record: dict) -> str:
    """基于 action_type + context 生成一句中文行为摘要。"""
    atype = record.get("action_type", "unknown")
    ctx = record.get("context", {})
    content = record.get("content", "") or record.get("payload", {}).get("content_preview", "")
    loneliness = ctx.get("loneliness", 0.0)
    boredom = ctx.get("boredom", 0.0)
    stress = ctx.get("stress", 0.0)

    label = _ACTION_LABELS.get(atype, atype)

    # 内容截断
    snippet = content[:50].replace("\n", " ").strip()

    # 根据类型生成摘要
    if atype == "voice":
        if loneliness > 0.6:
            summary = f"表达了孤独感（loneliness={loneliness:.2f}）"
        elif boredom > 0.7:
            summary = f"表达了无聊感（boredom={boredom:.2f}）"
        elif loneliness > 0.3:
            summary = f"表达了轻度孤独（loneliness={loneliness:.2f}）"
        else:
            summary = f"主动发言"
        if snippet:
            summary += f"：{snippet}..."

    elif atype == "reach":
        if loneliness > 0.6:
            summary = f"主动敲门求关注（loneliness={loneliness:.2f}）"
        elif boredom > 0.7:
            summary = f"主动敲门找事做（boredom={boredom:.2f}）"
        else:
            summary = f"主动敲门"
        if snippet:
            summary += f"：{snippet}..."

    elif atype == "silence":
        if loneliness > 0.6:
            summary = f"沉默，感到孤独（loneliness={loneliness:.2f}）"
        elif boredom > 0.7:
            summary = f"沉默，感到无聊（boredom={boredom:.2f}）"
        else:
            summary = f"安静等待"

    elif atype == "search":
        summary = "搜索信息"
        if snippet:
            summary += f"：{snippet[:40]}..."

    elif atype == "rest":
        summary = "进入休息状态"

    else:
        summary = f"[{label}]"
        if snippet:
            summary += f" {snippet[:40]}..."

    return summary


def format_timestamp(ts: float) -> str:
    """Unix时间戳 → 可读时间字符串。"""
    try:
        dt = datetime.fromtimestamp(ts)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return f"{ts}"


# ─────────────────────────────────────────────────────────────
# 主分析逻辑
# ─────────────────────────────────────────────────────────────
def load_records(path: str) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    # 按 tick 排序（确保时序正确）
    records.sort(key=lambda r: r.get("tick", 0))
    return records


def generate_timeline(records: list[dict]) -> str:
    """生成 timeline.txt 内容。"""
    lines = []
    lines.append("=" * 72)
    lines.append("XIA 行为时间线")
    lines.append("=" * 72)
    lines.append(f"总记录数: {len(records)}")
    lines.append(f"时间范围: {format_timestamp(records[0]['timestamp'])} → {format_timestamp(records[-1]['timestamp'])}")
    lines.append("-" * 72)

    for r in records:
        tick = r.get("tick", "?")
        ts = format_timestamp(r["timestamp"])
        atype = r.get("action_type", "unknown")
        summary = summarize_action(r)

        ctx = r.get("context", {})
        loneliness = ctx.get("loneliness", 0.0)
        boredom = ctx.get("boredom", 0.0)
        stress = ctx.get("stress", 0.0)

        # 状态旁注
        state_parts = []
        if loneliness > 0.01:
            state_parts.append(f"loneliness={loneliness:.2f}")
        if boredom > 0.01:
            state_parts.append(f"boredom={boredom:.2f}")
        if stress > 0.01:
            state_parts.append(f"stress={stress:.2f}")
        state_str = " | " + " ".join(state_parts) if state_parts else ""

        lines.append(f"[{tick:>4}] [{ts}] {summary}{state_str}")

    return "\n".join(lines)


def generate_curve_csv(records: list[dict]) -> str:
    """生成 curve.csv 内容。"""
    lines = []
    lines.append("tick,timestamp,loneliness,boredom,stress,somatic_tone,action_type")

    for r in records:
        tick = r.get("tick", 0)
        ts = r.get("timestamp", 0)
        ctx = r.get("context", {})
        loneliness = ctx.get("loneliness", 0.0)
        boredom = ctx.get("boredom", 0.0)
        stress = ctx.get("stress", 0.0)
        somatic = ctx.get("somatic_tone", 0.0)
        atype = r.get("action_type", "unknown")
        lines.append(
            f"{tick},{ts:.0f},{loneliness:.6f},{boredom:.6f},"
            f"{stress:.6f},{somatic:.6f},{atype}"
        )

    return "\n".join(lines)


def generate_highlights(records: list[dict]) -> str:
    """生成 highlights.txt 内容。"""
    lines = []
    lines.append("=" * 72)
    lines.append("XIA 关键行为片段")
    lines.append("=" * 72)
    lines.append("筛选规则：loneliness > 0.6 | voice | 连续 reach >= 3")
    lines.append("-" * 72)

    # 统计 reach 连续次数
    reach_streak = 0
    reach_streak_start = None
    highlighted_indices = set()

    for i, r in enumerate(records):
        atype = r.get("action_type", "unknown")
        ctx = r.get("context", {})
        loneliness = ctx.get("loneliness", 0.0)

        # 标记 highlight
        is_highlight = False

        if loneliness > 0.6:
            is_highlight = True
        if atype == "voice":
            is_highlight = True

        # reach 连续计数
        if atype == "reach":
            if reach_streak == 0:
                reach_streak_start = i
            reach_streak += 1
        else:
            if reach_streak >= 3:
                for j in range(reach_streak_start, i):
                    highlighted_indices.add(j)
            reach_streak = 0
            reach_streak_start = None

        if is_highlight:
            highlighted_indices.add(i)

    # 处理末尾连续 reach
    if reach_streak >= 3:
        for j in range(reach_streak_start, len(records)):
            highlighted_indices.add(j)

    # 生成 highlight 记录
    highlight_records = [records[i] for i in sorted(highlighted_indices) if i < len(records)]

    for r in highlight_records:
        tick = r.get("tick", "?")
        ts = format_timestamp(r["timestamp"])
        atype = r.get("action_type", "unknown")
        ctx = r.get("context", {})
        loneliness = ctx.get("loneliness", 0.0)
        boredom = ctx.get("boredom", 0.0)
        stress = ctx.get("stress", 0.0)
        content = r.get("content", "") or r.get("payload", {}).get("content_preview", "")

        # 原因标注
        reason_parts = []
        if loneliness > 0.6:
            reason_parts.append(f"loneliness={loneliness:.2f}")
        if atype == "voice":
            reason_parts.append("voice")
        if atype == "reach":
            reason_parts.append("reach")

        reason_str = " | ".join(reason_parts)

        lines.append("")
        lines.append(f"─── [{tick}] {ts} ─ {reason_str} ─────────────────────────")
        if content.strip():
            lines.append(f"内容：{content[:120].replace(chr(10), ' ')}")
        else:
            lines.append(f"原因：{r.get('reason', '')[:120].replace(chr(10), ' ')}")

    # 统计摘要
    lines.append("")
    lines.append("=" * 72)
    lines.append("统计摘要")
    lines.append("-" * 72)

    loneliness_vals = [r.get("context", {}).get("loneliness", 0.0) for r in records]
    boredom_vals = [r.get("context", {}).get("boredom", 0.0) for r in records]

    voice_count = sum(1 for r in records if r.get("action_type") == "voice")
    reach_count = sum(1 for r in records if r.get("action_type") == "reach")
    silence_count = sum(1 for r in records if r.get("action_type") == "silence")

    lines.append(f"总 tick 数：{len(records)}")
    lines.append(f"voice 次数：{voice_count}")
    lines.append(f"reach 次数：{reach_count}")
    lines.append(f"silence 次数：{silence_count}")
    lines.append(f"关键片段数：{len(highlight_records)}")
    if loneliness_vals:
        lines.append(f"loneliness 均值：{sum(loneliness_vals)/len(loneliness_vals):.4f}")
        lines.append(f"loneliness 最大值：{max(loneliness_vals):.4f}")
    if boredom_vals:
        lines.append(f"boredom 均值：{sum(boredom_vals)/len(boredom_vals):.4f}")
        lines.append(f"boredom 最大值：{max(boredom_vals):.4f}")

    return "\n".join(lines)


def main():
    if not os.path.exists(MANIFEST_PATH):
        print(f"[ERROR] manifest.jsonl not found: {MANIFEST_PATH}")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"[分析器] 加载 manifest.jsonl...")
    records = load_records(MANIFEST_PATH)
    print(f"[分析器] 共 {len(records)} 条记录")

    print("[分析器] 生成 timeline.txt...")
    timeline_txt = generate_timeline(records)
    timeline_path = os.path.join(OUTPUT_DIR, "timeline.txt")
    with open(timeline_path, "w", encoding="utf-8") as f:
        f.write(timeline_txt)
    print(f"[分析器] → {timeline_path}")

    print("[分析器] 生成 curve.csv...")
    curve_csv = generate_curve_csv(records)
    curve_path = os.path.join(OUTPUT_DIR, "curve.csv")
    with open(curve_path, "w", encoding="utf-8") as f:
        f.write(curve_csv)
    print(f"[分析器] → {curve_path}")

    print("[分析器] 生成 highlights.txt...")
    highlights_txt = generate_highlights(records)
    highlights_path = os.path.join(OUTPUT_DIR, "highlights.txt")
    with open(highlights_path, "w", encoding="utf-8") as f:
        f.write(highlights_txt)
    print(f"[分析器] → {highlights_path}")

    print()
    print(f"[完成] 输出目录：{OUTPUT_DIR}")
    print(f"  timeline.txt   — 行为时间线")
    print(f"  curve.csv      — 情绪曲线（可用 Excel/图表工具打开）")
    print(f"  highlights.txt — 关键片段")


if __name__ == "__main__":
    main()
