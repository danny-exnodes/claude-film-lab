"""The COMPOSE kit's own tests (tests/js/compose.test.cjs, atmosphere.test.cjs, preflight.test.cjs) run under `node --test`. Free: no browser, no API.

Skipped when node is not installed, so `python3 -m unittest discover -s tests` stays the one test command.
"""
import shutil, subprocess, unittest
from pathlib import Path

JS = Path(__file__).resolve().parent / "js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed (the kit's JavaScript tests need it)")
class TestComposeKitJs(unittest.TestCase):
    def node(self, name):
        r = subprocess.run([NODE, "--test", str(JS / name)], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, "node --test failed:\n" + r.stdout[-6000:] + r.stderr[-2000:])

    def test_node_suite(self):
        self.node("compose.test.cjs")

    def test_atmosphere_suite(self):
        """smoke.js, fire.js, foliage.js: the code-only atmosphere of the `layers` method."""
        self.node("atmosphere.test.cjs")

    def test_preflight_suite(self):
        """COMPOSE.preflight: key lists, anchors needed by each rig, the dry run (the CLI: test_compose_preflight.py)."""
        self.node("preflight.test.cjs")


if __name__ == "__main__":
    unittest.main()
