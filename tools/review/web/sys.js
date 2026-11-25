// Dashboard panels "Máy" (machine metrics) and "ComfyUI" (generation progress), fed by tools/review/monitor.py through
// /api/metrics, /api/comfy and the SSE events metrics/comfy. Charts are plain canvas (no library).
import { h, api, fmtDur, ago, store } from './lib.js';

const GIB = 2 ** 30;
const LOW_DISK = 10 * GIB;          // a drive with less free space is red (C: is the owner's small system drive)
const TIGHT_DISK = 20 * GIB;
const STALE = 10;                   // seconds without a sample: the monitor is shown as offline
const WINDOWS = [['10m', '10 phút', 600], ['24h', '24 giờ', 86400]];

const pct = (a, b) => (a != null && b ? (100 * a) / b : null);
const gb = (b) => (b == null ? '–' : (b / GIB >= 100 ? Math.round(b / GIB) : (b / GIB).toFixed(1)));
const num = (v, d = 0) => (v == null ? '–' : Number(v).toFixed(d));

// A full sample of monitor.py (or an already flat chart row) -> chart row.
export function flat(s) {
  if (!s || !('gpus' in s)) return s;
  const g = (s.gpus && s.gpus[0]) || {};
  return { t: s.t, cpu: s.cpu, ram_used: s.ram_used, ram_total: s.ram_total, gpu_util: g.util, vram_used: g.mem_used,
           vram_total: g.mem_total, gpu_temp: g.temp, gpu_power: g.power };
}

// level: '' | 'warm' | 'hot'
const TILES = [
  { key: 'cpu', label: 'CPU', color: '#5ef2ff', min: 0, max: 100, v: (r) => r.cpu,
    show: (s) => [num(s.cpu), '%', ''], level: (s) => (s.cpu > 95 ? 'warm' : '') },
  { key: 'ram', label: 'RAM', color: '#b69cff', min: 0, max: 100, v: (r) => pct(r.ram_used, r.ram_total),
    show: (s) => [gb(s.ram_used), 'GB', `/ ${gb(s.ram_total)} GB`],
    level: (s) => { const p = pct(s.ram_used, s.ram_total); return p > 95 ? 'hot' : p > 85 ? 'warm' : ''; } },
  { key: 'gpu', label: 'GPU', color: '#3ddc97', min: 0, max: 100, v: (r) => r.gpu_util,
    show: (s) => [num(gpu(s).util), '%', gpu(s).name || ''], level: () => '' },
  { key: 'vram', label: 'VRAM', color: '#7aa2ff', min: 0, max: 100, limit: 90, v: (r) => pct(r.vram_used, r.vram_total),
    show: (s) => { const g = gpu(s); return [gb(g.mem_used), 'GB', `/ ${gb(g.mem_total)} GB · ${num(pct(g.mem_used, g.mem_total))}%`]; },
    level: (s) => { const p = pct(gpu(s).mem_used, gpu(s).mem_total); return p > 90 ? 'hot' : p > 80 ? 'warm' : ''; } },
  { key: 'temp', label: 'Nhiệt độ GPU', color: '#ff9f6b', min: 20, max: 100, limit: 83, v: (r) => r.gpu_temp,
    show: (s) => [num(gpu(s).temp), '°C', 'ngưỡng 83 °C'],
    level: (s) => { const t = gpu(s).temp; return t > 83 ? 'hot' : t > 76 ? 'warm' : ''; } },
  { key: 'power', label: 'Công suất GPU', color: '#ffd36b', min: 0, max: null, v: (r) => r.gpu_power,
    show: (s) => [num(gpu(s).power), 'W', ''], level: () => '' },
];
function gpu(s) { return (s && s.gpus && s.gpus[0]) || {}; }

