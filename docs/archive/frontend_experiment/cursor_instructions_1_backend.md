# Cursor 指令 1：后端 API 扩展

## 目标
给前端提供更丰富的数据端点。改 3 个文件，不动核心逻辑。

---

## 1A. 扩展 get_status() 返回字段

**文件**：`E:/XIA/src/daemon/tick_engine.py`，找到 `get_status()` 方法

在现有 return dict 末尾追加以下字段（全部 round 到 3 位小数）：

```python
# 情绪维度（10个）
"joy":        round(getattr(self.entity, "joy",        0.0), 3),
"excitement": round(getattr(self.entity, "excitement", 0.0), 3),
"serenity":   round(getattr(self.entity, "serenity",   0.0), 3),
"sadness":    round(getattr(self.entity, "sadness",    0.0), 3),
"anger":      round(getattr(self.entity, "anger",      0.0), 3),
"fear":       round(getattr(self.entity, "fear",       0.0), 3),
"disgust":    round(getattr(self.entity, "disgust",    0.0), 3),
"anxiety":    round(getattr(self.entity, "anxiety",    0.0), 3),
"surprise":   round(getattr(self.entity, "surprise",   0.0), 3),
"curiosity":  round(getattr(self.entity, "curiosity",  0.5), 3),
# 驱动力扩展
"approach_drive": round(getattr(self.entity, "approach_drive", 0.0), 3),
"avoid_drive":    round(getattr(self.entity, "avoid_drive",    0.0), 3),
"unresolved":     round(getattr(self.entity, "unresolved",     0.2), 3),
"info_gap":       round(getattr(self.entity, "info_gap",       0.5), 3),
"pain":           round(getattr(self.entity, "pain",           0.0), 3),
# 孤独子维度
"loneliness_core":    round(getattr(self.entity, "loneliness_core",    0.0), 3),
"loneliness_surface": round(getattr(self.entity, "loneliness_surface", 0.0), 3),
# 厌倦子维度
"boredom_despair":    round(getattr(self.entity, "boredom_despair",    0.0), 3),
"boredom_futility":   round(getattr(self.entity, "boredom_futility",   0.0), 3),
# 语言系统摘要
"unlocked_vocab_count": len(getattr(self.entity, "_unlocked_vocabulary", [])),
# 模板学习摘要
"template_learned_count": len(getattr(self.entity, "_template_learned_weights", {})),
"runtime_template_count": len(getattr(self.entity, "_runtime_templates", [])),
```

**不要动** get_status() 里已有的字段，只在末尾追加。

---

## 1B. 新增 GET /logs 端点

**文件**：`E:/XIA/src/daemon/daemon.py`，找到 `HTTPServer` 的 `Handler.do_GET()` 方法

在 `/diary` 分支后加一个新 elif 分支：

```python
elif self.path.startswith('/logs'):
    import json
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(self.path)
    params = parse_qs(parsed.query)
    filename = params.get('file', ['daemon_live.log'])[0]
    limit = int(params.get('limit', ['200'])[0])

    # 安全检查：只允许读 logs/ 目录下的文件
    logs_dir = Path(__file__).parent.parent.parent / "logs"
    target = (logs_dir / filename).resolve()
    if not str(target).startswith(str(logs_dir.resolve())):
        self.send_response(403)
        self.end_headers()
        return

    try:
        if target.exists():
            lines = target.read_text(encoding='utf-8', errors='replace').splitlines()
            recent = lines[-limit:]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                "file": filename,
                "total_lines": len(lines),
                "lines": recent,
            }, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "file not found"}).encode('utf-8'))
    except Exception as e:
        self.send_response(500)
        self.end_headers()
        self.wfile.write(str(e).encode('utf-8'))
```

---

## 1C. 新增 GET /vocab 端点

**文件**：同上，继续在 do_GET 添加新 elif 分支：

```python
elif self.path == '/vocab':
    import json
    entity = self._get_entity()  # 用 daemon 已有的获取 entity 的方法
    unlocked = list(getattr(entity, "_unlocked_vocabulary", []))
    # 模板学习状态
    tl_data = getattr(entity, "_template_learner_data", {})
    learned_count = len(tl_data.get("learned_weights", {}))
    runtime_templates = [
        {"template": t.get("template", ""), "born_tick": t.get("born_tick", -1)}
        for t in tl_data.get("runtime_templates", [])
    ]
    # 消力效率 top 词
    qd = getattr(entity, "_quenching_data", {})
    records = qd.get("records", []) if isinstance(qd, dict) else []
    word_stats = {}
    for r in records[-200:]:
        w = r.get("expression", "")
        e = r.get("quenching_efficiency", 0.0)
        if w:
            if w not in word_stats:
                word_stats[w] = []
            word_stats[w].append(e)
    word_efficiency = {
        w: round(sum(v)/len(v), 3)
        for w, v in word_stats.items() if v
    }
    self.send_response(200)
    self.send_header('Content-Type', 'application/json')
    self.send_header('Access-Control-Allow-Origin', '*')
    self.end_headers()
    self.wfile.write(json.dumps({
        "unlocked": unlocked,
        "word_efficiency": word_efficiency,
        "learned_template_count": learned_count,
        "runtime_templates": runtime_templates,
    }, ensure_ascii=False).encode('utf-8'))
```

**注意**：`self._get_entity()` 需要你找到 daemon.py 中获取 entity 的实际方法名——可能是通过 `self.server` 或 `self._ipc_server._tick_engine.entity`。看 `/status` 端点怎么拿 entity 的，用一样的方式。

---

## 1D. IPC 桥接层

**文件**：`E:/XIA/frontend/electron/xia-bridge.js`

新增两个方法：

```js
async getLogs(filename = 'daemon_live.log', limit = 200) {
    return this._getRequest(`/logs?file=${encodeURIComponent(filename)}&limit=${limit}`)
}

async getVocab() {
    return this._getRequest('/vocab')
}
```

**文件**：`E:/XIA/frontend/electron/preload.js`

在 contextBridge.exposeInMainWorld 中新增：

```js
getLogs: (filename, limit) => ipcRenderer.invoke('xia:getLogs', filename, limit),
getVocab: () => ipcRenderer.invoke('xia:getVocab'),
```

**文件**：`E:/XIA/frontend/electron/main.js`

注册对应 ipcMain handler：

```js
ipcMain.handle('xia:getLogs', async (_event, filename, limit) => {
    return bridge.getLogs(filename, limit)
})

ipcMain.handle('xia:getVocab', async () => {
    return bridge.getVocab()
})
```

---

## 验证

改完后重启 daemon，用 curl 验证：
```bash
curl http://127.0.0.1:8765/status    # 确认新情绪字段出现
curl "http://127.0.0.1:8765/logs?file=daemon_live.log&limit=5"  # 确认返回 JSON
curl http://127.0.0.1:8765/vocab     # 确认返回词汇数据
```
