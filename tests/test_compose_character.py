"""The character rigs of method `layers` (tools/compose/cloth.js, pose.js): tests/js/character.test.cjs under
`node --test`, the kit lint, and one check on real pixels in headless Chrome. Free: no API.

Skipped when node (or Chrome) is not installed, so `python3 -m unittest discover -s tests` stays the one test command.
"""
import json, re, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
JS = REPO / "tests" / "js"
KIT = REPO / "tools" / "compose"
NODE = shutil.which("node")
CHROME = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium") if Path(c).exists()), None)
RIGS = ("cloth.js", "pose.js")

# A 600x800 figure (a body block, a striped cloak below it) drawn at stage scale 1; the cloak box is x 150..450,
# y 330..760, rooted on top, at the bottom and on the right. Every frame is compared with the same plate drawn without a rig.
PAGE = """<!doctype html><meta charset=utf-8><body><pre id=o>running</pre><script>__KIT__</script><script>
const busy = setInterval(() => {}, 1);   // keeps Chrome's virtual time from running out while the plates decode
(async () => {
  const C = COMPOSE, W = 600, H = 800, BOX = [150, 330, 450, 760];
  const src = document.createElement('canvas'); src.width = W; src.height = H;
  const s = src.getContext('2d');
  s.fillStyle = '#334'; s.fillRect(200, 60, 200, 300);
  for (let y = 300; y < 700; y += 8) { s.fillStyle = `rgb(${(y * 3) % 255},${(y * 7) % 255},90)`; s.fillRect(220 + ((y / 8) % 3) * 4, y, 160, 8); }
  s.strokeStyle = '#000'; s.lineWidth = 5; s.strokeRect(222, 302, 156, 396);
  const url = src.toDataURL(), place = { x: 0, y: 0, scale: 1, pivot: [0, 0] };
  // A second figure with a translucent cloak (alpha 128) below the body, boxed at SOFT.
  const SOFT = [150, 400, 450, 760];
  s.clearRect(0, 0, W, H);
  s.fillStyle = '#334'; s.fillRect(200, 60, 200, 300);
  s.fillStyle = 'rgba(200,40,40,0.5)'; s.fillRect(220, 380, 160, 320);
  const soft = src.toDataURL(), softRig = (root, amp) => ({ src: soft, anchors: 'none', place, rig: { cloth: [{ box: SOFT, root, amp }] } });
  C.ANCHORS = { x: { cloak: BOX } };
  await C.load({ seed: 7, plates: {
    ref: { src: url, anchors: 'none', place },
    top: { src: url, anchors: 'x', place, rig: { cloth: [{ box: 'cloak', root: 'top', amp: 0.08 }] } },
    bottom: { src: url, anchors: 'x', place, rig: { cloth: [{ box: 'cloak', root: 'bottom', amp: 0.08 }] } },
    right: { src: url, anchors: 'x', place, rig: { cloth: [{ box: 'cloak', root: 'right', amp: 0.08 }] } },
    sref: { src: soft, anchors: 'none', place }, s0top: softRig('top', 0), s0bottom: softRig('bottom', 0),
    stop: softRig('top', 0.08), sbottom: softRig('bottom', 0.08) } });
  const ROOT = { top: [BOX[0], BOX[1], BOX[2], BOX[1] + 3], bottom: [BOX[0], BOX[3] - 3, BOX[2], BOX[3]], right: [BOX[2] - 3, BOX[1], BOX[2], BOX[3]] };
  const cv = document.createElement('canvas'); cv.width = 1920; cv.height = 1080;
  const g = cv.getContext('2d', { willReadFrequently: true });
  const shot = (id, t, o) => {
    g.clearRect(0, 0, 1920, 1080);
    C.stage(g, { W: 1920, H: 1080 }, C.camera(t), (st) => { st.wind = { dir: 0, strength: 1, gust: 1 }; st.plate(id, o); });
    return g.getImageData(0, 0, W, H).data;
  };
  // channel values that differ by more than 1, inside (or outside) the rectangle
  const diff = (a, b, r, inside) => {
    let n = 0;
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      if ((x >= r[0] && x < r[2] && y >= r[1] && y < r[3]) !== inside) continue;
      for (let c = 0; c < 4; c++) if (Math.abs(a[(y * W + x) * 4 + c] - b[(y * W + x) * 4 + c]) > 1) n++;
    }
    return n;
  };
  const ref = shot('ref', 0), res = { warnings: C.report(), still: 0, frames: [] };
  for (const id of Object.keys(ROOT)) {
    res.still += diff(shot(id, 2, { cloth: false }), ref, [0, 0, 0, 0], false);
    for (const t of [0.3, 1.7, 4.2, 9.9]) {
      const f = shot(id, t);
      res.frames.push({ id, t, outside: diff(f, ref, BOX, false), root: diff(f, ref, ROOT[id], true),
                        inside: diff(f, ref, BOX, true), again: diff(f, shot(id, t), [0, 0, 0, 0], false) });
    }
  }
  // The translucent cloak: nothing may be drawn twice. With amp 0 the frame is the plate itself outside the feather
  // zone (there body and cloth overlap on purpose), and a displaced frame keeps alpha 128.
  const sref = shot('sref', 0);
  res.soft = [];
  for (const root of ['top', 'bottom']) {
    const fz = C.plates['s0' + root].cloths[0].feather;
    const zone = root === 'top' ? [0, SOFT[1], W, SOFT[1] + fz] : [0, SOFT[3] - fz, W, SOFT[3]];
    const f = shot('s' + root, 1.7);
    let off = 0;
    for (let y = 440; y < 680; y++) for (let x = 285; x < 315; x++) if (Math.abs(f[(y * W + x) * 4 + 3] - 128) > 1) off++;
    res.soft.push({ root, still: diff(shot('s0' + root, 1.7), sref, zone, false), alpha: off, moved: diff(f, sref, SOFT, true) });
  }
  document.getElementById('o').textContent = 'RESULT ' + JSON.stringify(res);
})().catch((e) => { document.getElementById('o').textContent = 'ERROR ' + e.stack; }).finally(() => clearInterval(busy));
</script>"""


