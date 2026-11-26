// Tag chips of the review web app: the registry (/api/tags = tools/review/tags.json + <media>/_tags.json), coloured
// chips, the dashboard's filter (AND across groups, OR within a group) and its state in the URL hash.
// Only pure functions run at import time: tests/test_review_monitor.py imports this module under node.
import { h, api } from './lib.js';

let REG = { groups: {} };
let loading = null;

export function loadTags() {
  if (!loading) {
    loading = api('tags').then((d) => { if (d && d.groups) REG = d; return REG; }).catch(() => REG);
  }
  return loading;
}

export function setRegistry(reg) { REG = reg && reg.groups ? reg : { groups: {} }; loading = Promise.resolve(REG); }
export function registry() { return REG; }

const SLUG = /^[a-z0-9][a-z0-9._-]{0,47}$/;
const GROUP = /^[a-z][a-z0-9_]{0,23}$/;

export function groupLabel(group, reg = REG) {
  return (reg.groups[group] && reg.groups[group].label) || group;
}

export function groupColor(group, reg = REG) {
  const c = reg.groups[group] && reg.groups[group].color;
  return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : '#8d9ab2';
}

// 'q01t03' -> 'Q1·T3' (labels_re), 'phuong-hoang' -> registry label or 'Phuong hoang'.
export function tagLabel(group, value, reg = REG) {
  const g = reg.groups[group];
  if (g && g.values && g.values[value]) return g.values[value];
  for (const [re, rep] of (g && g.labels_re) || []) {
    try { const r = new RegExp(re); if (r.test(value)) return value.replace(r, rep); } catch (e) { /* a bad pattern */ }
  }
  const s = String(value).replace(/[-_]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Groups in registry order, then unknown groups alphabetically.
export function orderGroups(groups, reg = REG) {
  const known = Object.keys(reg.groups);
  return [...new Set(groups)].sort((a, b) => {
    const ia = known.indexOf(a), ib = known.indexOf(b);
    if (ia !== ib) return (ia < 0 ? 1e6 : ia) - (ib < 0 ? 1e6 : ib);
    return a < b ? -1 : a > b ? 1 : 0;
  });
}

// [[group, value], ...] of a build's tags in display order.
export function tagPairs(tags, reg = REG, skip = []) {
  const out = [];
  for (const g of orderGroups(Object.keys(tags || {}), reg)) {
    if (skip.includes(g)) continue;
    for (const v of tags[g] || []) out.push([g, v]);
  }
  return out;
}

export function tagChip(group, value, { button = false, on = false, count = null, onclick = null } = {}) {
  const attrs = {
    class: 'tag' + (on ? ' on' : ''), style: `--c:${groupColor(group)}`, title: `${groupLabel(group)}: ${value}`,
    dataset: { g: group, v: value },
  };
  if (button) { attrs.type = 'button'; attrs['aria-pressed'] = on ? 'true' : 'false'; attrs.onclick = onclick; }
  return h(button ? 'button' : 'span', attrs, tagLabel(group, value),
    count != null ? h('small', { text: String(count) }) : null);
}

export function tagChips(tags, { skip = [], cls = 'tags' } = {}) {
  const pairs = tagPairs(tags, REG, skip);
  return pairs.length ? h('div', { class: cls }, pairs.map(([g, v]) => tagChip(g, v))) : null;
}

// ------------------------------------------------------------------ filter (pure)
// sel: {group: Set(values)}. A build matches when, for every group with a selection, it has one of the selected
// values (AND across groups, OR within a group: "Q1·T3 or Q1·T4, and Blender").
export function matches(build, sel) {
  for (const [g, vals] of Object.entries(sel || {})) {
    if (!vals || !vals.size) continue;
    const have = ((build && build.tags) || {})[g] || [];
    if (!have.some((v) => vals.has(v))) return false;
  }
  return true;
}

// Every (group, value) of the builds with its count, groups in registry order: the filter bar's chips.
export function facets(builds, reg = REG) {
  const counts = new Map();
  for (const b of builds) {
    for (const [g, vals] of Object.entries(b.tags || {})) {
      if (!counts.has(g)) counts.set(g, new Map());
      for (const v of vals || []) counts.get(g).set(v, (counts.get(g).get(v) || 0) + 1);
    }
  }
  return orderGroups([...counts.keys()], reg).map((g) => [g, [...counts.get(g).entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))]);
}

// Builds by the first value of `group` (a build without it goes last, under null). -> [[value|null, [builds]]].
export function groupBuilds(builds, group) {
  const by = new Map();
  for (const b of builds) {
    const v = (((b.tags || {})[group]) || [])[0] || null;
    if (!by.has(v)) by.set(v, []);
    by.get(v).push(b);
  }
  return [...by.entries()].sort((a, b) => (a[0] === null) - (b[0] === null) || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
}

// Dashboard state <-> hash query: 'st=active&t=kind:model,episode:q01t03&g=episode'.
const STATUSES = ['all', 'active', 'done', 'failed'];
export function parseState(query) {
  const st = { status: 'all', sel: {}, group: '' };
  for (const part of String(query || '').split('&')) {
    const i = part.indexOf('=');
    if (i < 0) continue;
    let k, v;
    try { k = decodeURIComponent(part.slice(0, i)); v = decodeURIComponent(part.slice(i + 1)); } catch (e) { continue; }
    if (k === 'st' && STATUSES.includes(v)) st.status = v;
    else if (k === 'g' && GROUP.test(v)) st.group = v;
    else if (k === 't') {
      for (const pair of v.split(',')) {
        const [g, val] = pair.split(':');
        if (GROUP.test(g || '') && SLUG.test(val || '')) (st.sel[g] = st.sel[g] || new Set()).add(val);
      }
    }
  }
  return st;
}

export function stateQuery({ status = 'all', sel = {}, group = '' } = {}) {
  const parts = [];
  if (status && status !== 'all') parts.push(`st=${status}`);
  const t = [];
  for (const g of Object.keys(sel).sort()) for (const v of [...sel[g]].sort()) t.push(`${g}:${v}`);
  if (t.length) parts.push(`t=${t.join(',')}`);
  if (group) parts.push(`g=${group}`);
  return parts.join('&');
}
