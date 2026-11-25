// Film Lab Review: router + dashboard. Views with three.js load on demand (blueprint.js, viewer.js, timeline.js).
import { h, chip, bar, api, mediaUrl, fmtDur, ago, Live, STATUS_VI, JOB_VI } from './lib.js';
import { makeRouter } from './route.js';
import { systemPanels } from './sys.js';

const view = document.getElementById('view');
const live = new Live(document.getElementById('live'));
const router = makeRouter(view, () => h('div', { class: 'route' }), (e, box) => {
  console.error(e);
  if (box) box.replaceChildren(h('p', { class: 'empty', text: `Không mở được trang: ${e.message}` }));
});

const ROUTES = {
  '': () => Promise.resolve({ default: dashboard }),
  build: () => import('./blueprint.js'),
  model: () => import('./viewer.js'),
  timeline: () => import('./timeline.js'),
};

function route() {
  const path = location.hash.replace(/^#\/?/, '');
  const [name, ...rest] = path.split('/');
  const key = name in ROUTES ? name : '';
  for (const a of document.querySelectorAll('.tabs a')) a.classList.toggle('on', a.dataset.route === key);
  return router.go(ROUTES[key], rest.map(decodeURIComponent).filter(Boolean), live);
}
window.addEventListener('hashchange', route);
route();

// ------------------------------------------------------------------ dashboard
const FILTERS = [['all', 'Tất cả'], ['active', 'Đang chạy'], ['done', 'Xong'], ['failed', 'Lỗi']];
const ACTIVE = new Set(['queued', 'building', 'rendering']);

function dashboard(root, _args, live) {
  const cards = new Map();
  let builds = new Map();
  let filter = 'all';
  const count = h('span', { class: 'count' });
  const grid = h('div', { class: 'grid' });
  const empty = h('p', { class: 'empty', text: 'Chưa có build nào. Chạy một bản dựng có --review hoặc review.py publish-video.' });
  const filters = h('div', { class: 'filters', role: 'group', 'aria-label': 'Lọc' },
    FILTERS.map(([k, label]) => h('button', {
      class: k === filter ? 'on' : '', dataset: { f: k }, text: label,
      onclick: (e) => { filter = k; for (const b of filters.children) b.classList.toggle('on', b.dataset.f === k); paint(); },
    })));
  const sys = systemPanels(live);
  root.append(h('section', { class: 'dash' }, sys.el,
    h('div', { class: 'dash-head' }, h('h1', { text: 'Bảng theo dõi' }), count, filters), grid, empty));

  function visible(b) {
    if (filter === 'active') return ACTIVE.has(b.status);
    if (filter === 'done') return b.status === 'done';
    if (filter === 'failed') return b.status === 'failed';
    return true;
  }

  function card(b) {
    const el = h('article', { class: 'card' });
    el.dataset.id = b.id;
    fill(el, b);
    return el;
  }

  function fill(el, b) {
    const thumb = h('a', { class: 'thumb', href: `#/${b.last_glb ? 'build' : 'timeline'}/${encodeURIComponent(b.id)}`,
                           'aria-label': b.title });
    if (b.thumb) thumb.append(h('img', { src: mediaUrl(b.thumb), alt: '', loading: 'lazy' }));
    else thumb.append(h('div', { class: 'ph', text: b.last_glb ? '3D · GLB' : (b.renders ? 'VIDEO' : 'FILM LAB') }));
    thumb.append(chip(b.status), h('span', { class: 'kind', text: b.kind }));
    const steps = b.expected_steps ? `Bước ${b.steps}/${b.expected_steps}` : (b.steps ? `${b.steps} bước` : '');
    const job = b.job;
    const actions = h('nav', { class: 'actions' });
    if (b.last_glb) {
      actions.append(h('a', { href: `#/build/${encodeURIComponent(b.id)}`, text: 'Bản vẽ dựng' }),
                     h('a', { href: `#/model/${encodeURIComponent(b.id)}`, text: 'Xem model' }));
    }
    if (b.renders) actions.append(h('a', { href: `#/timeline/${encodeURIComponent(b.id)}`, text: `Video (${b.renders})` }));
    el.className = `card st-${b.status}`;
    el.replaceChildren(thumb, h('div', { class: 'body' },
      h('h3', { text: b.title }),
      h('div', { class: 'meta', text: [b.project, b.id].filter(Boolean).join(' · ') }),
      bar(b.status, b.progress),
      h('div', { class: 'row' }, h('span', { class: 'cur', text: b.current || b.message || STATUS_VI[b.status] }),
        h('span', { class: 'mono', text: `${Math.round(100 * (b.progress || 0))}%` })),
      h('div', { class: 'row small' }, h('span', { text: steps || ago(b.updated) }),
        h('span', { class: 'mono elapsed', title: 'Thời gian chạy' })),
      job ? h('div', { class: `job ${job.status}`, text: `${job.tool} · ${JOB_VI[job.status] || job.status}` +
        (job.status === 'running' && job.progress != null ? ` · ${Math.round(job.progress * 100)}%` : '') +
        (job.gpu_s ? ` · ${fmtDur(job.gpu_s)} GPU` : '') + (job.message ? ` · ${job.message}` : '') }) : null,
      b.status === 'failed' && b.message ? h('div', { class: 'msg', text: b.message }) : null,
      actions));
    tick(el, b);
  }

  function tick(el, b) {
    const e = el.querySelector('.elapsed');
    if (!e) return;
    const end = b.finished || (ACTIVE.has(b.status) ? Date.now() / 1000 : b.updated);
    e.textContent = '⏱ ' + fmtDur(end - b.started);
  }

  function paint() {
    const list = [...builds.values()].sort((a, b) => b.updated - a.updated);
    const shown = list.filter(visible);
    const want = new Set(shown.map((b) => b.id));
    for (const [id, el] of cards) if (!want.has(id)) { el.remove(); cards.delete(id); }
    shown.forEach((b, i) => {
      let el = cards.get(b.id);
      if (!el) { el = card(b); cards.set(b.id, el); }
      if (grid.children[i] !== el) grid.insertBefore(el, grid.children[i] || null);
    });
    const active = list.filter((b) => ACTIVE.has(b.status)).length;
    count.textContent = `${list.length} build · ${active} đang chạy`;
    empty.hidden = list.length > 0;
  }

  function update(msg) {
    const b = msg.build;
    if (!b) return;
    builds.set(b.id, b);
    const el = cards.get(b.id);
    if (el) {
      fill(el, b);
      el.classList.add('flash');
      setTimeout(() => el.classList.remove('flash'), 700);
    }
    paint();
  }

  const off = live.on('*', update);
  const timer = setInterval(() => { for (const [id, el] of cards) { const b = builds.get(id); if (b && ACTIVE.has(b.status)) tick(el, b); } }, 1000);
  api('builds').then((d) => { builds = new Map(d.builds.map((b) => [b.id, b])); paint(); for (const b of d.builds) { const el = cards.get(b.id); if (el) fill(el, b); } })
    .catch((e) => { empty.textContent = `Không tải được danh sách: ${e.message}`; empty.hidden = false; });
  return { destroy() { off(); clearInterval(timer); sys.destroy(); } };
}