@unittest.skipUnless(NODE, "node is not installed (the kit's JavaScript tests need it)")
class TestCharacterRigsJs(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run([NODE, "--test", str(JS / "character.test.cjs")], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, "node --test failed:\n" + r.stdout[-6000:] + r.stderr[-2000:])


class TestCharacterRigsLint(unittest.TestCase):
    def test_rig_files_are_pure(self):
        sys.path.insert(0, str(KIT))
        try:
            import inline
        finally:
            sys.path.remove(str(KIT))
        for f in RIGS:
            self.assertEqual(inline.lint(f, (KIT / f).read_text(encoding="utf-8")), [])


@unittest.skipUnless(CHROME, "Chrome is not installed (the pixel check needs a real canvas)")
class TestClothPixels(unittest.TestCase):
    def test_cloth_moves_only_inside_its_box(self):
        order = ["core.js", "plates.js", "stage.js", "breath.js", "strip-warp.js", "eyelid.js", *RIGS]
        kit = "\n".join((KIT / f).read_text(encoding="utf-8") for f in order)
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "cloth.html"
            page.write_text(PAGE.replace("__KIT__", kit), encoding="utf-8")
            try:
                r = subprocess.run([CHROME, "--no-sandbox", "--headless=new", "--disable-gpu", "--virtual-time-budget=8000",
                                    "--dump-dom", page.as_uri()], capture_output=True, text=True, timeout=60)
            except (OSError, subprocess.TimeoutExpired) as e:
                self.skipTest(f"Chrome did not run: {e}")
        m = re.search(r'<pre id="o">(RESULT|ERROR) (.*?)</pre>', r.stdout, re.S)
        if not m:
            self.skipTest("Chrome gave no page (headless not available here)")
        self.assertEqual(m.group(1), "RESULT", m.group(2))
        res = json.loads(m.group(2).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"))
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["still"], 0, "cloth: false must give back the plate as it was (cut + feather + crop)")
        for f in res["frames"]:
            at = f"root {f['id']}, t={f['t']}"
            self.assertEqual(f["outside"], 0, f"pixels outside the box changed ({at})")
            self.assertEqual(f["root"], 0, f"the root edge moved ({at})")
            self.assertEqual(f["again"], 0, f"the same frame drawn twice differs ({at})")
            self.assertGreater(f["inside"], 5000, f"the cloth does not move ({at})")
        self.assertEqual(len(res["frames"]), 12)
        self.assertEqual([f["root"] for f in res["soft"]], ["top", "bottom"])
        for f in res["soft"]:
            self.assertEqual(f["still"], 0, f"amp 0 changed a translucent cloth outside the feather zone (root {f['root']})")
            self.assertEqual(f["alpha"], 0, f"a translucent cloth got denser: a pixel was drawn twice (root {f['root']})")
            self.assertGreater(f["moved"], 1000, f"the translucent cloth does not move (root {f['root']})")


if __name__ == "__main__":
    unittest.main()
