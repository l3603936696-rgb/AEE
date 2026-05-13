/**
 * XIA Bridge - HTTP API 客户端封装
 *
 * 通过 HTTP API 连接 XIA daemon (http://127.0.0.1:8765)
 * 独立封装，方便后续改为 WebSocket 或其他通信方式
 */

const http = require('http');

class XiaBridge {
  constructor() {
    // daemon HTTP API 地址
    this.apiHost = '127.0.0.1';
    this.apiPort = 8765;
    this.timeout = 30000; // 30s
  }

  /**
   * 发送 HTTP POST 请求
   * @param {Object} data - 请求数据
   * @returns {Promise<Object>} 响应对象
   */
  _postRequest(data) {
    return new Promise((resolve, reject) => {
      const body = JSON.stringify(data);

      const options = {
        hostname: this.apiHost,
        port: this.apiPort,
        path: '/',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
        },
        timeout: this.timeout,
      };

      const req = http.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const response = JSON.parse(data);
            resolve(response);
          } catch (e) {
            reject(new Error(`Failed to parse response: ${e.message}`));
          }
        });
      });

      req.on('error', (err) => {
        reject(err);
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });

      req.write(body);
      req.end();
    });
  }

  /**
   * 发送 HTTP GET 请求
   * @param {string} path - 请求路径
   * @returns {Promise<Object>} 响应对象
   */
  _getRequest(path) {
    return new Promise((resolve, reject) => {
      const options = {
        hostname: this.apiHost,
        port: this.apiPort,
        path: path,
        method: 'GET',
        timeout: this.timeout,
      };

      const req = http.request(options, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const response = JSON.parse(data);
            resolve(response);
          } catch (e) {
            reject(new Error(`Failed to parse response: ${e.message}`));
          }
        });
      });

      req.on('error', (err) => {
        reject(err);
      });

      req.on('timeout', () => {
        req.destroy();
        reject(new Error('Request timeout'));
      });

      req.end();
    });
  }

  /**
   * 对话
   * @param {string} message - 用户消息
   * @returns {Promise<Object>} 包含 response, decision, state_snapshot 等
   */
  async chat(message) {
    try {
      const response = await this._postRequest({
        type: 'chat',
        payload: {
          text: message,
          debug: false,
        },
      });

      // 处理 IPCResponse 格式
      if (response.ok !== undefined) {
        if (!response.ok) {
          return {
            error: true,
            message: response.error || 'Unknown error',
          };
        }
        return response.result || response;
      }

      return response;
    } catch (err) {
      console.error('XIA Bridge chat error:', err.message);
      return {
        error: true,
        message: `无法连接 XIA daemon: ${err.message}`,
        hint: '请确保 daemon 已启动 (python -m src.daemon.daemon)',
      };
    }
  }

  /**
   * 获取 daemon 状态
   * @returns {Promise<Object>} daemon 运行状态
   */
  async getStatus() {
    try {
      const response = await this._getRequest('/status');
      return response;
    } catch (err) {
      console.error('XIA Bridge getStatus error:', err.message);
      return {
        error: true,
        message: `无法连接 XIA daemon: ${err.message}`,
      };
    }
  }

  /**
   * 心跳检测
   * @returns {Promise<boolean>}
   */
  async ping() {
    try {
      await this._postRequest({ type: 'ping', payload: {} });
      return true;
    } catch (err) {
      return false;
    }
  }

  /**
   * 获取待处理行动（读取 pending.json）
   * @returns {Promise<Array>} 待处理行动列表
   */
  async getPendingActions() {
    const fs = require('fs');
    const path = require('path');
    const dataDir = path.join(__dirname, '..', '..', '..', 'data', 'xia_messages');
    const pendingPath = path.join(dataDir, 'pending.json');

    try {
      if (fs.existsSync(pendingPath)) {
        const content = fs.readFileSync(pendingPath, 'utf-8');
        const pending = JSON.parse(content);
        return Array.isArray(pending) ? pending : [pending];
      }
      return [];
    } catch (err) {
      console.error('XIA Bridge getPendingActions error:', err.message);
      return [];
    }
  }

  /**
   * 响应敲门（写入 response.json）
   * @param {string} responseText - 用户回复文本
   * @returns {Promise<boolean>}
   */
  async respondToReach(responseText) {
    const fs = require('fs');
    const path = require('path');
    const dataDir = path.join(__dirname, '..', '..', '..', 'data', 'xia_messages');
    const responsePath = path.join(dataDir, 'response.json');

    try {
      const responseData = {
        text: responseText,
        timestamp: Date.now() / 1000,
      };
      fs.writeFileSync(responsePath, JSON.stringify(responseData, null, 2));
      return true;
    } catch (err) {
      console.error('XIA Bridge respondToReach error:', err.message);
      return false;
    }
  }

  /**
   * 发送回复（别名方法）
   */
  async sendResponse(responseText) {
    return this.respondToReach(responseText);
  }

  /**
   * 获取内心日记（读取 internal_log.jsonl）
   * @returns {Promise<Array>} 日记条目列表
   */
  async getDiary() {
    const fs = require('fs');
    const path = require('path');
    const dataDir = path.join(__dirname, '..', '..', '..', 'data', 'xia_inner_diary');
    const diaryPath = path.join(dataDir, 'internal_log.jsonl');

    try {
      if (fs.existsSync(diaryPath)) {
        const content = fs.readFileSync(diaryPath, 'utf-8');
        const lines = content.trim().split('\n').filter(l => l.trim());
        const recent = lines.slice(-50);
        return recent.map(line => {
          try { return JSON.parse(line); } catch { return null; }
        }).filter(Boolean).reverse();
      }
      return [];
    } catch (err) {
      console.error('XIA Bridge getDiary error:', err.message);
      return [];
    }
  }

  /**
   * 获取日志文件内容
   * @param {string} filename - 日志文件名
   * @param {number} limit - 最大行数
   * @returns {Promise<Object>}
   */
  async getLogs(filename = 'daemon.log', limit = 200) {
    try {
      const response = await this._getRequest(`/logs?file=${encodeURIComponent(filename)}&limit=${limit}`);
      return response;
    } catch (err) {
      console.error('XIA Bridge getLogs error:', err.message);
      return { error: err.message };
    }
  }

  /**
   * 获取词汇库数据
   * @returns {Promise<Object>}
   */
  async getVocab() {
    try {
      const response = await this._getRequest('/vocab');
      return response;
    } catch (err) {
      console.error('XIA Bridge getVocab error:', err.message);
      return { error: err.message };
    }
  }

  /**
   * 运行语言训练 tick
   * @param {Object} overrideState - 覆盖状态
   * @returns {Promise<Object>}
   */
  async runTrainingTick(overrideState = {}) {
    try {
      const response = await this._postRequest({
        type: 'training_tick',
        payload: { override_state: overrideState },
      });
      if (response.ok !== undefined) {
        if (!response.ok) {
          return { error: response.error };
        }
        return response.result || response;
      }
      return response;
    } catch (err) {
      console.error('XIA Bridge runTrainingTick error:', err.message);
      return { error: err.message };
    }
  }
}

module.exports = { XiaBridge };
