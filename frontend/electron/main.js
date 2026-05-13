const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const xiaBridge = require('./xia-bridge');

let mainWindow;
let xiaClient = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#1a1a1f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  });

  const fs = require('fs');
  const htmlPath = path.join(__dirname, '../dist/index.html');
  console.log('[XIA] Loading HTML from:', htmlPath);
  console.log('[XIA] File exists:', fs.existsSync(htmlPath));

  // 检查 dist/index.html 是否存在，存在就用它
  if (fs.existsSync(htmlPath)) {
    mainWindow.loadFile(htmlPath);
  } else {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  }

  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDesc) => {
    console.log('[XIA] Failed to load:', errorCode, errorDesc);
  });

  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[XIA] Page loaded successfully');
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// 初始化 XIA bridge
function initXiaClient() {
  xiaClient = new xiaBridge.XiaBridge();
  return xiaClient;
}

// IPC handlers
function setupIpcHandlers() {
  // 对话
  ipcMain.handle('xia:chat', async (event, message) => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.chat(message);
  });

  // 获取状态
  ipcMain.handle('xia:getStatus', async () => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.getStatus();
  });

  // 心跳检测
  ipcMain.handle('xia:ping', async () => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.ping();
  });

  // 获取待处理行动
  ipcMain.handle('xia:getPendingActions', async () => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.getPendingActions();
  });

  // 响应敲门
  ipcMain.handle('xia:respondToReach', async (event, response) => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.respondToReach(response);
  });

  // 发送回复到 response.json
  ipcMain.handle('xia:sendResponse', async (event, response) => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.sendResponse(response);
  });

  // 获取内心日记
  ipcMain.handle('xia:getDiary', async () => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.getDiary();
  });

  // 获取日志
  ipcMain.handle('xia:getLogs', async (event, filename, limit) => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.getLogs(filename, limit);
  });

  // 获取词汇库
  ipcMain.handle('xia:getVocab', async () => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.getVocab();
  });

  // 运行训练 tick
  ipcMain.handle('xia:runTrainingTick', async (event, overrideState) => {
    if (!xiaClient) initXiaClient();
    return await xiaClient.runTrainingTick(overrideState);
  });
}

app.whenReady().then(() => {
  initXiaClient();
  setupIpcHandlers();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
