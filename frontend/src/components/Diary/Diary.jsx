import { useState, useEffect, useCallback } from 'react';
import './Diary.css';

const TYPE_CONFIG = {
  thought:      { label: '思考', color: 'var(--info-gap-color)' },
  feeling:      { label: '感受', color: 'var(--accent)' },
  state_change:  { label: '状态变化', color: 'var(--loneliness-color)' },
  observation:   { label: '观测', color: 'var(--text-muted)' },
  question:      { label: '疑问', color: 'var(--boredom-color)' },
};

const EMOTION_TAG_COLORS = {
  '孤独':     'var(--loneliness-color)',
  '疲惫':     'var(--fatigue-color)',
  '无聊':     'var(--boredom-color)',
  '压力':     'var(--stress-color)',
  '体感正面':  'var(--positive-tone)',
  '体感负面':  'var(--negative-tone)',
};

function Diary() {
  const [entries, setEntries] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [filter, setFilter] = useState('all');

  const loadDiary = useCallback(async () => {
    setIsLoading(true);
    try {
      if (window.xia) {
        const diary = await window.xia.getDiary();
        setEntries(diary || []);
      }
    } catch (err) {
      console.error('Failed to load diary:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDiary();
    const interval = setInterval(loadDiary, 8000);
    return () => clearInterval(interval);
  }, [loadDiary]);

  const formatTime = (ts) => {
    if (!ts) return '—';
    const date = new Date(ts * 1000);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return '刚刚';
    if (diffMins < 60) return `${diffMins} 分钟前`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} 小时前`;
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const filteredEntries = filter === 'all'
    ? entries
    : entries.filter(e => e.type === filter);

  return (
    <div className="diary">
      {/* 过滤器 */}
      <div className="diary-filter">
        {['all', 'feeling', 'thought', 'observation'].map(f => (
          <button
            key={f}
            className={`filter-btn ${filter === f ? 'active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f === 'all' ? '全部' : TYPE_CONFIG[f]?.label || f}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="loading">
          <div className="loading-spinner" />
          加载中...
        </div>
      ) : filteredEntries.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">🌙</div>
          <p>还没有内心日记</p>
          <p className="empty-state-text">
            daemon 运行时，她会在每个 tick 结束后写下内心独白
          </p>
        </div>
      ) : (
        <div className="diary-list">
          {filteredEntries.map((entry, idx) => {
            const cfg = TYPE_CONFIG[entry.type] || TYPE_CONFIG.observation;
            const snapshot = entry.state_snapshot || {};
            return (
              <div key={idx} className="diary-entry">
                <div className="entry-header">
                  <span
                    className="entry-type"
                    style={{
                      backgroundColor: `${cfg.color}20`,
                      color: cfg.color,
                    }}
                  >
                    {cfg.label}
                  </span>
                  <span className="entry-time">{formatTime(entry.timestamp)}</span>
                  <span className="entry-tick">tick {entry.tick}</span>
                </div>

                <div className="entry-text">{entry.text}</div>

                {/* 情绪关键词 */}
                {entry.emotional_keywords && entry.emotional_keywords.length > 0 && (
                  <div className="entry-tags">
                    {entry.emotional_keywords.map(tag => (
                      <span
                        key={tag}
                        className="entry-tag"
                        style={{ color: EMOTION_TAG_COLORS[tag] || 'var(--text-secondary)' }}
                      >
                        #{tag}
                      </span>
                    ))}
                  </div>
                )}

                {/* 状态快照 */}
                {snapshot && Object.keys(snapshot).length > 0 && (
                  <div className="entry-snapshot">
                    {Object.entries(snapshot).map(([key, val]) => (
                      <span key={key} className="snapshot-chip">
                        {key}: {typeof val === 'number' ? val.toFixed(2) : val}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default Diary;
