# XIA Frontend

XIA 认知引擎的 Electron 桌面展示层。

## 功能

- **对话**：与 XIA 自然对话
- **状态**：实时查看 XIA 的能量、孤独感、疲惫感等状态
- **日志**：查看 XIA 的主动行动记录
- **设置**：配置连接和调试工具

## 快速开始

### 1. 启动 Daemon

在 WSL2 终端中运行：

```bash
cd ~/XIA
./run_daemon.sh --start
```

这会启动 XIA daemon，包含：
- Unix Domain Socket (`data/xia_daemon.sock`) - 供本地 channel 使用
- HTTP API (`http://127.0.0.1:8765`) - 供 Windows 前端使用

### 2. 启动前端

在 Windows 上运行：

```bash
cd e:\XIA\frontend
npm run electron:preview
```

或者开发模式：

```bash
npm run electron:dev
```

## 项目结构

```
frontend/
├── electron/
│   ├── main.js         # Electron 主进程
│   ├── preload.js      # IPC 桥接
│   └── xia-bridge.js  # XIA HTTP API 客户端
├── src/
│   ├── components/
│   │   ├── StatusBar/  # 顶部状态栏
│   │   ├── Chat/       # 对话界面
│   │   ├── Status/     # 状态仪表盘
│   │   ├── Actions/    # 行动日志
│   │   └── Settings/   # 设置页
│   └── App.jsx         # 主应用
└── styles/
    └── global.css      # Claude 风格配色
```

## 技术栈

- **Electron 28** - 桌面应用框架
- **React 18** - UI 框架
- **Vite 5** - 构建工具

## 设计原则

- 色彩风格参照 Claude（深色主题）
- 每个 Tab 独立目录，便于迭代
- xia-bridge.js 独立封装，方便后续改为其他通信方式
