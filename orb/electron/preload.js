'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('orbHost', {
  platform: process.platform,
  toggleFullscreen: () => ipcRenderer.invoke('window:toggle-fullscreen'),
  /** @returns {Promise<string>} absolute path the PNG was written to */
  saveCapture: (bytes, filename) => ipcRenderer.invoke('capture:save', bytes, filename),
});
