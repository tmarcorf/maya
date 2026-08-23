'use strict';

const { app, protocol, net, session, desktopCapturer, BrowserWindow, ipcMain, shell } = require('electron');
const crypto = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const ROOT = path.join(__dirname, '..');
const SCHEME = 'orb';
const ENTRY = `${SCHEME}://app/src/index.html`;

// A privileged custom scheme gives us a real origin: ES modules + import maps load
// without CORS errors and getUserMedia sees a secure context (file:// gives neither).
protocol.registerSchemesAsPrivileged([
  {
    scheme: SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true },
  },
]);

// Chromium needs a nudge to expose loopback capture reliably on Windows.
app.commandLine.appendSwitch('enable-features', 'AudioServiceOutOfProcess');

/**
 * The document is served with a fresh nonce on every load so the inline import
 * map (which three's addons need to resolve the bare "three" specifier) can run
 * under a strict CSP instead of 'unsafe-inline'.
 */
async function serveDocument(target) {
  const nonce = crypto.randomBytes(16).toString('base64');
  const html = (await fs.readFile(target, 'utf8')).replaceAll('__NONCE__', nonce);

  return new Response(html, {
    headers: {
      'content-type': 'text/html; charset=utf-8',
      'content-security-policy': [
        "default-src 'none'",
        `script-src 'self' 'nonce-${nonce}'`,
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self'",
      ].join('; '),
    },
  });
}

/** Maps orb://app/<path> to a file on disk, refusing anything that escapes ROOT. */
async function serveFromRoot(request) {
  const { pathname } = new URL(request.url);
  const target = path.normalize(path.join(ROOT, decodeURIComponent(pathname)));

  if (target !== ROOT && !target.startsWith(ROOT + path.sep)) {
    return new Response('Forbidden', { status: 403 });
  }
  if (target.endsWith('.html')) {
    return serveDocument(target);
  }
  return net.fetch(pathToFileURL(target).toString(), { bypassCustomProtocolHandlers: true });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 860,
    minWidth: 520,
    minHeight: 520,
    backgroundColor: '#05070d',
    show: false,
    autoHideMenuBar: true,
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#00000000', symbolColor: '#7c8699', height: 34 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      backgroundThrottling: false,
    },
  });

  win.once('ready-to-show', () => win.show());
  win.loadURL(ENTRY);

  // Never let the visualizer navigate away or spawn windows.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:$/.test(new URL(url).protocol)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (event, url) => {
    if (url !== ENTRY) event.preventDefault();
  });

  return win;
}

/**
 * Registered once for the whole app rather than per window, so opening a second
 * window cannot throw on a duplicate handler.
 */
function registerIpc() {
  ipcMain.handle('window:toggle-fullscreen', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win) return false;
    win.setFullScreen(!win.isFullScreen());
    return win.isFullScreen();
  });

  // A renderer-side <a download> is unreliable here, so the main process owns
  // the write and hands back the real path for the UI to report.
  ipcMain.handle('capture:save', async (_event, bytes, filename) => {
    const safe = path.basename(String(filename)).replace(/[^\w.-]/g, '_');
    const target = path.join(app.getPath('pictures'), safe);
    await fs.writeFile(target, Buffer.from(bytes));
    return target;
  });
}

function configureSession() {
  const ses = session.defaultSession;

  // Only microphone/system-audio capture is ever needed.
  ses.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'media' || permission === 'display-capture');
  });
  ses.setPermissionCheckHandler((_wc, permission) => permission === 'media' || permission === 'display-capture');

  // getDisplayMedia() -> desktop audio loopback. Video is required to open the
  // stream on Windows; the renderer drops the video track immediately.
  ses.setDisplayMediaRequestHandler(
    (_request, callback) => {
      desktopCapturer
        .getSources({ types: ['screen'], fetchWindowIcons: false })
        .then((sources) => {
          if (!sources.length) return callback({});
          callback({ video: sources[0], audio: 'loopback' });
        })
        .catch(() => callback({}));
    },
    { useSystemPicker: false }
  );
}

app.whenReady().then(() => {
  protocol.handle(SCHEME, serveFromRoot);
  configureSession();
  registerIpc();
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
