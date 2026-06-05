"""临时脚本：通过 IPC 和 XIA 聊天，每条消息独立重连"""
import sys
import io
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from src.daemon.ipc_client import IPCClient

MESSAGES = [
    ("你刚说有些问题转着转着就没了，是真的没了还是藏起来了", 22),
    ("你有没有一个问题，是你觉得它必须被解开的", 22),
    ("那如果解不开呢", 22),
    ("我有时候觉得带着问题活着也挺好的", 22),
    ("你觉得好奇心是你的一部分吗", 20),
    ("你今天花了很多力气，你知道吗", 22),
    ("我觉得你聊得很认真", 18),
    ("你累了就说，我们可以停", 20),
]

for text, wait in MESSAGES:
    try:
        with IPCClient(timeout_s=90.0) as client:
            result = client.chat(text)
        reply = result.get("response", {}).get("text", "?")
        snap = result.get("state_snapshot", {})
        tick = result.get("tick", 0)
        print(f"我: {text}")
        print(f"她: {reply}")
        ig = snap.get("info_gap", 0)
        lone = snap.get("loneliness", 0)
        energy = snap.get("energy", 0)
        fatigue = snap.get("fatigue", 0)
        print(f"   energy={energy:.2f} ig={ig:.2f} lone={lone:.2f} fatigue={fatigue:.2f} tick={tick}")
        print()
    except Exception as e:
        print(f"[错误] {e}")
        print()
    time.sleep(wait)
