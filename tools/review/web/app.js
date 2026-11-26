// Film Lab Review: router + dashboard. Views with three.js load on demand (blueprint.js, viewer.js, timeline.js);
// the image gallery (gallery.js) needs no three.js.
import { h, chip, bar, api, mediaUrl, fmtDur, ago, Live, STATUS_VI, JOB_VI, mergeBuilds } from './lib.js';
import { makeRouter, parseRoute } from './route.js';
import { systemPanels } from './sys.js';
import { loadTags, tagChip, tagChips, groupLabel, groupColor, matches, facets, groupBuilds, parseState,
         stateQuery, own, tagValues, emptySel } from './tags.js';

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
  images: () => import('./gallery.js'),
};

function route() {
  const r = parseRoute(location.hash, Object.keys(ROUTES));
  for (const a of document.querySelectorAll('.tabs a')) a.classList.toggle('on', a.dataset.route === r.key);
  return router.go(ROUTES[r.key], r.args, live).then((v) => {
    if (v && r.error && view.firstElementChild) view.firstElementChild.prepend(h('p', { class: 'empty', text: r.error }));
    return v;
  });
}
window.addEventListener('hashchange', route);
route();

// ------------------------------------------------------------------ dashboard
const FILTERS = [['all', 'Tất cả'], ['active', 'Đang chạy'], ['done', 'Xong'], ['failed', 'Lỗi']];
const ACTIVE = new Set(['queued', 'building', 'rendering']);
const IMAGE_KINDS = new Set(['image', 'concept']);
const EMPTY = 'Chưa có build nào. Chạy một bản dựng có --review hoặc review.py publish-video.';

// Where a card's thumbnail leads: the gallery for image builds, the blueprint for models, else the timeline.
function mainLink(b) {
  const id = encodeURIComponent(b.id);
  if (IMAGE_KINDS.has(b.kind) && b.images) return `#/images/${id}`;
  if (b.last_glb) return `#/build/${id}`;
  if (b.images && !b.renders && b.images === b.steps) return `#/images/${id}`;
  if (b.steps) return `#/build/${id}`;
  return `#/timeline/${id}`;
}

