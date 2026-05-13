import { useState, useRef, useEffect } from 'react';
import { useLanguage } from '../../contexts/LanguageContext';
import './Chat.css';

const STORAGE_KEY = 'xia_chat_history';
const MAX_HISTORY = 100;

function Chat({ xiaState, onStateUpdate }) {
  const { t } = useLanguage();
  const [messages, setMessages] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved ? JSON.parse(saved) : [];
    } catch { return []; }
  });
  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [xiaTyping, setXiaTyping] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(messages.slice(-MAX_HISTORY)));
    } catch (e) { console.error('Failed to save chat history:', e); }
  }, [messages]);

  const clearHistory = () => {
    if (window.confirm(t('chat_clear') + '?')) {
      setMessages([]);
      localStorage.removeItem(STORAGE_KEY);
    }
  };

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || isSending) return;

    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: text,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    setIsSending(true);
    setXiaTyping(true);

    try {
      const response = await window.xia.chat(text);
      if (response.error) {
        setMessages(prev => [...prev, {
          id: Date.now() + 1,
          role: 'xia',
          content: `${t('error')}: ${response.message}`,
          timestamp: new Date(),
          isError: true,
        }]);
      } else {
        setMessages(prev => [...prev, {
          id: Date.now() + 1,
          role: 'xia',
          content: response.response?.text || t('no_data'),
          timestamp: new Date(),
          decision: response.decision,
          stateSnapshot: response.state_snapshot,
        }]);
        if (onStateUpdate) onStateUpdate();
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        role: 'xia',
        content: `${t('error')}: ${err.message}`,
        timestamp: new Date(),
        isError: true,
      }]);
    } finally {
      setIsSending(false);
      setXiaTyping(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const formatTime = (date) => {
    const d = date instanceof Date ? date : new Date(date);
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  };

  return (
    <div className="chat">
      <div className="chat-header">
        {messages.length > 0 && (
          <button className="btn-clear-history" onClick={clearHistory}>
            🗑️ {t('chat_clear')}
          </button>
        )}
        {messages.length > 0 && (
          <span className="chat-count">{t('chat_count', { n: messages.length })}</span>
        )}
      </div>

      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">💬</div>
            <p>{t('chat_placeholder').replace('...', '')}</p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`message ${msg.role === 'xia' ? 'message-xia' : 'message-user'}`}
          >
            <div className="message-header">
              <span className="message-sender">{msg.role === 'xia' ? 'XIA' : '你'}</span>
              <span className="message-time">{formatTime(msg.timestamp)}</span>
            </div>
            <div className="message-content">{msg.content}</div>
            {msg.role === 'xia' && msg.decision && (
              <div className="message-meta">
                <span className="meta-tag">[{msg.decision.action_type || 'idle'}]</span>
                <span className="meta-priority">{(msg.decision.priority ?? 0).toFixed(2)}</span>
              </div>
            )}
          </div>
        ))}

        {xiaTyping && (
          <div className="message message-xia message-typing">
            <div className="typing-indicator">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input">
        <input
          ref={inputRef}
          type="text"
          className="input-field"
          placeholder={t('chat_placeholder')}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isSending}
        />
        <button
          className="btn btn-primary"
          onClick={handleSend}
          disabled={isSending || !inputValue.trim()}
        >
          {t('chat_send')}
        </button>
      </div>
    </div>
  );
}

export default Chat;
