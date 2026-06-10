"""
XIA Long-Term Memory Service — 长期记忆服务

常驻进程，负责：
- 维护 XIA 的跨对话状态（EntityState + episodes.db）
- 后台 Tick Engine：对话窗口关闭时持续推进状态
- IPC Server：接收来自 channel/chat.py 的对话请求
- LLM 后端：DeepSeek API

架构：
    xia daemon (进程)
        ├── DeepSeek API（外部服务）
        ├── Tick Engine（每 60s 触发一次无 LLM 的后台 tick）
        ├── EntityState（内存 + 磁盘持久化）
        └── IPC Server（Unix Domain Socket: data/xia_daemon.sock）

    channel/chat.py（轻量客户端）
        └── 连接 daemon.sock 发送请求、接收回复

启动：
    python3 -m src.daemon.daemon      # 启动 daemon
    python3 -m channel                # 对话（连接 daemon）
    python3 -m channel --standalone   # 独立模式（不连接 daemon）
"""
