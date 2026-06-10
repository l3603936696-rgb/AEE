"""临时：向 daemon 发若干 chat（no_llm），抓回复+驱动力。无持久副作用。"""
import json, sys, io, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
URL = f"http://127.0.0.1:{PORT}"

MSGS = [
    "你刚才说想去看看，是被什么吸引了？",
    "那个让你好奇的东西，现在还在你心里转吗？",
    "如果我告诉你那是风吹过树叶的声音，你的疑问算解开了吗？",
    "你累的时候，安静下来是不是会舒服一点？",
    "我在这儿陪着你，你不是一个人。",
    "你今天学到的那个词，自己念出来是什么感觉？",
]

def ask(text):
    data = json.dumps({"type": "chat", "payload": {"text": text, "no_llm": True}}).encode()
    req = urllib.request.Request(URL, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=60)
    r = json.loads(resp.read().decode("utf-8", errors="replace"))
    res = r.get("result", r)
    reply = res.get("response", {}).get("text", "?")
    ss = res.get("state_snapshot", {})
    return reply, ss, res.get("tick")

for i, m in enumerate(MSGS, 1):
    try:
        reply, ss, tick = ask(m)
        print(f"[{i}] tick={tick}")
        print(f"  我 : {m}")
        print(f"  她 : {reply}")
        print(f"  info_gap={ss.get('info_gap')} unresolved={ss.get('unresolved')} "
              f"loneliness={ss.get('loneliness')} energy={ss.get('energy')}")
    except Exception as e:
        print(f"[{i}] ERROR: {e!r}")
    time.sleep(3)
