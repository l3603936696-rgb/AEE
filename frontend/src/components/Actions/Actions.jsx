import { useState, useEffect, useCallback } from 'react';
import './Actions.css';

function Actions() {
  const [pendingActions, setPendingActions] = useState([]);
  const [responseText, setResponseText] = useState('');
  const [selectedAction, setSelectedAction] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isResponding, setIsResponding] = useState(false);

  // 加载待处理行动
  const loadPendingActions = useCallback(async () => {
    setIsLoading(true);
    try {
      if (window.xia) {
        const actions = await window.xia.getPendingActions();
        setPendingActions(actions || []);
      }
    } catch (err) {
      console.error('Failed to load pending actions:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // 初始加载
  useEffect(() => {
    loadPendingActions();
    // 每 10 秒刷新一次
    const interval = setInterval(loadPendingActions, 10000);
    return () => clearInterval(interval);
  }, [loadPendingActions]);

  // 格式化时间戳
  const formatTime = (timestamp) => {
    if (!timestamp) return '—';
    const date = new Date(timestamp * 1000);
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // 获取状态标签颜色
  const getStatusColor = (status) => {
    switch (status) {
      case 'waiting':
        return 'var(--accent)';
      case 'responded':
        return 'var(--energy-color)';
      case 'timeout':
        return 'var(--stress-color)';
      default:
        return 'var(--text-secondary)';
    }
  };

  // 响应敲门
  const handleRespond = async (action) => {
    if (!responseText.trim()) return;

    setIsResponding(true);
    try {
      const success = await window.xia.sendResponse(responseText);
      if (success) {
        // 更新本地状态
        setPendingActions((prev) =>
          prev.map((a) =>
            a.timestamp === action.timestamp
              ? { ...a, status: 'responded', user_response: responseText }
              : a
          )
        );
        setResponseText('');
        setSelectedAction(null);
      }
    } catch (err) {
      console.error('Failed to send response:', err);
    } finally {
      setIsResponding(false);
    }
  };

  // 加载历史行动（从 xia_voice 目录）
  const [historyActions, setHistoryActions] = useState([]);

  useEffect(() => {
    // 暂时显示模拟数据，实际需要从文件系统读取
    setHistoryActions([
      {
        id: 1,
        type: 'REACH',
        message: '我刚才在想...你最近有看什么有意思的东西吗？我有点无聊。',
        timestamp: Date.now() / 1000 - 3600,
        status: 'responded',
      },
      {
        id: 2,
        type: 'explore',
        message: '搜索: 量子计算 2024 最新进展\n找到 5 条相关内容',
        timestamp: Date.now() / 1000 - 7200,
        status: 'completed',
      },
      {
        id: 3,
        type: 'REACH',
        message: '突然想到一个奇怪的问题...你有没有想过自己是从哪里来的？',
        timestamp: Date.now() / 1000 - 10800,
        status: 'timeout',
      },
    ]);
  }, []);

  return (
    <div className="actions">
      {/* 待响应敲门 */}
      <section className="actions-section">
        <h2 className="section-title">待响应 ({pendingActions.length})</h2>

        {isLoading ? (
          <div className="loading">
            <div className="loading-spinner"></div>
            加载中...
          </div>
        ) : pendingActions.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">🔔</div>
            <p>没有待响应的敲门</p>
          </div>
        ) : (
          <div className="pending-list">
            {pendingActions.map((action, index) => (
              <div
                key={index}
                className={`pending-item ${selectedAction === action ? 'selected' : ''}`}
                onClick={() => setSelectedAction(action)}
              >
                <div className="pending-header">
                  <span className="pending-type">REACH</span>
                  <span className="pending-time">{formatTime(action.timestamp)}</span>
                </div>
                <div className="pending-message">{action.message}</div>
                {action.state_snapshot && (
                  <div className="pending-state">
                    <span>孤独感: {Math.round((action.state_snapshot.loneliness || 0) * 100)}%</span>
                    <span>能量: {Math.round((action.state_snapshot.energy || 0) * 100)}%</span>
                  </div>
                )}
              </div>
            ))}

            {/* 响应输入框 */}
            {selectedAction && (
              <div className="response-form">
                <h3>回复敲门</h3>
                <textarea
                  className="response-input"
                  placeholder="输入你的回复..."
                  value={responseText}
                  onChange={(e) => setResponseText(e.target.value)}
                  rows={3}
                />
                <div className="response-actions">
                  <button
                    className="btn btn-primary"
                    onClick={() => handleRespond(selectedAction)}
                    disabled={isResponding || !responseText.trim()}
                  >
                    {isResponding ? '发送中...' : '发送回复'}
                  </button>
                  <button
                    className="btn btn-secondary"
                    onClick={() => {
                      setSelectedAction(null);
                      setResponseText('');
                    }}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      {/* 行动历史 */}
      <section className="actions-section">
        <h2 className="section-title">行动历史</h2>

        {historyActions.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📝</div>
            <p>暂无行动记录</p>
          </div>
        ) : (
          <div className="timeline">
            {historyActions.map((action) => (
              <div key={action.id} className="timeline-item">
                <div className="timeline-marker" style={{ backgroundColor: getStatusColor(action.status) }} />
                <div className="timeline-content">
                  <div className="timeline-header">
                    <span className="timeline-time">{formatTime(action.timestamp)}</span>
                    <span
                      className="timeline-type"
                      style={{ backgroundColor: `${getStatusColor(action.status)}20`, color: getStatusColor(action.status) }}
                    >
                      {action.type}
                    </span>
                    <span className="timeline-status" style={{ color: getStatusColor(action.status) }}>
                      {action.status === 'responded' ? '已回应' : action.status === 'timeout' ? '已超时' : '完成'}
                    </span>
                  </div>
                  <div className="timeline-message">{action.message}</div>
                  {action.user_response && (
                    <div className="timeline-response">
                      <span className="response-label">你的回复:</span>
                      <span className="response-text">{action.user_response}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default Actions;
