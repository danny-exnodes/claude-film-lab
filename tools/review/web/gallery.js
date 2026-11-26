// Image gallery of a build (#/images/<id>): ComfyUI/Seedream image jobs (kind image or concept) and any build whose
// steps carry images. Grid, large view with the step's metadata (prompt, seed, model, steps, s/image, size), compare
// 2-4 images side by side, mark images as chosen. Live: new images appear as their step events arrive; the job's
// progress shows image k/N and sampler step i/n. Chosen marks stay in this browser (the public page is read-only);
// "Tải danh sách chọn" downloads them as JSON for the director/agent. No three.js.
import { h, chip, bar, api, mediaUrl, fmtDur, store } from './lib.js';
import { loadTags, tagChips } from './tags.js';

const ACTIVE = new Set(['queued', 'building', 'rendering']);
const MAX_COMPARE = 4;

// The seed as exact text: the server sends seed_str too (a JSON number above 2**53 is rounded by the browser).
export function seedText(m) {
  if (!m) return null;
  if (typeof m.seed_str === 'string' && /^[0-9]{1,20}$/.test(m.seed_str)) return m.seed_str;
  return m.seed != null ? String(m.seed) : null;
}

// A step's metadata for chosen-<build>.json: seed as the exact string, no seed_str.
export function exportMeta(m) {
  const out = { ...(m || {}) };
  const seed = seedText(m);
  delete out.seed_str;
  if (seed != null) out.seed = seed;
  return out;
}

export function metaRows(s) {
  const m = s.meta || {};
  const rows = [];
  if (m.workflow) rows.push(['Workflow', m.workflow]);
  if (m.model) rows.push(['Model', m.model]);
  if (seedText(m) != null) rows.push(['Seed', seedText(m)]);
  if (m.sampler_steps != null) rows.push(['Số bước', String(m.sampler_steps)]);
  if (m.seconds != null) rows.push(['Thời gian', `${fmtDur(m.seconds)} / ảnh`]);
  if (m.width && m.height) rows.push(['Cỡ', `${m.width}×${m.height}`]);
  if (m.items) rows.push(['Lô', `ảnh ${m.item || '?'}/${m.items}`]);
  return rows;
}

