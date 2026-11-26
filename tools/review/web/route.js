// Route guard of the review web app: one view at a time, even when the user navigates while a view is still loading.
// Each route renders into its own fresh box; a view that finishes after the user left is destroyed at once, and the
// box it may still write into is already detached. Views get alive() to stop early after their own awaits.
// No DOM import: tests/test_review.py runs this module under node with a fake container.

// '#/build/giot%20demo' -> { key: 'build', args: ['giot demo'], error: null, query: '' }. A segment that is not valid
// percent-encoding ('%E0%A4%A') would throw in decodeURIComponent: the dashboard opens with a message instead of a
// blank page. '#/?t=kind:model&g=episode' -> key '' and query 't=kind:model&g=episode' (the dashboard's filters).
export function parseRoute(hash, names) {
  const full = String(hash || '').replace(/^#\/?/, '');
  const qi = full.indexOf('?');
  const path = qi < 0 ? full : full.slice(0, qi);
  const query = qi < 0 ? '' : full.slice(qi + 1);
  const [name, ...rest] = path.split('/');
  let bad = false;
  const args = rest.map((s) => { try { return decodeURIComponent(s); } catch (e) { bad = true; return s; } })
    .filter(Boolean);
  if (bad) return { key: '', args: [], error: `Đường dẫn không hợp lệ: #/${path}`, query: '' };
  return { key: names.includes(name) ? name : '', args, error: null, query };
}

export function makeRouter(view, makeBox, onError = () => {}) {
  let seq = 0;
  let current = null;
  return {
    get current() { return current; },
    async go(load, args, live) {
      const my = ++seq;
      const alive = () => my === seq;
      try { current?.destroy?.(); } catch (e) { onError(e, null); }
      current = null;
      const box = makeBox();
      view.replaceChildren(box);
      let v = null;
      try {
        const mod = await load();
        if (!alive()) return null;
        v = await mod.default(box, args, live, alive);
      } catch (e) {
        if (alive()) onError(e, box);
        return null;
      }
      if (!alive()) {
        try { v?.destroy?.(); } catch (e) { onError(e, null); }
        return null;
      }
      current = v;
      return v;
    },
  };
}
