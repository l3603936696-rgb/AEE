import { useState, useEffect, useCallback } from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import './Training.css';

const DIMENSIONS = [
  { key: 'fatigue',        min: 0, max: 1, label: 'Fatigue',       color: 'var(--fatigue-color)' },
  { key: 'energy',         min: 0, max: 1, label: 'Energy',        color: 'var(--energy-color)' },
  { key: 'loneliness',     min: 0, max: 1, label: 'Loneliness',    color: 'var(--loneliness-color)' },
  { key: 'stress',          min: 0, max: 1, label: 'Stress',        color: 'var(--stress-color)' },
  { key: 'approach_drive',  min: 0, max: 1, label: 'Approach',      color: 'var(--positive-tone)' },
  { key: 'avoid_drive',     min: 0, max: 1, label: 'Avoid',       color: 'var(--negative-tone)' },
  { key: 'boredom',         min: 0, max: 1, label: 'Boredom',       color: 'var(--boredom-color)' },
  { key: 'info_gap',        min: 0, max: 1, label: 'Info Gap',     color: 'var(--info-gap-color)' },
];

function Training({ xiaState }) {
  const { t } = useLanguage();
  const [override, setOverride] = useState({});
  const [result, setResult] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [vocab, setVocab] = useState(null);
  const [isLoadingVocab, setIsLoadingVocab] = useState(true);

  // 初始化 override 从 xiaState
  useEffect(() => {
    if (!xiaState) return;
    const init = {};
    DIMENSIONS.forEach(({ key }) => {
      if (xiaState[key] !== undefined) {
        init[key] = xiaState[key];
      }
    });
    setOverride(init);
  }, [xiaState]);

  // 加载词汇库
  const loadVocab = useCallback(async () => {
    setIsLoadingVocab(true);
    try {
      const data = await window.xia.getVocab();
      setVocab(data);
    } catch (err) {
      console.error('Failed to load vocab:', err);
    } finally {
      setIsLoadingVocab(false);
    }
  }, []);

  useEffect(() => { loadVocab(); }, [loadVocab]);

  // 运行训练 tick
  const runTick = async () => {
    setIsRunning(true);
    setResult(null);
    try {
      const data = await window.xia.runTrainingTick(override);
      console.log('[Training] result:', JSON.stringify(data));
      setResult(data);
    } catch (err) {
      setResult({ error: err.message });
    } finally {
      setIsRunning(false);
    }
  };

  // 还原到真实状态
  const restoreReal = () => {
    if (!xiaState) return;
    const restored = {};
    DIMENSIONS.forEach(({ key }) => {
      if (xiaState[key] !== undefined) {
        restored[key] = xiaState[key];
      }
    });
    setOverride(restored);
    setResult(null);
  };

  const updateDim = (key, val) => {
    setOverride(prev => ({ ...prev, [key]: val }));
  };

  // 消力效率条
  const EfficiencyBar = ({ value }) => (
    <div className="eff-bar">
      <div
        className="eff-fill"
        style={{ width: `${Math.min(100, value * 100)}%` }}
      />
      <span className="eff-value">{(value * 100).toFixed(1)}%</span>
    </div>
  );

  return (
    <div className="training">
      {/* 左栏：状态注入 */}
      <div className="training-left">
        <h2 className="section-title">{t('train_inject_state')}</h2>

        <div className="dim-list">
          {DIMENSIONS.map(({ key, color }) => (
            <div key={key} className="dim-item">
              <div className="dim-header">
                <span className="dim-label">{t(`status_${key}`) || key}</span>
                <span className="dim-value" style={{ color }}>
                  {(override[key] ?? 0).toFixed(3)}
                </span>
              </div>
              <input
                type="range"
                className="dim-slider"
                min="0"
                max="1"
                step="0.01"
                value={override[key] ?? 0}
                onChange={(e) => updateDim(key, parseFloat(e.target.value))}
                style={{ '--slider-color': color }}
              />
            </div>
          ))}
        </div>

        <div className="training-actions">
          <button
            className="btn btn-primary"
            onClick={runTick}
            disabled={isRunning}
          >
            {isRunning ? '...' : t('train_run')}
          </button>
          <button
            className="btn btn-secondary"
            onClick={restoreReal}
          >
            {t('train_restore')}
          </button>
        </div>

        {/* 结果 */}
        {result && (
          <div className="training-result">
            <h3 className="section-title">{t('train_result')}</h3>
            {result.error ? (
              <div className="result-error">{result.error}</div>
            ) : (
              <div className="result-grid">
                {result.composed && (
                  <div className="result-composed">
                    <span className="result-composed-label">{t('train_composed')}</span>
                    <span className="result-composed-text">{result.composed}</span>
                  </div>
                )}
                {result.best && (
                  <div className="result-word result-best">
                    <span className="result-word-label">1.</span>
                    <span className="result-word-text">{result.best}</span>
                    <span className="result-score">{(result.best_score ?? 0).toFixed(3)}</span>
                  </div>
                )}
                {result.second && (
                  <div className="result-word">
                    <span className="result-word-label">2.</span>
                    <span className="result-word-text">{result.second}</span>
                    <span className="result-score">{(result.second_score ?? 0).toFixed(3)}</span>
                  </div>
                )}
                {result.third && (
                  <div className="result-word">
                    <span className="result-word-label">3.</span>
                    <span className="result-word-text">{result.third}</span>
                  </div>
                )}
                <div className="result-meta">
                  <span>candidates: {result.cand_count}</span>
                  <span>warm: {result.warm_count}</span>
                  <span>ms: {result.ms}</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 右栏：词汇库 */}
      <div className="training-right">
        <div className="vocab-header">
          <h2 className="section-title">{t('train_vocab')}</h2>
          <button className="btn btn-secondary btn-small" onClick={loadVocab} disabled={isLoadingVocab}>
            {isLoadingVocab ? '...' : t('log_refresh')}
          </button>
        </div>

        {isLoadingVocab ? (
          <div className="loading">
            <div className="loading-spinner" />{t('loading')}
          </div>
        ) : !vocab ? (
          <div className="empty-state">
            <div className="empty-state-icon">📚</div>
            <p>{t('no_data')}</p>
          </div>
        ) : (
          <div className="vocab-content">
            {/* 已解锁词汇 */}
            <div className="vocab-section">
              <h3 className="vocab-section-title">{t('train_unlocked')} ({vocab.unlocked?.length ?? 0})</h3>
              <div className="vocab-chips">
                {(vocab.unlocked || []).length === 0 ? (
                  <span className="vocab-empty">{t('no_data')}</span>
                ) : (
                  vocab.unlocked.map((word, i) => (
                    <span key={i} className="vocab-chip">{word}</span>
                  ))
                )}
              </div>
            </div>

            {/* 词效率统计 */}
            <div className="vocab-section">
              <h3 className="vocab-section-title">{t('train_word_stats')}</h3>
              {vocab.word_efficiency && Object.keys(vocab.word_efficiency).length > 0 ? (
                <div className="eff-list">
                  {Object.entries(vocab.word_efficiency)
                    .sort((a, b) => b[1] - a[1])
                    .map(([word, eff]) => (
                      <div key={word} className="eff-row">
                        <span className="eff-word">{word}</span>
                        <EfficiencyBar value={eff} />
                      </div>
                    ))}
                </div>
              ) : (
                <span className="vocab-empty">{t('no_data')}</span>
              )}
            </div>
          </div>
        )}

        {/* 模板学习状态 */}
        <div className="vocab-section">
          <h3 className="vocab-section-title">{t('train_templates')}</h3>
          <div className="template-count">
            {t('train_learned')}: <strong>{vocab.learned_template_count ?? 0}</strong>
          </div>
          <div className="runtime-templates">
            <div className="template-count">
              {t('train_runtime')}: <strong>{vocab.runtime_templates?.length ?? 0}</strong>
            </div>
            {(!vocab.runtime_templates || vocab.runtime_templates.length === 0) ? (
              <div className="vocab-empty">{t('train_no_runtime')}</div>
            ) : (
              <div className="runtime-list">
                {vocab.runtime_templates.map((tmpl, i) => (
                  <div key={i} className="runtime-item">
                    <span className="runtime-template">{tmpl.template}</span>
                    <span className="runtime-born">tick {tmpl.born_tick}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Training;