export default async function mount(root, [id], live, alive = () => true) {
  if (!id) { location.hash = '#/'; return {}; }
  let data;
  try { data = await api(`builds/${encodeURIComponent(id)}`); } catch (e) {
    if (alive()) root.append(h('p', { class: 'empty', text: `Không có build "${id}".` }));
    return {};
  }
  await loadTags();
  if (!alive()) return {};
  let build = data.build;
  let steps = data.steps.filter((s) => s.image);
  let total = data.steps.length;                 // every step (with or without an image): a restart shrinks it
  const key = `chosen.${id}`;
  const chosen = new Set(store(key) || []);
  for (const s of steps) if (s.meta && s.meta.chosen) chosen.add(s.image);
  const compare = new Set();
  let onlyChosen = false;
  let open = -1;

  // ---------------------------------------------------------------- DOM
  const headChip = h('span');
  const headBar = h('span');
  const elapsed = h('span', { class: 'stats' });
  const chips = h('span', { class: 'hchips' });
  const prog = h('div', { class: 'gprog' });
  const count = h('span', { class: 'muted' });
  const btnCompare = h('button', { type: 'button', onclick: () => showCompare() });
  const btnOnly = h('button', { type: 'button', text: '★ Chỉ ảnh được chọn', onclick: () => { onlyChosen = !onlyChosen; paintGrid(); } });
  const btnClear = h('button', { type: 'button', text: 'Bỏ chọn so sánh', onclick: () => { compare.clear(); paintGrid(); } });
  const btnExport = h('button', { type: 'button', text: '⤓ Tải danh sách chọn', onclick: exportChosen });
  const grid = h('div', { class: 'gallery' });
  const empty = h('p', { class: 'empty' });
  const box = h('div', { class: 'lightbox', hidden: true, role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Ảnh lớn' });
  const cmp = h('div', { class: 'lightbox compare', hidden: true, role: 'dialog', 'aria-modal': 'true', 'aria-label': 'So sánh ảnh' });
  root.append(h('section', { class: 'gal' },
    h('div', { class: 'bp-head' }, h('a', { href: '#/', text: '← Bảng' }), h('h1', { text: build.name || build.title }),
      headChip, headBar, chips, h('span', { class: 'grow' }), elapsed),
    prog,
    h('div', { class: 'gtools' }, count, btnCompare, btnClear, btnOnly, btnExport),
    grid, empty, box, cmp));

  function shownSteps() { return onlyChosen ? steps.filter((s) => chosen.has(s.image)) : steps; }

  function saveChosen() { store(key, [...chosen]); }

  function toggleChosen(s) {
    if (chosen.has(s.image)) chosen.delete(s.image); else chosen.add(s.image);
    saveChosen();
    paintGrid();
    if (open >= 0) showLarge(open);
  }

  function tile(s, i) {
    const on = chosen.has(s.image);
    const sel = compare.has(s.image);
    const m = s.meta || {};
    const cb = h('input', { type: 'checkbox', 'aria-label': 'So sánh', checked: sel,
      onchange: () => {
        if (cb.checked && compare.size >= MAX_COMPARE) { cb.checked = false; return; }
        if (cb.checked) compare.add(s.image); else compare.delete(s.image);
        paintTools();
        el.classList.toggle('cmp', cb.checked);
      } });
    const el = h('figure', { class: 'gtile' + (on ? ' chosen' : '') + (sel ? ' cmp' : '') },
      h('button', { class: 'gimg', type: 'button', 'aria-label': `Mở ảnh ${s.label}`, onclick: () => showLarge(i) },
        h('img', { src: mediaUrl(s.image), alt: s.label, loading: 'lazy' })),
      h('button', { class: 'star', type: 'button', title: on ? 'Bỏ chọn' : 'Chọn ảnh này', 'aria-pressed': on ? 'true' : 'false',
        text: on ? '★' : '☆', onclick: () => toggleChosen(s) }),
      h('figcaption', {}, h('label', { class: 'cmpl' }, cb, h('span', { text: s.label })),
        h('span', { class: 'mono muted', text: [seedText(m) != null ? `seed ${seedText(m)}` : null,
          m.seconds != null ? fmtDur(m.seconds) : null].filter(Boolean).join(' · ') })));
    return el;
  }

  function paintTools() {
    btnCompare.textContent = `⇄ So sánh (${compare.size})`;
    btnCompare.disabled = compare.size < 2;
    btnClear.disabled = !compare.size;
    btnOnly.classList.toggle('on', onlyChosen);
    btnExport.disabled = !chosen.size;
    count.textContent = `${steps.length} ảnh · ${chosen.size} được chọn`;
  }

  function paintGrid() {
    const list = shownSteps();
    grid.replaceChildren(...list.map((s) => tile(s, steps.indexOf(s))));
    empty.hidden = list.length > 0;
    empty.textContent = steps.length ? 'Chưa chọn ảnh nào.' : (ACTIVE.has(build.status) ? 'Đang chờ ảnh đầu tiên…' : 'Build này chưa có ảnh.');
    paintTools();
  }

  function paintHead() {
    headChip.replaceChildren(chip(build.status));
    headBar.replaceChildren(bar(build.status, build.progress));
    chips.replaceChildren(tagChips(build.tags) || '');
    const end = build.finished || (ACTIVE.has(build.status) ? Date.now() / 1000 : build.updated);
    elapsed.textContent = `⏱ ${fmtDur(end - build.started)}`;
    const j = build.job;
    if (j && j.status === 'running') {
      const parts = [];
      const bars = [];
      if (j.items) {
        parts.push(h('b', { class: 'mono', text: `Ảnh ${j.item || 0}/${j.items}` }));
        bars.push(bar('rendering', (Math.max(0, (j.item || 1) - 1) + (j.steps ? (j.step || 0) / j.steps : 0)) / j.items));
      }
      if (j.steps) {
        parts.push(h('span', { class: 'mono', text: `bước ${j.step || 0}/${j.steps}` }));
        bars.push(bar('building', (j.step || 0) / j.steps));
      }
      if (j.eta != null) parts.push(h('span', { class: 'muted', text: `còn ~${fmtDur(j.eta)}` }));
      const per = steps.map((s) => (s.meta || {}).seconds).filter((x) => x != null);
      if (per.length) parts.push(h('span', { class: 'muted', text: `${fmtDur(per.reduce((a, b) => a + b, 0) / per.length)} / ảnh` }));
      prog.replaceChildren(h('div', { class: 'gpl' }, h('span', { text: j.label || j.tool }), ...parts,
        j.message ? h('span', { class: 'muted', text: j.message }) : null), ...bars);
      prog.hidden = false;
    } else prog.hidden = true;
  }

  // ---------------------------------------------------------------- large view and compare
  function close() {
    box.hidden = true; cmp.hidden = true; open = -1;
    box.replaceChildren(); cmp.replaceChildren();
  }

  function metaList(s) {
    const m = s.meta || {};
    return h('dl', { class: 'kv gmeta' }, h('dt', { text: 'Bước' }), h('dd', { text: s.label }),
      metaRows(s).flatMap(([k, v]) => [h('dt', { text: k }), h('dd', { class: 'mono', text: v })]),
      m.prompt ? [h('dt', { text: 'Prompt' }), h('dd', { class: 'prompt', text: m.prompt })] : null);
  }

  function showLarge(i) {
    const s = steps[i];
    if (!s) return;
    open = i;
    cmp.hidden = true;
    const on = chosen.has(s.image);
    box.replaceChildren(
      h('div', { class: 'lbtools' }, h('span', { class: 'mono', text: `${i + 1}/${steps.length}` }),
        h('button', { type: 'button', text: '←', 'aria-label': 'Ảnh trước', disabled: i <= 0, onclick: () => showLarge(i - 1) }),
        h('button', { type: 'button', text: '→', 'aria-label': 'Ảnh sau', disabled: i >= steps.length - 1, onclick: () => showLarge(i + 1) }),
        h('button', { type: 'button', class: on ? 'on' : '', text: on ? '★ Được chọn' : '☆ Chọn', onclick: () => toggleChosen(s) }),
        h('a', { class: 'btn', href: mediaUrl(s.image), target: '_blank', rel: 'noopener', text: 'Mở file ↗' }),
        h('span', { class: 'grow' }), h('button', { type: 'button', text: '✕', 'aria-label': 'Đóng', onclick: close })),
      h('div', { class: 'lbbody' }, h('img', { src: mediaUrl(s.image), alt: s.label }), metaList(s)));
    box.hidden = false;
  }

  function showCompare() {
    const list = steps.filter((s) => compare.has(s.image));
    if (list.length < 2) return;
    box.hidden = true;
    cmp.replaceChildren(
      h('div', { class: 'lbtools' }, h('b', { text: `So sánh ${list.length} ảnh` }), h('span', { class: 'grow' }),
        h('button', { type: 'button', text: '✕', 'aria-label': 'Đóng', onclick: close })),
      h('div', { class: `cmpgrid n${list.length}` }, list.map((s) => {
        const on = chosen.has(s.image);
        return h('figure', { class: on ? 'chosen' : '' }, h('img', { src: mediaUrl(s.image), alt: s.label }),
          h('figcaption', {}, h('button', { type: 'button', class: 'star', text: on ? '★' : '☆', 'aria-pressed': on ? 'true' : 'false',
            onclick: () => { toggleChosen(s); showCompare(); } }), metaList(s)));
      })));
    cmp.hidden = false;
  }

  function onKey(e) {
    if (box.hidden && cmp.hidden) return;
    if (e.key === 'Escape') close();
    else if (!box.hidden && e.key === 'ArrowLeft' && open > 0) showLarge(open - 1);
    else if (!box.hidden && e.key === 'ArrowRight' && open < steps.length - 1) showLarge(open + 1);
    else if (!box.hidden && (e.key === 'c' || e.key === 'C') && steps[open]) toggleChosen(steps[open]);
    else return;
    e.preventDefault();
  }
  window.addEventListener('keydown', onKey);

  function exportChosen() {
    const out = {
      build: id, title: build.title, exported: new Date().toISOString(),
      chosen: steps.filter((s) => chosen.has(s.image)).map((s) => ({ n: s.n, label: s.label, image: s.image, meta: exportMeta(s.meta) })),
    };
    const blob = new Blob([JSON.stringify(out, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = h('a', { href: url, download: `chosen-${id}-${new Date().toISOString().slice(0, 10)}.json` });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // ---------------------------------------------------------------- live
  async function reload() {
    try {
      const d = await api(`builds/${encodeURIComponent(id)}`);
      if (!alive()) return;
      build = d.build;
      steps = d.steps.filter((s) => s.image);
      total = d.steps.length;
      paintGrid();
      paintHead();
    } catch (e) { console.error(e); }
  }

  const off = live.on('*', (msg, name) => {
    if (!msg.build || msg.build.id !== id) return;
    const restarted = msg.build.steps < total || (name === 'build' && msg.data && msg.data.restart);
    build = msg.build;
    total = Math.max(total, msg.build.steps || 0);
    if (restarted) { reload(); return; }
    if (name === 'step' && msg.data && msg.data.image) {
      const s = msg.data;
      const at = steps.findIndex((x) => x.n === s.n);
      if (at >= 0) steps[at] = s; else { steps.push(s); steps.sort((a, b) => a.n - b.n); }
      if (s.meta && s.meta.chosen) { chosen.add(s.image); saveChosen(); }
      paintGrid();
    }
    paintHead();
  });
  const timer = setInterval(paintHead, 1000);
  paintGrid();
  paintHead();
  return { destroy() { off(); clearInterval(timer); window.removeEventListener('keydown', onKey); } };
}
