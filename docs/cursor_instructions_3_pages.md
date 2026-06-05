# Cursor 指令 3：新页面 + 现有页面升级

## 前置条件
指令 1（后端）和指令 2（i18n + 导航）已完成。

## 目标
实现训练页、日志页，升级状态页。

---

## 3A. 日志页

**新建文件**：`E:/XIA/frontend/src/components/Logs/Logs.jsx`

布局（单栏）：

### 顶栏
- 文件选择 dropdown（默认 `daemon_live.log`），可选项：
  ```
  daemon_live.log
  daemon_error.log
  counterfactual_probe.jsonl
  shell_audit.jsonl
  browser_audit.jsonl
  ```
- 行数选择（50 / 200 / 500），默认 200
- 刷新按钮
- 自动刷新开关（默认关，开启后 30 秒刷新一次）
- 搜索输入框（实时过滤关键字）

### 内容区
- 调用 `window.xia.getLogs(filename, limit)` 获取数据
- `.jsonl` 文件：每行尝试 JSON.parse → 格式化展示关键字段（timestamp、type/event、摘要）
- `.log` 文件：纯文本，等宽字体，显示行号
- 颜色：包含 `ERROR` → 红色行，包含 `WARN` → 黄色行
- 底部显示 "共 {total_lines} 行，显示最近 {limit} 行"
- 加载时显示 loading 状态

### 样式
沿用现有深色主题（参考 `global.css`），等宽字体用 `monospace`。

---

## 3B. 训练页（词汇+模板监控）

**新建文件**：`E:/XIA/frontend/src/components/Training/Training.jsx`

布局（两栏）：

### 左栏：词汇库
- 调用 `window.xia.getVocab()` 获取数据
- 显示：
  - 已解锁词数量（大数字）
  - 已解锁词列表：每个词 + 平均消力效率的迷你横条（内联 bar，宽度按比例）
  - 按效率排序，高效率在上
- 底部刷新按钮

### 右栏：模板学习状态
- 从 `/vocab` 获取的 `learned_template_count` 和 `runtime_templates`
- 显示：
  - "已学习权重的模板：{N} 个"
  - "进化出的新模板：{N} 个"
  - 每个进化模板显示：模板字符串 + 出生 tick
- 如果无进化模板，显示空状态："暂无进化模板（需要更多学习数据）"

### 样式
卡片式布局，左右各占 50%，移动端竖排。

---

## 3C. 状态页升级

**文件**：`E:/XIA/frontend/src/components/Status/Status.jsx`

在现有基础维度卡（energy、fatigue、loneliness、boredom、stress）下方新增：

### 新增区块 1：信息缺口
- 单个指标卡：`info_gap`，与现有卡片样式一致

### 新增区块 2：情绪维度（10 个）
标题用 `t('status_emotions')`

2 列网格，每个格子：emoji + 中英标签 + 进度条 + 数值

| key | emoji | zh | en |
|-----|-------|----|----|
| joy | 😊 | 喜悦 | Joy |
| excitement | ✨ | 兴奋 | Excitement |
| serenity | 😌 | 宁静 | Serenity |
| sadness | 😔 | 悲伤 | Sadness |
| anger | 😤 | 愤怒 | Anger |
| fear | 😨 | 恐惧 | Fear |
| disgust | 😒 | 厌恶 | Disgust |
| anxiety | 😰 | 焦虑 | Anxiety |
| surprise | 😲 | 惊讶 | Surprise |
| curiosity | 🔍 | 好奇 | Curiosity |

标签用 `t('emotion_joy')` 等。

进度条颜色：正面情绪（joy/excitement/serenity/curiosity）用蓝/绿色调，负面情绪用红/橙色调。

### 新增区块 3：孤独子维度
标题："孤独子维度" / "Loneliness Subdimensions"

两个并排进度条：
- `loneliness_core` — 核心孤独 / Core
- `loneliness_surface` — 表面孤独 / Surface

### 新增区块 4：厌倦子维度
同上布局：
- `boredom_despair` — 绝望性 / Despair
- `boredom_futility` — 徒劳性 / Futility

### 新增区块 5：驱动力
标题用 `t('status_drives')`

并排显示：
- `approach_drive` — 趋近 / Approach
- `avoid_drive` — 回避 / Avoid
- `unresolved` — 未解决张力 / Unresolved

### 新增区块 6：词汇摘要（小条）
在底部加一行：
```
已解锁词汇：{unlocked_vocab_count} 个 | 已学习模板：{template_learned_count} 个 | 进化模板：{runtime_template_count} 个
```

所有数值从 `/status` API 现有轮询中读取（不需要额外请求）。

---

## 3D. Chat.jsx 小增强

**文件**：`E:/XIA/frontend/src/components/Chat/Chat.jsx`

1. placeholder 改为 `t('chat_placeholder')`
2. 发送按钮文字改为 `t('chat_send')`
3. 每条消息右下角加时间戳（`HH:mm` 格式，灰色小字）

---

## 样式提示

所有新增 CSS 写在对应组件的 CSS 文件或 `global.css` 中。风格保持一致：
- 深色背景（现有主题）
- 圆角卡片
- 进度条用 CSS `linear-gradient` 或 `width: XX%`
- 不引入任何 UI 组件库（保持现有纯 CSS 风格）

## 验证

1. 日志页：选 `daemon_live.log`，确认显示最近日志，搜索过滤正常
2. 训练页：确认显示词汇列表和效率条
3. 状态页：确认 10 个情绪维度、子维度、驱动力全部显示
4. 切换语言：所有新增标签正确切换
