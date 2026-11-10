"""The COMPOSE kit's own tests (tests/js/compose.test.cjs) run under `node --test`. Free: no browser, no API.

Skipped when node is not installed, so `python3 -m unittest discover -s tests` stays the one test command.
"""
import shutil, subprocess, unittest
from pathlib import Path

JS = Path(__file__).resolve().parent / "js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not installed (the kit's JavaScript tests need it)")
class TestComposeKitJs(unittest.TestCase):
    def test_node_suite(self):
        r = subprocess.run([NODE, "--test", str(JS / "compose.test.cjs")], capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, "node --test failed:\n" + r.stdout[-6000:] + r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
