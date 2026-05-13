const { contextBridge, ipcRenderer } = require('electron');

// 暴露给渲染进程的 API
contextBridge.exposeInMainWorld('xia', {
  // 对话
  chat: (message) => ipcRenderer.invoke('xia:chat', message),

  // 获取状态
  getStatus: () => ipcRenderer.invoke('xia:getStatus'),

  // 心跳检测
  ping: () => ipcRenderer.invoke('xia:ping'),

  // 获取待处理行动
  getPendingActions: () => ipcRenderer.invoke('xia:getPendingActions'),

  // 响应敲门
  respondToReach: (response) => ipcRenderer.invoke('xia:respondToReach', response),

  // 发送回复
  sendResponse: (response) => ipcRenderer.invoke('xia:sendResponse', response),

  // 监听敲门通知
  onReachNotification: (callback) => {
    ipcRenderer.on('xia:reach-notification', (event, data) => callback(data));
    return () => ipcRenderer.removeAllListeners('xia:reach-notification');
  },

  // 获取内心日记
  getDiary: () => ipcRenderer.invoke('xia:getDiary'),

  // 获取日志
  getLogs: (filename, limit) => ipcRenderer.invoke('xia:getLogs', filename, limit),

  // 获取词汇库
  getVocab: () => ipcRenderer.invoke('xia:getVocab'),

  // 运行训练 tick
  runTrainingTick: (overrideState) => ipcRenderer.invoke('xia:runTrainingTick', overrideState),
});