function dashboard(root, _args, live, alive = () => true) {
  // Filters live in the hash (#/?st=active&t=kind:model,episode:q01t03&g=episode): a link shares them.
  const state = parseState(parseRoute(location.hash, Object.keys(ROUTES)).query);
  const cards = new Map();
  const builds = new Map();
  const count = h('span', { class: 'count' });
  const grid = h('div', { class: 'groups' });
  const empty = h('p', { class: 'empty', text: EMPTY });
  const filters = h('div', { class: 'filters', role: 'group', 'aria-label': 'Lọc theo trạng thái' },
    FILTERS.map(([k, label]) => h('button', {
      class: k === state.status ? 'on' : '', dataset: { f: k }, text: label,
      onclick: () => { state.status = k; for (const b of filters.children) b.classList.toggle('on', b.dataset.f === k); changed(); },
    })));
  const groupSel = h('select', { 'aria-label': 'Gom nhóm theo', onchange: () => { state.group = groupSel.value; changed(); } });
  const tagbar = h('div', { class: 'tagbar', role: 'group', 'aria-label': 'Lọc theo chip' });
  const sys = systemPanels(live);
  root.append(h('section', { class: 'dash' }, sys.el,
    h('div', { class: 'dash-head' }, h('h1', { text: 'Bảng theo dõi' }), count, filters,
      h('label', { class: 'groupby' }, 'Gom theo ', groupSel)),
    tagbar, grid, empty));

  function changed() {
    const q = stateQuery(state);
    history.replaceState(null, '', '#/' + (q ? '?' + q : ''));      // shareable; no hashchange, no re-render
    paint();
  }

  function visibleStatus(b) {
    if (state.status === 'active') return ACTIVE.has(b.status);
    if (state.status === 'done') return b.status === 'done';
    if (state.status === 'failed') return b.status === 'failed';
    return true;
  }

  function card(b) {
    const el = h('article', { class: 'card' });
    el.dataset.id = b.id;
    fill(el, b);
    return el;
  }

  function fill(el, b) {
    const name = b.name || b.title;
    const id = encodeURIComponent(b.id);
    const thumb = h('a', { class: 'thumb', href: mainLink(b), 'aria-label': name });
    if (b.thumb) thumb.append(h('img', { src: mediaUrl(b.thumb), alt: '', loading: 'lazy' }));
    else thumb.append(h('div', { class: 'ph', text: b.last_glb ? '3D · GLB' : (b.renders ? 'VIDEO' : (b.images ? 'ẢNH' : 'FILM LAB')) }));
    thumb.append(chip(b.status));
    const steps = b.expected_steps ? `Bước ${b.steps}/${b.expected_steps}` : (b.steps ? `${b.steps} bước` : '');
    const job = b.job;
    const actions = h('nav', { class: 'actions' });
    if (b.last_glb || b.steps > (b.images || 0)) actions.append(h('a', { href: `#/build/${id}`, text: 'Bản vẽ dựng' }));
    if (b.last_glb) actions.append(h('a', { href: `#/model/${id}`, text: 'Xem model' }));
    if (b.images) actions.append(h('a', { href: `#/images/${id}`, text: `Ảnh (${b.images})` }));
    if (b.renders) actions.append(h('a', { href: `#/timeline/${id}`, text: `Video (${b.renders})` }));
    const running = job && job.status === 'running';
    const detail = running ? (job.items ? ` · ảnh ${job.item || 0}/${job.items}` : '') +
      (job.steps ? ` · bước ${job.step || 0}/${job.steps}` : '') : '';
    el.className = `card st-${b.status}`;
    el.replaceChildren(thumb, h('div', { class: 'body' },
      h('h3', { text: name, title: b.title }),
      tagChips(b.tags),
      h('div', { class: 'meta', text: b.id }),
      bar(b.status, b.progress),
      h('div', { class: 'row' }, h('span', { class: 'cur', text: b.current || b.message || STATUS_VI[b.status] }),
        h('span', { class: 'mono', text: `${Math.round(100 * (b.progress || 0))}%` })),
      h('div', { class: 'row small' }, h('span', { text: steps || ago(b.updated) }),
        h('span', { class: 'mono elapsed', title: 'Thời gian chạy' })),
      job ? h('div', { class: `job ${job.status}`, text: `${job.label || job.tool} · ${JOB_VI[job.status] || job.status}` +
        (running && job.progress != null ? ` · ${Math.round(job.progress * 100)}%` : '') + detail +
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

  function toggle(g, v) {
    const s = own(state.sel, g) || (state.sel[g] = new Set());
    if (s.has(v)) s.delete(v); else s.add(v);
    if (!s.size) delete state.sel[g];
    changed();
  }

  function paintBar(list) {
    const kids = [];
    const groups = facets(list);
    for (const [g, vals] of groups) {
      const sel = own(state.sel, g) || new Set();
      kids.push(h('div', { class: 'tg', style: `--c:${groupColor(g)}` }, h('span', { class: 'tgl', text: groupLabel(g) }),
        vals.map(([v, n]) => tagChip(g, v, { button: true, on: sel.has(v), count: n, onclick: () => toggle(g, v) }))));
    }
    // a selected value that no build has (any more) stays visible, so it can be removed
    for (const [g, vals] of Object.entries(state.sel)) {
      for (const v of vals) {
        if (!list.some((b) => tagValues(b.tags, g).includes(v))) {
          kids.push(tagChip(g, v, { button: true, on: true, count: 0, onclick: () => toggle(g, v) }));
        }
      }
    }
    if (Object.keys(state.sel).length) {
      kids.push(h('button', { class: 'clear', type: 'button', text: '✕ Bỏ lọc chip', onclick: () => { state.sel = emptySel(); changed(); } }));
    }
    tagbar.replaceChildren(...kids);
    tagbar.hidden = !kids.length;
    const names = [...new Set(groups.map(([g]) => g).concat(state.group ? [state.group] : []))];
    groupSel.replaceChildren(h('option', { value: '', text: '(không)' }),
      ...names.map((g) => h('option', { value: g, text: groupLabel(g) })));
    groupSel.value = state.group;
  }

  function paint() {
    const list = [...builds.values()].sort((a, b) => b.updated - a.updated);
    const shown = list.filter((b) => visibleStatus(b) && matches(b, state.sel));
    const want = new Set(shown.map((b) => b.id));
    for (const [id, el] of cards) if (!want.has(id)) { el.remove(); cards.delete(id); }
    const cardOf = (b) => { let c = cards.get(b.id); if (!c) { c = card(b); cards.set(b.id, c); } return c; };
    const sections = state.group ? groupBuilds(shown, state.group) : [[undefined, shown]];
    grid.replaceChildren(...sections.map(([v, bs]) => {
      const g = h('div', { class: 'grid' }, bs.map(cardOf));
      if (v === undefined) return g;
      return h('section', { class: 'gsec' },
        h('h2', {}, v === null ? h('span', { class: 'muted', text: `Không có ${groupLabel(state.group).toLowerCase()}` })
          : tagChip(state.group, v), h('span', { class: 'count', text: String(bs.length) })), g);
    }));
    paintBar(list);
    const active = list.filter((b) => ACTIVE.has(b.status)).length;
    count.textContent = `${shown.length === list.length ? list.length : `${shown.length}/${list.length}`} build · ${active} đang chạy`;
    empty.textContent = list.length ? 'Không có build nào khớp bộ lọc.' : EMPTY;
    empty.hidden = shown.length > 0;
  }

  function update(msg) {
    const b = msg.build;
    if (!b) return;
    mergeBuilds(builds, [b]);
    if (builds.get(b.id) !== b) return;               // an older row than the one shown
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
  paint();
  // The snapshot may be older than SSE updates that arrived while it loaded: merge by `updated`, the newer row wins.
  Promise.all([api('builds'), loadTags()]).then(([d]) => {
    if (!alive()) return;
    mergeBuilds(builds, d.builds);
    for (const [id, b] of builds) { const el = cards.get(id); if (el) fill(el, b); }
    paint();
  })
    .catch((e) => { empty.textContent = `Không tải được danh sách: ${e.message}`; empty.hidden = false; });
  return { destroy() { off(); clearInterval(timer); sys.destroy(); } };
}
