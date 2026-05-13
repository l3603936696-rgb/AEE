import { useState } from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import './Settings.css';

function Settings({ xiaState }) {
  const { t, toggle, lang } = useLanguage();
  const [settings, setSettings] = useState({
    enableActions: true,
    showActionLogs: true,
    actionCooldown: 10,
    autoRefresh: true,
    refreshInterval: 5,
  });

  const [debugInfo, setDebugInfo] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  // 语言设置放在顶部
  const langSection = (
    <section className="settings-section">
      <h2 className="settings-section-title">{t('settings_language')}</h2>
      <div className="settings-card">
        <div className="settings-row">
          <span className="settings-label">{t('settings_language')}</span>
          <div className="lang-toggle">
            <button
              className={`lang-btn ${lang === 'zh' ? 'active' : ''}`}
              onClick={() => lang !== 'zh' && toggle()}
            >{t('settings_lang_zh')}</button>
            <button
              className={`lang-btn ${lang === 'en' ? 'active' : ''}`}
              onClick={() => lang !== 'en' && toggle()}
            >{t('settings_lang_en')}</button>
          </div>
        </div>
      </div>
    </section>
  );

  // 切换设置
  const toggleSetting = (key) => {
    setSettings((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  // 更新数值设置
  const updateNumberSetting = (key, value) => {
    const num = parseInt(value, 10);
    if (!isNaN(num) && num >= 0) {
      setSettings((prev) => ({
        ...prev,
        [key]: num,
      }));
    }
  };

  // 查看完整实体状态
  const showEntityState = () => {
    setDebugInfo({
      type: 'entity',
      data: xiaState,
    });
  };

  // 查看探针日志
  const showProbeLog = async () => {
    setIsLoading(true);
    try {
      // 实际应该从文件系统读取
      setDebugInfo({
        type: 'probe',
        data: '探针日志功能开发中...',
      });
    } catch (err) {
      setDebugInfo({
        type: 'error',
        data: err.message,
      });
    } finally {
      setIsLoading(false);
    }
  };

  // 重置调试弹窗
  const closeDebugInfo = () => {
    setDebugInfo(null);
  };

  return (
    <div className="settings">
      {langSection}
      {/* 连接设置 */}
      <section className="settings-section">
        <h2 className="settings-section-title">连接设置</h2>
        <div className="settings-card">
          <div className="settings-row">
            <span className="settings-label">Daemon Socket</span>
            <span className="settings-value mono">data/xia_daemon.sock</span>
          </div>
          <div className="settings-row">
            <span className="settings-label">Ollama 地址</span>
            <span className="settings-value mono">{xiaState?.ollama_alive !== undefined ? (xiaState.ollama_alive ? '172.31.112.1:11434' : '未连接') : '—'}</span>
          </div>
          <div className="settings-row">
            <span className="settings-label">连接状态</span>
            <span className={`settings-status ${xiaState?.error ? 'error' : 'success'}`}>
              {xiaState?.error ? '离线' : '在线'}
            </span>
          </div>
        </div>
      </section>

      {/* 行为设置 */}
      <section className="settings-section">
        <h2 className="settings-section-title">行为设置</h2>
        <div className="settings-card">
          <div className="settings-row">
            <span className="settings-label">启用主动行动敲门</span>
            <button
              className={`toggle ${settings.enableActions ? 'active' : ''}`}
              onClick={() => toggleSetting('enableActions')}
            >
              <span className="toggle-knob" />
            </button>
          </div>
          <div className="settings-row">
            <span className="settings-label">显示行动日志</span>
            <button
              className={`toggle ${settings.showActionLogs ? 'active' : ''}`}
              onClick={() => toggleSetting('showActionLogs')}
            >
              <span className="toggle-knob" />
            </button>
          </div>
          <div className="settings-row">
            <span className="settings-label">敲门冷却时间</span>
            <div className="settings-input-group">
              <input
                type="number"
                className="settings-input"
                value={settings.actionCooldown}
                onChange={(e) => updateNumberSetting('actionCooldown', e.target.value)}
                min={1}
                max={60}
              />
              <span className="settings-input-suffix">分钟</span>
            </div>
          </div>
        </div>
      </section>

      {/* 自动刷新设置 */}
      <section className="settings-section">
        <h2 className="settings-section-title">自动刷新</h2>
        <div className="settings-card">
          <div className="settings-row">
            <span className="settings-label">启用自动刷新</span>
            <button
              className={`toggle ${settings.autoRefresh ? 'active' : ''}`}
              onClick={() => toggleSetting('autoRefresh')}
            >
              <span className="toggle-knob" />
            </button>
          </div>
          <div className="settings-row">
            <span className="settings-label">刷新间隔</span>
            <div className="settings-input-group">
              <input
                type="number"
                className="settings-input"
                value={settings.refreshInterval}
                onChange={(e) => updateNumberSetting('refreshInterval', e.target.value)}
                min={1}
                max={60}
                disabled={!settings.autoRefresh}
              />
              <span className="settings-input-suffix">秒</span>
            </div>
          </div>
        </div>
      </section>

      {/* 调试工具 */}
      <section className="settings-section">
        <h2 className="settings-section-title">调试</h2>
        <div className="settings-card">
          <div className="debug-buttons">
            <button className="debug-btn" onClick={showEntityState}>
              查看完整实体状态
            </button>
            <button className="debug-btn" onClick={showProbeLog} disabled={isLoading}>
              查看探针日志
            </button>
          </div>
        </div>
      </section>

      {/* 关于 */}
      <section className="settings-section">
        <h2 className="settings-section-title">关于</h2>
        <div className="settings-card">
          <div className="settings-row">
            <span className="settings-label">版本</span>
            <span className="settings-value">1.0.0</span>
          </div>
          <div className="settings-row">
            <span className="settings-label">XIA 引擎</span>
            <span className="settings-value">v3.x</span>
          </div>
          <div className="settings-row">
            <span className="settings-label">Electron</span>
            <span className="settings-value">28.x</span>
          </div>
        </div>
      </section>

      {/* 调试弹窗 */}
      {debugInfo && (
        <div className="debug-modal-overlay" onClick={closeDebugInfo}>
          <div className="debug-modal" onClick={(e) => e.stopPropagation()}>
            <div className="debug-modal-header">
              <h3>{debugInfo.type === 'entity' ? '实体状态' : debugInfo.type === 'probe' ? '探针日志' : '错误'}</h3>
              <button className="debug-modal-close" onClick={closeDebugInfo}>×</button>
            </div>
            <div className="debug-modal-content">
              <pre>{JSON.stringify(debugInfo.data, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Settings;