// Area chart of rows (t ascending) on a canvas; gaps longer than 3 intervals break the line.
export function drawChart(canvas, rows, value, { min = 0, max = null, color = '#5ef2ff', limit = null, t0, t1, gap = 6 }) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  if (!w || !hgt) return;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(hgt * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(hgt * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hgt);
  const pts = rows.map((r) => [r.t, value(r)]).filter((p) => p[1] != null && isFinite(p[1]));
  let top = max;
  if (top == null) top = Math.max(1, ...pts.map((p) => p[1])) * 1.15;
  const X = (t) => ((t - t0) / Math.max(1, t1 - t0)) * w;
  const Y = (v) => hgt - 1 - ((Math.min(top, Math.max(min, v)) - min) / Math.max(1e-9, top - min)) * (hgt - 3);
  ctx.strokeStyle = 'rgba(141,154,178,.14)';
  ctx.lineWidth = 1;
  for (const f of [0.25, 0.5, 0.75]) { const y = Math.round(hgt * f) + 0.5; ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
  if (limit != null && limit < top) {
    ctx.strokeStyle = 'rgba(255,107,122,.75)';
    ctx.setLineDash([4, 3]);
    ctx.beginPath(); ctx.moveTo(0, Y(limit) + 0.5); ctx.lineTo(w, Y(limit) + 0.5); ctx.stroke();
    ctx.setLineDash([]);
  }
  const runs = [];
  let run = [];
  for (let i = 0; i < pts.length; i += 1) {
    if (run.length && pts[i][0] - pts[i - 1][0] > gap) { runs.push(run); run = []; }
    run.push(pts[i]);
  }
  if (run.length) runs.push(run);
  const grad = ctx.createLinearGradient(0, 0, 0, hgt);
  grad.addColorStop(0, color + '55');
  grad.addColorStop(1, color + '05');
  for (const r of runs) {
    ctx.beginPath();
    r.forEach(([t, v], i) => (i ? ctx.lineTo(X(t), Y(v)) : ctx.moveTo(X(t), Y(v))));
    if (r.length === 1) ctx.lineTo(X(r[0][0]) + 2, Y(r[0][1]));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.lineTo(X(r[r.length - 1][0]) + (r.length === 1 ? 2 : 0), hgt);
    ctx.lineTo(X(r[0][0]), hgt);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();
  }
}

export function systemPanels(live) {
  let win = store('sysWindow') === '24h' ? '24h' : '10m';
  let rows10 = [];
  let rows24 = [];
  let latest = null;
  let lastT = 0;            // server time of the newest sample (seconds)
  let skew = 0;             // server clock - browser clock
  let comfy = null;
  let comfyAt = 0;

  // ---------------------------------------------------------------- machine
  const tiles = TILES.map((d) => {
    const val = h('b', { class: 'mono' });
    const unit = h('small');
    const sub = h('span', { class: 'sub mono' });
    const cv = h('canvas', { 'aria-hidden': 'true' });
    const el = h('div', { class: 'tile', style: `--c:${d.color}` },
      h('div', { class: 'tl' }, d.label), h('div', { class: 'tv' }, val, unit), sub, cv);
    return { d, el, val, unit, sub, cv };
  });
  const age = h('span', { class: 'age' });
  const winBtns = h('div', { class: 'seg', role: 'group', 'aria-label': 'Khoảng thời gian' },
    WINDOWS.map(([k, label]) => h('button', { class: k === win ? 'on' : '', dataset: { w: k }, text: label,
      onclick: () => { win = k; store('sysWindow', k); for (const b of winBtns.children) b.classList.toggle('on', b.dataset.w === k); load(); } })));
  const disks = h('div', { class: 'disks' });
  const jobs = h('div', { class: 'jobs' });
  const machine = h('article', { class: 'syscard machine', 'aria-label': 'Máy chủ lab' },
    h('header', {}, h('h2', { text: 'Máy' }), age, winBtns),
    h('div', { class: 'tiles' }, tiles.map((t) => t.el)), disks, jobs);

  function paintMachine() {
    const s = latest || {};
    for (const t of tiles) {
      const [v, u, sub] = t.d.show(s);
      t.val.textContent = latest ? v : '–';
      t.unit.textContent = latest ? u : '';
      t.sub.textContent = latest ? sub : '';
      t.el.className = 'tile ' + (latest ? t.d.level(s) : '');
    }
    disks.replaceChildren(...(s.disks || []).map((d) => {
      const used = d.total ? 1 - d.free / d.total : 0;
      const lvl = d.free < LOW_DISK ? 'hot' : d.free < TIGHT_DISK ? 'warm' : '';
      const i = h('i');
      i.style.width = `${Math.round(100 * used)}%`;
      return h('div', { class: `disk ${lvl}` }, h('b', { class: 'mono', text: d.name }),
        h('div', { class: 'dbar' }, i),
        h('span', { class: 'mono', text: `${gb(d.free)} GB trống / ${gb(d.total)} GB` + (lvl === 'hot' ? ' · sắp đầy' : '') }));
    }));
    const procs = s.procs || [];
    jobs.replaceChildren(h('span', { class: 'muted', text: 'Job nặng:' }),
      ...(procs.length ? procs.map((p) => h('span', { class: 'pill', text: p.count > 1 ? `${p.name} ×${p.count}` : p.name }))
        : [h('span', { class: 'muted', text: latest ? 'không có' : '–' })]));
    paintCharts();
    paintAge();
  }

  function paintCharts() {
    const now = Date.now() / 1000 + skew;
    const [, , span] = WINDOWS.find((w) => w[0] === win);
    const rows = win === '10m' ? rows10 : rows24;
    for (const t of tiles) {
      drawChart(t.cv, rows, t.d.v, { min: t.d.min, max: t.d.max, color: t.d.color, limit: t.d.limit,
                                     t0: now - span, t1: now, gap: win === '10m' ? 7 : 190 });
    }
  }

  function paintAge() {
    const a = lastT ? Date.now() / 1000 + skew - lastT : null;
    const off = a == null || a > STALE;
    machine.classList.toggle('offline', off);
    age.textContent = a == null ? 'chưa có số liệu (monitor.py chưa chạy)' : off ? `mất tín hiệu ${fmtDur(a)}` : 'trực tiếp';
    age.className = 'age ' + (off ? 'off' : 'ok');
    comfyCard.classList.toggle('offline', !comfyAt || Date.now() / 1000 + skew - comfyAt > STALE);
  }

  async function load() {
    try {
      const d = await api(`metrics?window=${win}`);
      skew = d.now - Date.now() / 1000;
      if (d.latest) { latest = d.latest; lastT = d.latest.t; }
      if (win === '10m') rows10 = d.samples; else rows24 = d.samples;
      paintMachine();
    } catch (e) { age.textContent = `không tải được số liệu (${e.message})`; }
  }

  // ---------------------------------------------------------------- ComfyUI
  const cChip = h('span', { class: 'chip s-queued', text: '…' });
  const cQueue = h('span', { class: 'age' });
  const cBody = h('div', { class: 'cbody' });
  const cHist = h('div', { class: 'chist' });
  const comfyCard = h('article', { class: 'syscard comfy', 'aria-label': 'ComfyUI' },
    h('header', {}, h('h2', { text: 'ComfyUI' }), cChip, cQueue), cBody, cHist);

  function buildLink(b) {
    return b ? h('a', { href: `#/timeline/${encodeURIComponent(b.id)}`, text: b.title || b.id }) : null;
  }

  function paintComfy() {
    const c = comfy;
    const fresh = comfyAt && Date.now() / 1000 + skew - comfyAt <= STALE;
    if (!c) {
      cChip.className = 'chip s-queued'; cChip.textContent = 'chưa rõ';
      cQueue.textContent = '';
      cBody.replaceChildren(h('p', { class: 'muted', text: 'Chưa có số liệu (monitor.py chưa chạy).' }));
      cHist.replaceChildren();
      return;
    }
    cChip.className = `chip ${!fresh ? 's-failed' : c.up ? (c.running ? 's-rendering' : 's-done') : 's-queued'}`;
    cChip.textContent = !fresh ? 'mất tín hiệu' : c.up ? (c.running ? 'đang chạy' : 'bật · rảnh') : 'tắt';
    cQueue.textContent = c.up ? `đang chạy ${c.running ?? 0} · chờ ${c.pending ?? 0}` : '';
    const cur = c.current;
    const kids = [];
    if (cur) {
      const i = h('i');
      i.style.width = `${Math.max(0, Math.min(100, cur.pct || 0))}%`;
      kids.push(
        c.build ? h('div', { class: 'cbuild' }, 'Build: ', buildLink(c.build)) : null,
        h('div', { class: 'bar s-rendering big' }, i),
        h('div', { class: 'cstep' }, h('b', { class: 'mono', text: `Bước ${cur.step}/${cur.total}` }),
          cur.bar > 1 ? h('span', { class: 'muted', text: ` · lượt ${cur.bar}` }) : null,
          h('span', { class: 'mono pctv', text: `${num(cur.pct)}%` })),
        h('dl', { class: 'kv ckv' },
          h('dt', { text: 's/bước' }), h('dd', { text: cur.s_per_step != null ? `${num(cur.s_per_step, cur.s_per_step < 10 ? 2 : 1)} s` : '–' }),
          h('dt', { text: 'Đã chạy' }), h('dd', { text: fmtDur(cur.elapsed) }),
          h('dt', { text: 'Còn lại' }), h('dd', { text: cur.eta != null ? `~${fmtDur(cur.eta)}` : '–' }),
          h('dt', { text: 'Cả job' }), h('dd', { text: fmtDur(cur.job_elapsed) })));
    } else if (c.up && c.running) {
      kids.push(c.build ? h('div', { class: 'cbuild' }, 'Build: ', buildLink(c.build)) : null,
        h('p', { class: 'muted', text: 'Đang chạy, chưa có bước nào (đang nạp model?).' }));
    } else {
      kids.push(h('p', { class: 'muted', text: c.up ? 'Không có job đang chạy.' : 'Server ComfyUI không chạy.' }));
    }
    if (!c.log) kids.push(h('p', { class: 'note', text: 'Không thấy file log ComfyUI: tiến độ từng bước cần monitor.py --comfy-log.' }));
    cBody.replaceChildren(...kids.filter(Boolean));
    const hist = [...(c.history || [])].reverse();
    cHist.replaceChildren(hist.length ? h('table', { class: 'htab' },
      h('thead', {}, h('tr', {}, ['Lúc', 'Thời gian', 'Bước', 's/bước', ''].map((x) => h('th', { text: x })))),
      h('tbody', {}, hist.map((r) => h('tr', { class: r.status !== 'ok' ? 'bad' : '' },
        h('td', { text: r.t ? ago(r.t) : '–' }),
        h('td', { class: 'mono', text: fmtDur(r.duration) }),
        h('td', { class: 'mono', text: r.steps != null ? String(r.steps) : '–' }),
        h('td', { class: 'mono', text: r.s_per_step != null ? num(r.s_per_step, r.s_per_step < 10 ? 2 : 1) : '–' }),
        h('td', {}, r.status !== 'ok' ? (r.status === 'failed' ? 'lỗi' : 'dừng') : '', r.build ? buildLink(r.build) : null)))))
      : h('p', { class: 'muted small', text: 'Chưa có lượt tạo nào trong log.' }));
  }

  async function loadComfy() {
    try {
      const d = await api('comfy');
      if (d.comfy) { comfy = d.comfy; comfyAt = d.comfy.t; }
      paintComfy();
    } catch (e) { /* the next SSE event fills it */ }
  }

  // ---------------------------------------------------------------- live
  const offM = live.on('metrics', (msg) => {
    const s = msg.sample;
    if (!s) return;
    latest = s;
    lastT = s.t;
    skew = s.t - Date.now() / 1000;
    rows10.push(flat(s));
    const cut = s.t - 600;
    while (rows10.length && rows10[0].t < cut) rows10.shift();
    paintMachine();
  });
  const offC = live.on('comfy', (msg) => {
    if (!msg.comfy) return;
    comfy = msg.comfy;
    comfyAt = msg.comfy.t;
    paintComfy();
  });
  const ro = new ResizeObserver(() => paintCharts());
  for (const t of tiles) ro.observe(t.cv);
  const tick = setInterval(() => { paintAge(); if (comfy) paintComfy(); }, 1000);
  const refresh = setInterval(() => { if (win === '24h') load(); }, 60000);

  paintMachine();
  paintComfy();
  load();
  if (win === '24h') api('metrics?window=10m').then((d) => { rows10 = d.samples; }).catch(() => {});
  loadComfy();

  return {
    el: h('section', { class: 'sys' }, machine, comfyCard),
    destroy() { offM(); offC(); ro.disconnect(); clearInterval(tick); clearInterval(refresh); },
  };
}
