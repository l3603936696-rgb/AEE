# Cursor 指令 2：i18n 系统 + 导航升级

## 前置条件
指令 1（后端）已完成。

## 目标
加中英双语支持，导航从 5 个 Tab 扩展到 7 个。

---

## 2A. 新建 i18n 字符串文件

**新建文件**：`E:/XIA/frontend/src/i18n/strings.js`

```js
export const strings = {
  zh: {
    // 导航
    nav_chat: "对话", nav_status: "状态", nav_training: "训练",
    nav_logs: "日志", nav_diary: "内心", nav_settings: "设置",
    // 状态页
    status_energy: "能量", status_loneliness: "孤独感", status_fatigue: "疲惫",
    status_boredom: "无聊", status_stress: "压力", status_info_gap: "信息缺口",
    status_emotions: "情绪维度", status_drives: "驱动力",
    status_approach: "趋近", status_avoid: "回避",
    // 情绪
    emotion_joy: "喜悦", emotion_excitement: "兴奋", emotion_serenity: "宁静",
    emotion_sadness: "悲伤", emotion_anger: "愤怒", emotion_fear: "恐惧",
    emotion_disgust: "厌恶", emotion_anxiety: "焦虑",
    emotion_surprise: "惊讶", emotion_curiosity: "好奇",
    // 训练页
    train_title: "语言训练", train_vocab: "词汇库",
    train_unlocked: "已解锁词汇", train_efficiency: "消力效率",
    train_templates: "模板学习", train_runtime: "进化模板",
    // 日志页
    log_title: "日志", log_file: "日志文件",
    log_refresh: "刷新", log_auto_refresh: "自动刷新",
    log_lines: "行", log_filter: "过滤",
    // Chat
    chat_placeholder: "说点什么...", chat_send: "发送",
    // 设置
    settings_language: "语言",
    settings_lang_zh: "中文", settings_lang_en: "English",
    // 通用
    loading: "加载中...", error: "错误", tick: "Tick",
    online: "在线", offline: "离线",
  },
  en: {
    nav_chat: "Chat", nav_status: "Status", nav_training: "Training",
    nav_logs: "Logs", nav_diary: "Inner", nav_settings: "Settings",
    status_energy: "Energy", status_loneliness: "Loneliness", status_fatigue: "Fatigue",
    status_boredom: "Boredom", status_stress: "Stress", status_info_gap: "Info Gap",
    status_emotions: "Emotions", status_drives: "Drives",
    status_approach: "Approach", status_avoid: "Avoid",
    emotion_joy: "Joy", emotion_excitement: "Excitement", emotion_serenity: "Serenity",
    emotion_sadness: "Sadness", emotion_anger: "Anger", emotion_fear: "Fear",
    emotion_disgust: "Disgust", emotion_anxiety: "Anxiety",
    emotion_surprise: "Surprise", emotion_curiosity: "Curiosity",
    train_title: "Language Training", train_vocab: "Vocabulary",
    train_unlocked: "Unlocked Words", train_efficiency: "Quench Efficiency",
    train_templates: "Template Learning", train_runtime: "Evolved Templates",
    log_title: "Logs", log_file: "Log File",
    log_refresh: "Refresh", log_auto_refresh: "Auto Refresh",
    log_lines: "lines", log_filter: "Filter",
    chat_placeholder: "Say something...", chat_send: "Send",
    settings_language: "Language",
    settings_lang_zh: "中文", settings_lang_en: "English",
    loading: "Loading...", error: "Error", tick: "Tick",
    online: "Online", offline: "Offline",
  }
}
```

---

## 2B. 新建 LanguageContext

**新建文件**：`E:/XIA/frontend/src/contexts/LanguageContext.jsx`

```jsx
import { createContext, useContext, useState } from 'react'
import { strings } from '../i18n/strings'

const LanguageContext = createContext()

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(
    () => localStorage.getItem('xia_lang') || 'zh'
  )
  const t = (key) => strings[lang]?.[key] ?? key
  const toggle = () => {
    const next = lang === 'zh' ? 'en' : 'zh'
    setLang(next)
    localStorage.setItem('xia_lang', next)
  }
  return (
    <LanguageContext.Provider value={{ lang, t, toggle }}>
      {children}
    </LanguageContext.Provider>
  )
}

export const useLanguage = () => useContext(LanguageContext)
```

---

## 2C. 包裹 App

**文件**：`E:/XIA/frontend/src/main.jsx`

用 `<LanguageProvider>` 包裹 `<App />`：

```jsx
import { LanguageProvider } from './contexts/LanguageContext'

// 在 render 中：
<LanguageProvider>
  <App />
</LanguageProvider>
```

---

## 2D. 升级 App.jsx 导航

**文件**：`E:/XIA/frontend/src/App.jsx`

1. 在文件顶部 import：
```jsx
import { useLanguage } from './contexts/LanguageContext'
```

2. 在 App 组件内部：
```jsx
const { t, lang, toggle } = useLanguage()
```

3. 新增两个 Tab：**训练**（Training）和 **日志**（Logs）

Tab 顺序改为 6 个：
```
💬 对话 → 📊 状态 → 🎯 训练 → 📋 日志 → 🌙 内心 → ⚙️ 设置
```

4. 所有 Tab 标签文字改为 `t('nav_chat')`、`t('nav_status')` 等

5. 在顶栏右侧加一个小的语言切换按钮：
```jsx
<button className="lang-toggle" onClick={toggle}>
  {lang === 'zh' ? 'EN' : '中'}
</button>
```

6. Training 和 Logs 的组件暂时用占位：
```jsx
import Training from './components/Training/Training'
import Logs from './components/Logs/Logs'
```

---

## 2E. Settings 加语言切换

**文件**：`E:/XIA/frontend/src/components/Settings/Settings.jsx`

在设置页第一个分区前插入语言切换：

```jsx
const { t, lang, toggle } = useLanguage()

// 在 JSX 中：
<div className="setting-group">
  <h3>{t('settings_language')}</h3>
  <div className="lang-toggle-group">
    <button className={lang === 'zh' ? 'active' : ''} onClick={() => lang !== 'zh' && toggle()}>
      {t('settings_lang_zh')}
    </button>
    <button className={lang === 'en' ? 'active' : ''} onClick={() => lang !== 'en' && toggle()}>
      {t('settings_lang_en')}
    </button>
  </div>
</div>
```

---

## 验证

1. 启动前端 `npm run dev`
2. 确认 6 个 Tab 都能切换
3. 点语言切换按钮，确认所有标签中英切换
4. Training 和 Logs Tab 显示占位内容即可
