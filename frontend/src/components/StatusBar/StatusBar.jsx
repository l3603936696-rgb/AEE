import { useMemo } from 'react';
import './StatusBar.css';

function StatusBar({ xiaState, isLoading }) {
  // 从 xiaState 中提取关键数据
  const state = useMemo(() => {
    if (!xiaState) {
      return {
        energy: 0,
        somatic_tone: 0,
        loneliness: 0,
        tick: 0,
        uptime: '—',
        lastInteraction: '—',
        isConnected: false,
      };
    }

    // 计算运行时间
    let uptime = '—';
    if (xiaState.uptime_s) {
      const hours = Math.floor(xiaState.uptime_s / 3600);
      const mins = Math.floor((xiaState.uptime_s % 3600) / 60);
      uptime = `${hours}h ${mins}m`;
    }

    // 格式化上次互动时间
    let lastInteraction = '—';
    if (xiaState.last_interaction && xiaState.last_interaction !== 'never') {
      try {
        const date = new Date(xiaState.last_interaction);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 1) {
          lastInteraction = '刚刚';
        } else if (diffMins < 60) {
          lastInteraction = `${diffMins} 分钟前`;
        } else {
          const diffHours = Math.floor(diffMins / 60);
          lastInteraction = `${diffHours} 小时前`;
        }
      } catch {
        lastInteraction = xiaState.last_interaction;
      }
    }

    return {
      energy: xiaState.energy ?? 0,
      somatic_tone: xiaState.somatic_tone ?? 0,
      loneliness: xiaState.loneliness ?? 0,
      fatigue: xiaState.fatigue ?? 0,
      tick: xiaState.current_tick ?? xiaState.tick ?? 0,
      uptime,
      lastInteraction,
      isConnected: !xiaState.error,
    };
  }, [xiaState]);

  // 根据躯体基调判断情绪文字
  const getMoodText = (tone) => {
    if (tone > 0.3) return '愉悦';
    if (tone > 0.1) return '平静';
    if (tone > -0.1) return '一般';
    if (tone > -0.3) return '低落';
    return '痛苦';
  };

  // 能量条颜色
  const getEnergyColor = (energy) => {
    if (energy > 0.6) return 'var(--energy-color)';
    if (energy > 0.3) return 'var(--boredom-color)';
    return 'var(--stress-color)';
  };

  return (
    <header className="status-bar">
      <div className="status-bar-left">
        <div className="status-bar-logo">
          <span className="logo-text">XIA</span>
          <span className={`status-indicator ${state.isConnected ? 'connected' : 'disconnected'}`}>
            {state.isConnected ? '运行中' : '离线'}
          </span>
        </div>
      </div>

      <div className="status-bar-center">
        <div className="status-bar-item">
          <span className="status-bar-label">能量</span>
          <div className="status-bar-mini">
            <div
              className="status-bar-mini-fill"
              style={{
                width: `${state.energy * 100}%`,
                backgroundColor: getEnergyColor(state.energy),
              }}
            />
          </div>
          <span className="status-bar-value">{Math.round(state.energy * 100)}%</span>
        </div>

        <div className="status-bar-divider" />

        <div className="status-bar-item">
          <span className="status-bar-label">情绪</span>
          <span className="status-bar-mood">{getMoodText(state.somatic_tone)}</span>
        </div>

        <div className="status-bar-divider" />

        <div className="status-bar-item">
          <span className="status-bar-label">孤独感</span>
          <span className="status-bar-value" style={{ color: 'var(--loneliness-color)' }}>
            {Math.round(state.loneliness * 100)}%
          </span>
        </div>

        <div className="status-bar-divider" />

        <div className="status-bar-item">
          <span className="status-bar-label">Tick</span>
          <span className="status-bar-value">{state.tick.toLocaleString()}</span>
        </div>
      </div>

      <div className="status-bar-right">
        <span className="status-bar-meta">
          {isLoading ? '加载中...' : `运行 ${state.uptime}`}
        </span>
      </div>
    </header>
  );
}

export default StatusBar;
