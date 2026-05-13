import { useMemo, useRef, useEffect } from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import { LineChart, Line, ResponsiveContainer, Tooltip, XAxis } from 'recharts';
import './Status.css';

const CORE_CONFIG = [
  { key: 'energy',     color: 'var(--energy-color)',     icon: '⚡' },
  { key: 'loneliness', color: 'var(--loneliness-color)', icon: '👤' },
  { key: 'fatigue',    color: 'var(--fatigue-color)',    icon: '😴' },
  { key: 'boredom',    color: 'var(--boredom-color)',    icon: '😐' },
  { key: 'stress',     color: 'var(--stress-color)',     icon: '⚠️' },
  { key: 'info_gap',   color: 'var(--info-gap-color)',    icon: '❓' },
  { key: 'unresolved', color: '#a855f7',                  icon: '🔗' },
];

const EMOTION_CONFIG = [
  { key: 'joy',        emoji: '😊', zh: '喜悦',   en: 'Joy',        color: '#22c55e' },
  { key: 'excitement', emoji: '✨', zh: '兴奋',   en: 'Excitement', color: '#f59e0b' },
  { key: 'serenity',   emoji: '😌', zh: '宁静',   en: 'Serenity',   color: '#06b6d4' },
  { key: 'sadness',    emoji: '😔', zh: '悲伤',   en: 'Sadness',    color: '#6366f1' },
  { key: 'anger',      emoji: '😤', zh: '愤怒',   en: 'Anger',      color: '#ef4444' },
  { key: 'fear',       emoji: '😨', zh: '恐惧',   en: 'Fear',       color: '#8b5cf6' },
  { key: 'disgust',    emoji: '😒', zh: '厌恶',   en: 'Disgust',    color: '#84cc16' },
  { key: 'anxiety',    emoji: '😰', zh: '焦虑',   en: 'Anxiety',    color: '#f97316' },
  { key: 'surprise',   emoji: '😲', zh: '惊讶',   en: 'Surprise',   color: '#ec4899' },
  { key: 'curiosity',   emoji: '🔍', zh: '好奇',   en: 'Curiosity',  color: '#3b82f6' },
];

const SUBLONELINESS = [
  { key: 'loneliness_core',    emoji: '💔', zh: '核心孤独', en: 'Core Loneliness', color: 'var(--loneliness-color)' },
  { key: 'loneliness_surface', emoji: '🥀', zh: '表面孤独', en: 'Surface Loneliness', color: '#fb923c' },
];

const SUBBOREDOM = [
  { key: 'boredom_despair',  emoji: '🌫️', zh: '绝望性厌倦', en: 'Despair', color: '#eab308' },
  { key: 'boredom_futility',  emoji: '⏳', zh: '徒劳性厌倦', en: 'Futility', color: '#a3a3a3' },
];

// Mini emotion trend chart colors (subset for the line chart)
const TREND_KEYS = ['energy', 'loneliness', 'fatigue', 'somatic_tone'];
const TREND_COLORS = {
  energy: '#22c55e',
  loneliness: '#f97316',
  fatigue: '#6366f1',
  somatic_tone: '#d4a574',
};

