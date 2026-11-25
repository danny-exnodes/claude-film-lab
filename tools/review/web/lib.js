// Shared helpers of the review web app: DOM building, formatting, API, live events (Server-Sent Events).

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export const STATUS_VI = {
  queued: 'Chờ', building: 'Đang dựng', rendering: 'Đang render', done: 'Xong', failed: 'Lỗi',
};
export const KIND_VI = { model: 'model', render: 'render', clip: 'clip', demo: 'demo' };
export const JOB_VI = { queued: 'chờ', running: 'đang chạy', done: 'xong', failed: 'lỗi' };

export function chip(status) {
  return h('span', { class: `chip s-${status}`, text: STATUS_VI[status] || status });
}

export function bar(status, progress) {
  const i = h('i');
  i.style.width = `${Math.round(100 * Math.max(0, Math.min(1, progress || 0)))}%`;
  return h('div', { class: `bar s-${status}` }, i);
}

export function mediaUrl(rel) {
  return rel ? '/media/' + rel.split('/').map(encodeURIComponent).join('/') : null;
}

export function fmtDur(sec) {
  if (sec == null || !isFinite(sec)) return '–';
  sec = Math.max(0, sec);
  if (sec < 60) return `${sec < 10 ? sec.toFixed(1) : Math.round(sec)} s`;
  const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
  if (m < 60) return `${m}:${String(s).padStart(2, '0')}`;
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function fmtTC(sec, fps = 24) {
  sec = Math.max(0, sec || 0);
  const f = Math.floor((sec * fps + 1e-6) % fps);
  const s = Math.floor(sec) % 60, m = Math.floor(sec / 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}:${String(f).padStart(2, '0')}`;
}

export function fmtNum(n) {
  return n == null ? '–' : Number(n).toLocaleString('vi-VN');
}

export function ago(t) {
  const d = Date.now() / 1000 - t;
  if (d < 5) return 'vừa xong';
  if (d < 60) return `${Math.round(d)} giây trước`;
  if (d < 3600) return `${Math.round(d / 60)} phút trước`;
  if (d < 86400) return `${Math.round(d / 3600)} giờ trước`;
  return new Date(t * 1000).toLocaleDateString('vi-VN');
}

export async function api(path) {
  const r = await fetch('/api/' + path, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

export function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }

export function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem('review.' + key) || 'null');
    localStorage.setItem('review.' + key, JSON.stringify(value));
  } catch (e) { /* private mode or blocked storage: nothing is remembered */ }
  return null;
}

// One EventSource for the whole app; views subscribe to event names and get {type, build, data}.
export class Live {
  constructor(dot) {
    this.dot = dot;
    this.handlers = new Map();
    this.lastBeat = 0;
    this.connect();
    this.timer = setInterval(() => this.paint(), 3000);
  }
  connect() {
    this.es = new EventSource('/api/stream');
    const names = ['hello', 'heartbeat', 'build', 'step', 'progress', 'render', 'job', 'done', 'fail'];
    for (const name of names) {
      this.es.addEventListener(name, (e) => {
        this.lastBeat = Date.now();
        let msg = {};
        try { msg = JSON.parse(e.data); } catch (err) { return; }
        if (name === 'hello' || name === 'heartbeat') { this.paint(); return; }
        for (const fn of [...(this.handlers.get(name) || []), ...(this.handlers.get('*') || [])]) {
          try { fn(msg, name); } catch (err) { console.error(err); }
        }
      });
    }
    this.es.onopen = () => { this.lastBeat = Date.now(); this.paint(); };
    this.es.onerror = () => this.paint();
  }
  on(name, fn) {
    if (!this.handlers.has(name)) this.handlers.set(name, new Set());
    this.handlers.get(name).add(fn);
    return () => this.handlers.get(name).delete(fn);
  }
  paint() {
    if (!this.dot) return;
    const open = this.es.readyState === 1 && Date.now() - this.lastBeat < 40000;
    this.dot.className = 'live ' + (open ? 'ok' : 'wait');
    this.dot.querySelector('span').textContent = open ? 'trực tiếp' : 'đang nối lại…';
  }
}
