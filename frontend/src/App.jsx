import { useState, useEffect, useCallback } from 'react';
import StatusBar from './components/StatusBar/StatusBar';
import Chat from './components/Chat/Chat';
import Status from './components/Status/Status';
import Training from './components/Training/Training';
import Logs from './components/Logs/Logs';
import Actions from './components/Actions/Actions';
import Diary from './components/Diary/Diary';
import Settings from './components/Settings/Settings';
import { useLanguage } from './contexts/LanguageContext';

const TABS = [
  { id: 'chat',     labelKey: 'nav_chat',     icon: '💬' },
  { id: 'status',   labelKey: 'nav_status',   icon: '📊' },
  { id: 'training', labelKey: 'nav_training', icon: '🎯' },
  { id: 'logs',     labelKey: 'nav_logs',     icon: '📋' },
  { id: 'actions',  labelKey: 'nav_actions',  icon: '📝' },
  { id: 'diary',    labelKey: 'nav_diary',    icon: '🌙' },
  { id: 'settings', labelKey: 'nav_settings', icon: '⚙️' },
];

function App() {
  const [activeTab, setActiveTab] = useState('chat');
  const [xiaState, setXiaState] = useState(null);
  const [xiaError, setXiaError] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const { t, toggle, lang } = useLanguage();

  const fetchStatus = useCallback(async () => {
    if (typeof window !== 'undefined' && window.xia) {
      try {
        const status = await window.xia.getStatus();
        if (!status.error) {
          setXiaState(status);
          setXiaError(null);
        } else {
          setXiaError(status.message);
        }
      } catch (err) {
        setXiaError(err.message);
      } finally {
        setIsLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const renderContent = () => {
    switch (activeTab) {
      case 'chat':     return <Chat xiaState={xiaState} onStateUpdate={fetchStatus} />;
      case 'status':   return <Status xiaState={xiaState} />;
      case 'training': return <Training xiaState={xiaState} />;
      case 'logs':     return <Logs />;
      case 'actions':  return <Actions />;
      case 'diary':    return <Diary />;
      case 'settings': return <Settings xiaState={xiaState} />;
      default: return null;
    }
  };

  const activeTabLabel = TABS.find((tab) => tab.id === activeTab)?.labelKey;
  const activeTabText = t(activeTabLabel || 'nav_chat');

  return (
    <div className="app">
      <StatusBar xiaState={xiaState} isLoading={isLoading} />
      <div className="app-content">
        <nav className="sidebar">
          <div className="sidebar-top-controls">
            <button
              className="lang-toggle-btn"
              onClick={toggle}
              title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
            >
              {lang === 'zh' ? 'EN' : '中'}
            </button>
          </div>
          <div className="sidebar-nav">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="nav-item-icon">{tab.icon}</span>
                <span className="nav-item-label">{t(tab.labelKey)}</span>
              </button>
            ))}
          </div>
        </nav>
        <main className="main-content">
          {xiaError && activeTab === 'chat' && (
            <div style={{ padding: '16px 24px', background: '#ef444420', borderBottom: '1px solid #ef4444' }}>
              <span style={{ color: '#ef4444' }}>{xiaError}</span>
            </div>
          )}
          <div className="content-header">
            <h1>{activeTabText}</h1>
          </div>
          <div className="content-body">
            {renderContent()}
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;
