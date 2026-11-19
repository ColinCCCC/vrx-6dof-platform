#!/usr/bin/env node
// 把 Archify 生成的图（页面里的 <svg>）导出成 2 倍 PNG，供 README 引用。
// 零依赖：用无头 Chrome 的 DevTools 协议，Node >= 22（内置 WebSocket）。
//
// 用法：node scripts/export_diagram_png.mjs <diagram.html> <out.png>
// 浏览器：优先 $ARCHIFY_CHROME，其次 PATH 里的 chrome/chromium。

import { spawn } from 'node:child_process';
import { access, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';

const VIEWPORT = { width: 1500, height: 1000 };
const SCALE = 2;
// 图例贴着 viewBox 底边，留一点余量，避免缩放取整把最后一行裁掉
const PAD = 16;
const LAUNCH_TIMEOUT_MS = 20000;
const LOAD_TIMEOUT_MS = 20000;

const [htmlArg, outArg] = process.argv.slice(2);
if (!htmlArg || !outArg) {
  console.error('用法：node scripts/export_diagram_png.mjs <diagram.html> <out.png>');
  process.exit(2);
}
const htmlPath = path.resolve(htmlArg);
const outPath = path.resolve(outArg);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch {
    return false;
  }
}

async function resolveChrome() {
  const explicit = process.env.ARCHIFY_CHROME;
  if (explicit) {
    if (!(await exists(explicit))) throw new Error(`ARCHIFY_CHROME 指向的文件不存在：${explicit}`);
    return explicit;
  }
  const names = ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome'];
  const dirs = (process.env.PATH || '').split(path.delimiter).filter(Boolean);
  for (const dir of dirs) {
    for (const name of names) {
      const candidate = path.join(dir, name);
      if (await exists(candidate)) return candidate;
    }
  }
  throw new Error('找不到 Chrome/Chromium：装一个，或设置 ARCHIFY_CHROME=/path/to/chrome');
}

async function waitForDevToolsPort(userDataDir) {
  const portFile = path.join(userDataDir, 'DevToolsActivePort');
  const deadline = Date.now() + LAUNCH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (await exists(portFile)) {
      const text = await readFile(portFile, 'utf8');
      const port = Number(text.split('\n')[0]);
      if (Number.isInteger(port) && port > 0) return port;
    }
    await sleep(100);
  }
  throw new Error('Chrome 启动超时（没写出 DevToolsActivePort）');
}

class Cdp {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data);
      if (message.id && this.pending.has(message.id)) {
        const { resolve, reject } = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) reject(new Error(message.error.message));
        else resolve(message.result);
        return;
      }
      for (const handler of this.listeners.get(message.method) || []) handler(message.params);
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (this.pending.delete(id)) reject(new Error(`${method} 超时`));
      }, LOAD_TIMEOUT_MS);
    });
  }

  once(method) {
    return new Promise((resolve) => {
      const handler = (params) => {
        this.listeners.set(method, (this.listeners.get(method) || []).filter((h) => h !== handler));
        resolve(params);
      };
      this.listeners.set(method, [...(this.listeners.get(method) || []), handler]);
    });
  }
}

function connect(url) {
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    socket.addEventListener('open', () => resolve(new Cdp(socket)));
    socket.addEventListener('error', () => reject(new Error('DevTools WebSocket 连接失败')));
  });
}

const chrome = await resolveChrome();
const userDataDir = await mkdtemp(path.join(tmpdir(), 'archify-png-'));
const args = [
  '--headless=new',
  '--disable-gpu',
  '--hide-scrollbars',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-background-networking',
  '--remote-debugging-port=0',
  `--user-data-dir=${userDataDir}`,
  'about:blank',
];
if (process.getuid?.() === 0 || process.env.ARCHIFY_CHROME_NO_SANDBOX === '1') args.unshift('--no-sandbox');

const child = spawn(chrome, args, { stdio: ['ignore', 'ignore', 'pipe'] });
let stderr = '';
child.stderr.setEncoding('utf8');
child.stderr.on('data', (chunk) => {
  stderr = `${stderr}${chunk}`.slice(-4000);
});

let browser;
try {
  const port = await waitForDevToolsPort(userDataDir);
  const res = await fetch(`http://127.0.0.1:${port}/json/list`);
  const targets = await res.json();
  const page = targets.find((t) => t.type === 'page');
  if (!page) throw new Error('Chrome 没有可用的 page target');
  browser = await connect(page.webSocketDebuggerUrl);

  await browser.send('Page.enable');
  await browser.send('Emulation.setDeviceMetricsOverride', {
    width: VIEWPORT.width,
    height: VIEWPORT.height,
    deviceScaleFactor: SCALE,
    mobile: false,
  });
  const loaded = browser.once('Page.loadEventFired');
  await browser.send('Page.navigate', { url: `file://${htmlPath}` });
  await Promise.race([loaded, sleep(LOAD_TIMEOUT_MS)]);
  // 等字体和布局稳定，避免截到半渲染的图
  await sleep(2500);
  // 关掉阅读器浮层（工具栏、放大缩小、路径探针等），只留图本身
  await browser.send('Runtime.evaluate', {
    expression: `(() => {
      const style = document.createElement('style');
      style.textContent = '.no-print { display: none !important; }';
      document.head.append(style);
    })()`,
  });
  await sleep(600);

  const { result } = await browser.send('Runtime.evaluate', {
    expression: `(() => {
      const svg = document.querySelector('main svg, #diagram svg, svg');
      if (!svg) return null;
      // 取宿主容器而不是 svg 本身：图例可能溢出 svg 的视口，容器盒才包含它
      const host = svg.closest('.diagram-container') || svg.parentElement || svg;
      const r = host.getBoundingClientRect();
      return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height };
    })()`,
    returnByValue: true,
  });
  if (!result.value) throw new Error('页面里找不到 <svg>，确认这是 Archify 生成的图');
  const { x, y, width, height } = result.value;
  const pad = PAD;
  const clip = {
    x: Math.max(0, x - pad),
    y: Math.max(0, y - pad),
    width: width + pad * 2,
    height: height + pad * 2,
    scale: 1,
  };

  const shot = await browser.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip,
  });
  await writeFile(outPath, Buffer.from(shot.data, 'base64'));
  console.log(`导出 ${outPath}（${Math.round(clip.width)}×${Math.round(clip.height)} @${SCALE}x）`);
} catch (error) {
  if (stderr.trim()) console.error(stderr.trim().split('\n').slice(-3).join('\n'));
  console.error(`导出失败：${error.message}`);
  process.exitCode = 1;
} finally {
  try {
    await browser?.send('Browser.close');
  } catch {
    /* 忽略关闭失败 */
  }
  child.kill('SIGKILL');
  await rm(userDataDir, { recursive: true, force: true });
}
