// Route guard of the review web app: one view at a time, even when the user navigates while a view is still loading.
// Each route renders into its own fresh box; a view that finishes after the user left is destroyed at once, and the
// box it may still write into is already detached. Views get alive() to stop early after their own awaits.
// No DOM import: tests/test_review.py runs this module under node with a fake container.

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