function Status({ xiaState }) {
  const { t, lang } = useLanguage();
  const historyRef = useRef([]);

  // 追踪历史（最多24个点）
  useEffect(() => {
    if (!xiaState || xiaState.error) return;
    const point = {
      tick: xiaState.current_tick ?? xiaState.tick ?? 0,
      energy: xiaState.energy ?? 0,
      loneliness: xiaState.loneliness ?? 0,
      fatigue: xiaState.fatigue ?? 0,
      somatic_tone: xiaState.somatic_tone ?? 0,
    };
    historyRef.current = [...historyRef.current.slice(-23), point];
  }, [xiaState]);

  const state = useMemo(() => {
    if (!xiaState) {
      return {
        energy: 0, loneliness: 0, fatigue: 0, boredom: 0, stress: 0,
        info_gap: 0, unresolved: 0, somatic_tone: 0,
        approach_drive: 0, avoid_drive: 0,
        joy: 0, excitement: 0, serenity: 0, sadness: 0, anger: 0,
        fear: 0, disgust: 0, anxiety: 0, surprise: 0, curiosity: 0.5,
        loneliness_core: 0, loneliness_surface: 0,
        boredom_despair: 0, boredom_futility: 0,
        unlocked_vocab_count: 0,
        tick: 0, uptime: '—', last_interaction: '—',
        current_action: null, fragmentation_tone: '',
      };
    }

    let uptime = '—';
    if (xiaState.uptime_s) {
      const hours = Math.floor(xiaState.uptime_s / 3600);
      const mins = Math.floor((xiaState.uptime_s % 3600) / 60);
      if (hours > 24) {
        const days = Math.floor(hours / 24);
        uptime = `${days}d ${hours % 24}h`;
      } else {
        uptime = `${hours}h ${mins}m`;
      }
    }

    let lastInteraction = '—';
    if (xiaState.last_interaction && xiaState.last_interaction !== 'never') {
      try {
        const date = new Date(xiaState.last_interaction);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) lastInteraction = lang === 'zh' ? '刚刚' : 'Just now';
        else if (diffMins < 60) lastInteraction = `${diffMins}m ago`;
        else lastInteraction = `${Math.floor(diffMins / 60)}h ago`;
      } catch {
        lastInteraction = xiaState.last_interaction;
      }
    }

    const decision = xiaState.decision || {};

    return {
      energy:            xiaState.energy            ?? 0,
      loneliness:        xiaState.loneliness        ?? 0,
      fatigue:           xiaState.fatigue           ?? 0,
      boredom:          xiaState.boredom          ?? 0,
      stress:           xiaState.stress           ?? 0,
      info_gap:         xiaState.info_gap         ?? 0,
      unresolved:       xiaState.unresolved       ?? 0.2,
      somatic_tone:     xiaState.somatic_tone     ?? 0,
      approach_drive:   xiaState.approach_drive   ?? 0,
      avoid_drive:      xiaState.avoid_drive      ?? 0,
      joy:              xiaState.joy              ?? 0,
      excitement:        xiaState.excitement        ?? 0,
      serenity:          xiaState.serenity          ?? 0,
      sadness:           xiaState.sadness           ?? 0,
      anger:             xiaState.anger             ?? 0,
      fear:              xiaState.fear              ?? 0,
      disgust:           xiaState.disgust           ?? 0,
      anxiety:           xiaState.anxiety           ?? 0,
      surprise:          xiaState.surprise          ?? 0,
      curiosity:          xiaState.curiosity          ?? 0.5,
      loneliness_core:    xiaState.loneliness_core    ?? 0,
      loneliness_surface: xiaState.loneliness_surface ?? 0,
      boredom_despair:   xiaState.boredom_despair   ?? 0,
      boredom_futility:  xiaState.boredom_futility  ?? 0,
      unlocked_vocab_count: xiaState.unlocked_vocab_count ?? 0,
      tick:              xiaState.current_tick ?? xiaState.tick ?? 0,
      uptime,
      last_interaction: lastInteraction,
      current_action: decision.action_type || 'idle',
      fragmentation_tone: decision.fragmentation_tone || '',
    };
  }, [xiaState, lang]);

  const driveGap = state.approach_drive - state.avoid_drive;

  const getToneDescription = (tone) => {
    if (tone > 0.5) return lang === 'zh' ? '非常愉悦' : 'Very Pleasant';
    if (tone > 0.2) return lang === 'zh' ? '愉悦' : 'Pleasant';
    if (tone > 0)   return lang === 'zh' ? '平静偏正' : 'Calm/Positive';
    if (tone === 0) return lang === 'zh' ? '中性' : 'Neutral';
    if (tone > -0.2) return lang === 'zh' ? '平静偏负' : 'Calm/Negative';
    if (tone > -0.5) return lang === 'zh' ? '低落' : 'Low';
    return lang === 'zh' ? '非常低落' : 'Very Low';
  };

  const getDriveGapText = (gap) => {
    if (gap > 0.1) return lang === 'zh' ? '趋近占优' : 'Approach-Dominant';
    if (gap < -0.1) return lang === 'zh' ? '回避占优' : 'Avoid-Dominant';
    return lang === 'zh' ? '势均力敌' : 'Balanced';
  };

  const getEmotionLabel = (cfg) => lang === 'zh' ? cfg.zh : cfg.en;

  const StatusBar = ({ value, color }) => (
    <div className="status-bar">
      <div
        className="status-bar-fill"
        style={{ width: `${Math.max(0, Math.min(100, value * 100))}%`, backgroundColor: color }}
      />
    </div>
  );

  if (!xiaState || xiaState.error) {
    return (
      <div className="status-empty">
        <div className="status-empty-icon">📊</div>
        <p>{xiaState?.error ? xiaState.message : t('loading')}</p>
      </div>
    );
  }

  return (
    <div className="status">
      {/* 核心状态 */}
      <section className="status-section">
        <h2 className="section-title">{lang === 'zh' ? '核心状态' : 'Core State'}</h2>
        <div className="status-grid">
          {CORE_CONFIG.map((item) => (
            <div key={item.key} className="status-item">
              <div className="status-item-header">
                <span className="status-icon">{item.icon}</span>
                <span className="status-name">{t(`status_${item.key}`) || item.key}</span>
                <span className="status-value" style={{ color: item.color }}>
                  {(state[item.key] ?? 0).toFixed(3)}
                </span>
              </div>
              <StatusBar value={state[item.key]} color={item.color} />
            </div>
          ))}
        </div>
      </section>

      {/* 情绪维度 */}
      <section className="status-section">
        <h2 className="section-title">{t('status_emotions')}</h2>
        <div className="emotion-section-layout">
          <div className="emotion-grid">
            {EMOTION_CONFIG.map((cfg) => (
              <div key={cfg.key} className="emotion-item">
                <span className="emotion-emoji">{cfg.emoji}</span>
                <span className="emotion-label">{getEmotionLabel(cfg)}</span>
                <div className="emotion-bar-wrap">
                  <div
                    className="emotion-bar-fill"
                    style={{
                      width: `${Math.max(0, Math.min(100, (state[cfg.key] ?? 0) * 100))}%`,
                      backgroundColor: cfg.color,
                    }}
                  />
                </div>
                <span className="emotion-value">{(state[cfg.key] ?? 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
          {historyRef.current.length > 2 && (
            <div className="emotion-trend">
              <h3 className="trend-title">{lang === 'zh' ? '趋势' : 'Trend'}</h3>
              <ResponsiveContainer width="100%" height={120}>
                <LineChart data={historyRef.current}>
                  <XAxis dataKey="tick" hide />
                  <Tooltip
                    contentStyle={{ background: '#252529', border: '1px solid #3a3a40', borderRadius: 8, fontSize: 11 }}
                    labelStyle={{ display: 'none' }}
                    itemStyle={{ fontSize: 11 }}
                  />
                  {TREND_KEYS.map(key => (
                    <Line
                      key={key}
                      type="monotone"
                      dataKey={key}
                      stroke={TREND_COLORS[key]}
                      strokeWidth={1.5}
                      dot={false}
                      isAnimationActive={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
              <div className="trend-legend">
                {TREND_KEYS.map(key => (
                  <span key={key} className="trend-legend-item">
                    <span className="trend-dot" style={{ background: TREND_COLORS[key] }} />
                    {key}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* 孤独子维度 */}
      <section className="status-section">
        <h2 className="section-title">{lang === 'zh' ? '孤独子维度' : 'Loneliness Sub-Dimensions'}</h2>
        <div className="sub-dim-grid">
          {SUBLONELINESS.map((cfg) => (
            <div key={cfg.key} className="sub-dim-item">
              <div className="sub-dim-header">
                <span className="sub-dim-emoji">{cfg.emoji}</span>
                <span className="sub-dim-label">{lang === 'zh' ? cfg.zh : cfg.en}</span>
                <span className="sub-dim-value" style={{ color: cfg.color }}>
                  {(state[cfg.key] ?? 0).toFixed(3)}
                </span>
              </div>
              <StatusBar value={state[cfg.key]} color={cfg.color} />
            </div>
          ))}
        </div>
      </section>

      {/* 厌倦子维度 */}
      <section className="status-section">
        <h2 className="section-title">{lang === 'zh' ? '厌倦子维度' : 'Boredom Sub-Dimensions'}</h2>
        <div className="sub-dim-grid">
          {SUBBOREDOM.map((cfg) => (
            <div key={cfg.key} className="sub-dim-item">
              <div className="sub-dim-header">
                <span className="sub-dim-emoji">{cfg.emoji}</span>
                <span className="sub-dim-label">{lang === 'zh' ? cfg.zh : cfg.en}</span>
                <span className="sub-dim-value" style={{ color: cfg.color }}>
                  {(state[cfg.key] ?? 0).toFixed(3)}
                </span>
              </div>
              <StatusBar value={state[cfg.key]} color={cfg.color} />
            </div>
          ))}
        </div>
      </section>

      {/* 驱动力场 */}
      <section className="status-section">
        <h2 className="section-title">{t('status_drives')}</h2>
        <div className="drive-container">
          <div className="drive-item">
            <div className="drive-label-row">
              <span className="drive-label">
                <span className="drive-arrow">↑</span> {t('status_approach')}
              </span>
              <span className="drive-value" style={{ color: 'var(--positive-tone)' }}>
                {state.approach_drive.toFixed(3)}
              </span>
            </div>
            <div className="drive-bar-track">
              <div className="drive-bar-fill drive-bar-approach"
                style={{ width: `${state.approach_drive * 100}%` }} />
            </div>
          </div>

          <div className="drive-gap-indicator">
            <span style={{ color: driveGap > 0 ? 'var(--positive-tone)' : 'var(--negative-tone)' }}>
              {driveGap > 0 ? '+' : ''}{driveGap.toFixed(3)}
            </span>
            <span className="drive-gap-text">{getDriveGapText(driveGap)}</span>
          </div>

          <div className="drive-item">
            <div className="drive-label-row">
              <span className="drive-label">
                <span className="drive-arrow">↓</span> {t('status_avoid')}
              </span>
              <span className="drive-value" style={{ color: 'var(--negative-tone)' }}>
                {state.avoid_drive.toFixed(3)}
              </span>
            </div>
            <div className="drive-bar-track">
              <div className="drive-bar-fill drive-bar-avoid"
                style={{ width: `${state.avoid_drive * 100}%` }} />
            </div>
          </div>
        </div>
      </section>

      {/* 当前行为 + 词汇 */}
      <section className="status-section">
        <h2 className="section-title">{lang === 'zh' ? '当前行为' : 'Current Behavior'}</h2>
        <div className="current-behavior">
          <div className="behavior-action">
            <span className="behavior-type">[{state.current_action || 'idle'}]</span>
            {state.fragmentation_tone && (
              <span className="behavior-tone">{state.fragmentation_tone}</span>
            )}
          </div>
          <div className="behavior-tone-description">
            {lang === 'zh' ? '躯体基调' : 'Somatic Tone'}: {getToneDescription(state.somatic_tone)} ({state.somatic_tone.toFixed(3)})
          </div>
          <div className="vocab-summary">
            {t('status_unlocked')}: {state.unlocked_vocab_count} {lang === 'zh' ? '个' : 'words'}
          </div>
        </div>
      </section>

      {/* 运行信息 */}
      <section className="status-section">
        <h2 className="section-title">{lang === 'zh' ? '运行信息' : 'Runtime Info'}</h2>
        <div className="runtime-info">
          <div className="runtime-item">
            <span className="runtime-label">{t('tick')}</span>
            <span className="runtime-value">{state.tick.toLocaleString()}</span>
          </div>
          <div className="runtime-item">
            <span className="runtime-label">{lang === 'zh' ? '运行时间' : 'Uptime'}</span>
            <span className="runtime-value">{state.uptime}</span>
          </div>
          <div className="runtime-item">
            <span className="runtime-label">{lang === 'zh' ? '上次互动' : 'Last Interaction'}</span>
            <span className="runtime-value">{state.last_interaction}</span>
          </div>
        </div>
      </section>
    </div>
  );
}

export default Status;
