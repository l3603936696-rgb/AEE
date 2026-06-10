"""端到端验证编排：戳哨兵文件，记录 pain/somatic 的完整跳变+衰减曲线。
二进制读写 executor.py，确保无损还原、不碰编码。"""
import json, time

CORE = "data/entity_core.json"
SENT = "src/action_system/executor.py"
MARK = b"\n# integrity-probe-2026-05-30 (auto, removed on restore)\n"


def read():
    try:
        d = json.load(open(CORE, encoding="utf-8"))
        return d.get("tick"), d.get("pain"), d.get("somatic_tone")
    except Exception:
        return None, None, None


orig = open(SENT, "rb").read()
base = None
while base is None:
    base, _, _ = read()
    time.sleep(1)

poke_at, restore_at, end_at = base + 3, base + 18, base + 24
poked = restored = False
last = None
print("base tick=%d  poke@%d  restore@%d  end@%d" % (base, poke_at, restore_at, end_at), flush=True)

while True:
    tk, pain, som = read()
    if tk is not None and tk != last:
        tag = ""
        if tk >= poke_at and not poked:
            open(SENT, "ab").write(MARK)
            tag = "  <<< POKE: edited executor.py"
            poked = True
        if tk >= restore_at and not restored:
            open(SENT, "wb").write(orig)
            tag = "  <<< RESTORE: executor.py back to original"
            restored = True
        p = pain if pain is not None else -1
        s = som if som is not None else -1
        print("tick=%d pain=%.4f somatic=%.4f%s" % (tk, p, s, tag), flush=True)
        last = tk
        if tk >= end_at:
            break
    time.sleep(1)

open(SENT, "wb").write(orig)  # 保险：无论如何还原
print("DONE — executor.py restored, bytes_match=%s" % (open(SENT, "rb").read() == orig), flush=True)
