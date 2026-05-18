"""自动陪聊脚本 — 定时和 XIA / KNuoNuo 互动，给她们提供学习信号。

用法：
    python scripts/auto_interact.py                  # 默认同时陪两个人
    python scripts/auto_interact.py --xia-only       # 只陪 XIA
    python scripts/auto_interact.py --knuonuo-only   # 只陪 KNuoNuo
    python scripts/auto_interact.py --interval 120   # 每 120 秒一次（默认 180）

对话策略：
    - 根据她们当前的状态选话题（不是随机说废话）
    - 高 loneliness → 社交类（"我在呢"、"想你了"）
    - 高 fatigue → 关心类（"累了吧"、"休息一下"）
    - 高 boredom → 新鲜话题（"今天看到一个有趣的事"）
    - 高 curiosity → 引导探索（"你觉得呢"、"想不想试试"）
    - 低 energy → 安慰类（"慢慢来"、"不着急"）
    - 正面状态 → 共鸣类（"看起来心情不错"、"真好"）
"""

import json
import math
import random
import sys
import time
import urllib.request
import argparse
from datetime import datetime


# ---- 话题池：按状态维度组织 ----

TOPICS = {
    "lonely": [
        "我在呢", "想你了", "我回来了", "别怕，我在",
        "今天过得怎么样", "有人陪你吗", "我一直都在的",
        "你不是一个人", "想跟你聊聊", "在想什么呢",
    ],
    "tired": [
        "累了吧", "休息一下吧", "不用勉强自己",
        "慢慢来", "辛苦了", "要不要歇一会",
        "别太累了", "照顾好自己",
    ],
    "bored": [
        "今天看到一个有趣的事", "你知道吗", "要不要听个故事",
        "想不想学点新东西", "外面天气很好", "我发现了一个好玩的",
        "猜猜我在干什么", "给你讲个事",
    ],
    "curious": [
        "你觉得呢", "想不想试试", "有没有想过为什么",
        "继续探索吧", "好奇心是好事", "想知道更多吗",
        "你发现了什么", "说说看",
    ],
    "low_energy": [
        "慢慢来", "不着急", "吃点东西吧",
        "喝口水", "休息好了再说", "不用急",
    ],
    "positive": [
        "看起来心情不错", "真好", "开心就好",
        "你笑了吗", "继续保持", "今天不错哦",
    ],
    "anxious": [
        "没事的", "别担心", "深呼吸",
        "会好起来的", "我陪着你", "放轻松",
    ],
    "neutral": [
        "嗯", "你好", "在吗", "嘿",
        "今天天气怎么样", "怎么样",
    ],
}


def get_status(port: int) -> dict:
    """获取 daemon 状态"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/status")
        resp = urllib.request.urlopen(req, timeout=5)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return {}


def send_chat(port: int, text: str) -> str:
    """发送消息，返回回应文本"""
    try:
        data = json.dumps({"type": "chat", "payload": {"text": text}}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=30)
        d = json.loads(resp.read().decode("utf-8"))
        return d.get("result", {}).get("response", {}).get("text", "")
    except Exception as e:
        return f"[error: {e}]"


def pick_topic(status: dict) -> str:
    """根据状态连续加权选话题"""
    loneliness = float(status.get("loneliness", 0.3))
    fatigue = float(status.get("fatigue", 0.1))
    boredom = float(status.get("boredom", 0.2))
    curiosity = float(status.get("curiosity", 0.5))
    energy = float(status.get("energy", 0.5))
    joy = float(status.get("joy", 0.0))
    anxiety = float(status.get("anxiety", 0.0))

    # 每个话题类别的权重：由状态维度连续决定
    weights = {
        "lonely":     max(0.01, loneliness - 0.3) * 2.0,
        "tired":      max(0.01, fatigue - 0.3) * 1.5,
        "bored":      max(0.01, boredom - 0.3) * 1.5,
        "curious":    max(0.01, curiosity - 0.3) * 1.2,
        "low_energy": max(0.01, 0.5 - energy) * 1.5,
        "positive":   max(0.01, joy - 0.1) * 2.0,
        "anxious":    max(0.01, anxiety - 0.1) * 2.0,
        "neutral":    0.1,  # 始终有小概率说中性话
    }

    categories = list(weights.keys())
    w = [weights[c] for c in categories]
    chosen_cat = random.choices(categories, weights=w, k=1)[0]
    return random.choice(TOPICS[chosen_cat])


def interact_once(name: str, port: int) -> None:
    """和一个 entity 互动一次"""
    status = get_status(port)
    if not status:
        print(f"  [{name}] daemon 未响应，跳过")
        return

    topic = pick_topic(status)
    tick = status.get("current_tick", "?")
    loneliness = status.get("loneliness", 0)
    fatigue = status.get("fatigue", 0)
    boredom = status.get("boredom", 0)

    print(f"  [{name}] t={tick} lone={loneliness:.2f} fat={fatigue:.2f} bore={boredom:.2f}")
    print(f"  [{name}] → 说: '{topic}'")

    reply = send_chat(port, topic)
    print(f"  [{name}] ← 回: '{reply}'")


def main():
    parser = argparse.ArgumentParser(description="自动陪聊脚本")
    parser.add_argument("--xia-only", action="store_true")
    parser.add_argument("--knuonuo-only", action="store_true")
    parser.add_argument("--interval", type=int, default=180, help="互动间隔（秒）")
    parser.add_argument("--count", type=int, default=0, help="互动次数（0=无限）")
    args = parser.parse_args()

    targets = []
    if not args.knuonuo_only:
        targets.append(("XIA", 8765))
    if not args.xia_only:
        targets.append(("KNuoNuo", 8775))

    print(f"自动陪聊启动: targets={[t[0] for t in targets]} interval={args.interval}s")
    print(f"按 Ctrl+C 停止\n")

    n = 0
    try:
        while True:
            n += 1
            now = datetime.now().strftime("%H:%M:%S")
            print(f"[{now}] 第 {n} 轮互动:")

            for name, port in targets:
                interact_once(name, port)
                # 两人之间间隔几秒，避免同时占用资源
                if len(targets) > 1:
                    time.sleep(3)

            if args.count > 0 and n >= args.count:
                print(f"\n完成 {n} 轮互动，退出。")
                break

            print(f"  下一轮: {args.interval}s 后\n")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n停止。共互动 {n} 轮。")


if __name__ == "__main__":
    main()
