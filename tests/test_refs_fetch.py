"""tools/refs_fetch.py and the retry/backoff core of tools/netfetch.py, against a local fake Commons server.
Never touches the real network: the module's API URL is pointed at 127.0.0.1."""
import io, json, os, tempfile, threading, unittest, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import helpers

refs = helpers.load("refs_fetch.py")
netfetch = refs.netfetch

try:
    from PIL import Image
except ImportError:            # tools/ci.sh --install brings Pillow
    Image = None


def png_bytes(w, h, fmt="PNG", color=(120, 30, 20)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format=fmt)
    return buf.getvalue()


def meta(lic="CC BY-SA 4.0", artist='<a href="//x">Some <b>Painter</b></a>', nonfree=None):
    m = {"LicenseShortName": {"value": lic}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
         "Artist": {"value": artist}, "Credit": {"value": "Own work"}, "DateTimeOriginal": {"value": "1679"},
         "ImageDescription": {"value": "<p>Wintry &amp; misty mountains</p>"}}
    if nonfree is not None:
        m["NonFree"] = {"value": nonfree}
    return m


class FakeCommons:
    """/w/api.php answers imageinfo for the files in self.files; /img/<name> serves their bytes.
    self.fail_api = [(status, headers), ...] answers the next API calls with those errors first."""

    def __init__(self):
        self.files, self.fail_api, self.calls, self.agents = {}, [], [], []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = urllib.parse.parse_qs(u.query)
                fake.calls.append(self.path)
                fake.agents.append(self.headers.get("User-Agent"))
                if u.path == "/w/api.php":
                    if fake.fail_api:
                        status, hdrs = fake.fail_api.pop(0)
                        self.send_response(status)
                        for k, v in hdrs.items():
                            self.send_header(k, v)
                        self.end_headers()
                        return
                    if "generator" in q:
                        pages = [fake.page(t, i) for i, t in enumerate(sorted(fake.files))]
                    else:
                        pages = [fake.page(q["titles"][0], 0)]
                    return self.reply(json.dumps({"query": {"pages": pages}}).encode(), "application/json")
                if u.path.startswith("/img/"):
                    name = urllib.parse.unquote(u.path[5:])
                    for f in fake.files.values():
                        if f["name"] == name:
                            return self.reply(f["data"], "image/" + f["fmt"].lower())
                self.send_response(404)
                self.end_headers()

            def reply(self, body, ctype):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def add(self, title, w, h, fmt="JPEG", **kw):
        name = title.split(":", 1)[1].replace(" ", "_")
        self.files[title] = {"name": name, "w": w, "h": h, "fmt": fmt, "data": png_bytes(w, h, fmt), "meta": meta(**kw)}

    def page(self, title, index):
        f = self.files.get(title)
        if not f:
            return {"title": title, "missing": True}
        return {"title": title, "index": index, "imageinfo": [{
            "url": f"{self.base}/img/{f['name']}", "width": f["w"], "height": f["h"],
            "thumburl": f"{self.base}/img/{f['name']}", "extmetadata": f["meta"]}]}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class TestPure(unittest.TestCase):
    def test_licence_parsing(self):
        free = ["CC BY-SA 4.0", "CC BY 2.0", "Public domain", "PD-US", "PDM", "CC0", "GFDL", "No restrictions",
                "Attribution", "CC-BY-SA-3.0"]
        nonfree = ["CC BY-NC-SA 4.0", "CC BY-ND 2.0", "Fair use", "All rights reserved", "", "Some custom terms"]
        for lic in free:
            self.assertTrue(refs.licence_of({"LicenseShortName": {"value": lic}})[2], lic)
        for lic in nonfree:
            self.assertFalse(refs.licence_of({"LicenseShortName": {"value": lic}})[2], lic)
        self.assertFalse(refs.licence_of({"LicenseShortName": {"value": "CC BY 4.0"}, "NonFree": {"value": "true"}})[2])
        self.assertEqual(refs.licence_of({"UsageTerms": {"value": "Public domain"}})[:1], ("Public domain",))
        self.assertEqual(refs.licence_of({})[0], "unknown")

    def test_parse_ref(self):
        P = refs.parse_ref
        self.assertEqual(P("File:Gong_Xian_-_Landscape.jpg"), ("File:Gong Xian - Landscape.jpg", None))
        self.assertEqual(P("https://commons.wikimedia.org/wiki/File:Gong_Xian_-_Landscape.jpg"),
                         ("File:Gong Xian - Landscape.jpg", None))
        self.assertEqual(P("https://commons.wikimedia.org/wiki/File:%E5%85%95.pdf?page=26"), ("File:兕.pdf", 26))
        self.assertEqual(P("https://commons.wikimedia.org/w/index.php?title=File:A_b.png&oldid=1"), ("File:A b.png", None))
        self.assertEqual(P("https://upload.wikimedia.org/wikipedia/commons/a/ab/A_b.jpg"), ("File:A b.jpg", None))
        self.assertEqual(P("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/A_b.jpg/800px-A_b.jpg"),
                         ("File:A b.jpg", None))
        for bad in ("https://example.com/File:A.jpg", "A.jpg", "https://commons.wikimedia.org/wiki/Category:X"):
            with self.assertRaises(refs.Refused):
                P(bad)

    def test_names(self):
        self.assertEqual(refs.slug_name("File:Gong Xian - Wintry mountains (1689).jpg"), "gong-xian-wintry-mountains-1689")
        self.assertTrue(refs.slug_name("File:兕圖.png").startswith("commons-"))
        self.assertEqual(refs.safe_name("../x.jpg"), "x.jpg")          # basename only
        for bad in (".hidden", "a b.jpg", "x/"):
            with self.assertRaises(refs.Refused):
                refs.safe_name(bad)

    def test_plain_strips_html(self):
        self.assertEqual(refs.plain({"value": '<a href="x">Some <b>Painter</b></a>'}), "Some Painter")
        self.assertEqual(refs.plain("a &amp; b"), "a & b")

    def test_retry_after_forms(self):
        self.assertEqual(netfetch.retry_after("7"), 7.0)
        self.assertAlmostEqual(netfetch.retry_after("Wed, 21 Oct 2015 07:28:10 GMT", now=1445412480.0), 10.0)
        self.assertIsNone(netfetch.retry_after("soon"))

    def test_read_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("# comment\n\nFile:A.jpg\nFile:B c.jpg | b_01.jpg | note | with bar\nFile:D.jpg |  | n\n")
            self.assertEqual(refs.read_list(p), [("File:A.jpg", None, None),
                                                 ("File:B c.jpg", "b_01.jpg", "note | with bar"),
                                                 ("File:D.jpg", None, "n")])


@unittest.skipIf(Image is None, "Pillow is not installed")
class TestFetch(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeCommons()
        self.addCleanup(self.fake.close)
        p = mock.patch.object(refs, "API", self.fake.base + "/w/api.php")
        p.start()
        self.addCleanup(p.stop)
        self.slept = []
        s = mock.patch.object(netfetch.time, "sleep", side_effect=lambda t: self.slept.append(t))
        s.start()
        self.addCleanup(s.stop)
        self.out = str(self.tmp / "refs")

    def run_cli(self, *argv):
        return helpers.run_main(refs.main, ["--interval", "0", *argv])

    def credits(self):
        with open(os.path.join(self.out, "_credits.jsonl"), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_429_then_success_honours_retry_after(self):
        self.fake.add("File:Gong Xian - Landscape.jpg", 800, 600)
        self.fake.fail_api = [(429, {"Retry-After": "7"}), (503, {})]
        code, out, err = self.run_cli("fetch", "File:Gong_Xian_-_Landscape.jpg", "--out", self.out)
        self.assertEqual(code, 0, err)
        self.assertIn(7.0, self.slept)              # Retry-After wins
        self.assertIn(4.0, self.slept)              # then exponential backoff: 2 * 2**1
        self.assertIn("HTTP 429", err)
        self.assertTrue(os.path.isfile(os.path.join(self.out, "gong-xian-landscape.jpg")))
        self.assertTrue(all(a == netfetch.USER_AGENT for a in self.fake.agents))
        self.assertNotRegex(netfetch.USER_AGENT, r"@")      # no e-mail or other personal data

    def test_gives_up_after_the_retries(self):
        self.fake.add("File:A.jpg", 100, 100)
        self.fake.fail_api = [(429, {"Retry-After": "1"})] * 10
        code, out, err = self.run_cli("fetch", "File:A.jpg", "--out", self.out)
        self.assertEqual(code, 1)
        self.assertIn("gave up", err)
        self.assertFalse(os.path.exists(os.path.join(self.out, "a.jpg")))

    def test_credits_line_and_resize(self):
        self.fake.add("File:Wide scroll.jpg", 3000, 1000, lic="Public domain")
        code, out, err = self.run_cli("fetch", "File:Wide_scroll.jpg", "--out", self.out, "--name", "loc_old_01_scroll",
                                      "--note", "tam viễn", "--kind", "old")
        self.assertEqual(code, 0, err)
        path = os.path.join(self.out, "loc_old_01_scroll.jpg")
        with Image.open(path) as im:
            self.assertEqual(im.size, (1600, 533))
        [row] = self.credits()
        self.assertEqual(row["file"], "loc_old_01_scroll.jpg")
        self.assertEqual(row["title"], "File:Wide scroll.jpg")
        self.assertEqual(row["page"], "https://commons.wikimedia.org/wiki/File:Wide_scroll.jpg")
        self.assertEqual((row["licence"], row["free"], row["author"]), ("Public domain", True, "Some Painter"))
        self.assertEqual(row["description"], "Wintry & misty mountains")
        self.assertEqual((row["orig_size"], row["size"]), ([3000, 1000], [1600, 533]))
        self.assertEqual((row["note"], row["kind"]), ("tam viễn", "old"))
        for key in ("licence_url", "credit", "date", "url", "fetched"):
            self.assertIn(key, row)

    def test_small_png_kept_byte_for_byte(self):
        self.fake.add("File:Small.png", 400, 300, fmt="PNG")
        code, _, err = self.run_cli("fetch", "File:Small.png", "--out", self.out)
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.out, "small.png"), "rb") as f:
            self.assertEqual(f.read(), self.fake.files["File:Small.png"]["data"])

    def test_no_overwrite(self):
        self.fake.add("File:A.jpg", 100, 100)
        self.assertEqual(self.run_cli("fetch", "File:A.jpg", "--out", self.out)[0], 0)
        path = os.path.join(self.out, "a.jpg")
        before = (os.path.getmtime(path), os.path.getsize(path))
        code, out, err = self.run_cli("fetch", "File:A.jpg", "--out", self.out)
        self.assertEqual(code, 0)
        self.assertIn("already in _credits.jsonl", out)
        self.assertEqual((os.path.getmtime(path), os.path.getsize(path)), before)
        self.assertEqual(len(self.credits()), 1)
        # a file of the same name made by hand is not replaced either
        self.fake.add("File:B.jpg", 100, 100)
        with open(os.path.join(self.out, "mine.jpg"), "wb") as f:
            f.write(b"hand made")
        code, out, _ = self.run_cli("fetch", "File:B.jpg", "--out", self.out, "--name", "mine.jpg")
        self.assertIn("exists", out)
        with open(os.path.join(self.out, "mine.jpg"), "rb") as f:
            self.assertEqual(f.read(), b"hand made")

    def test_nonfree_refused_unless_allowed(self):
        self.fake.add("File:Modern.jpg", 200, 200, lic="CC BY-NC-SA 4.0")
        code, out, err = self.run_cli("fetch", "File:Modern.jpg", "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("not free", err)
        self.assertFalse(os.path.exists(os.path.join(self.out, "modern.jpg")))
        code, out, err = self.run_cli("fetch", "File:Modern.jpg", "--out", self.out, "--allow-nonfree")
        self.assertEqual(code, 0, err)
        [row] = self.credits()
        self.assertEqual((row["free"], row["licence"]), (False, "CC BY-NC-SA 4.0"))
        self.assertIn("[NON-FREE]", out)

    def test_list_file_and_missing_page(self):
        self.fake.add("File:A.jpg", 100, 100)
        self.fake.add("File:B.png", 100, 100, fmt="PNG")
        lst = self.tmp / "refs.txt"
        lst.write_text("File:A.jpg | x_01_a | first\nFile:B.png\nFile:Nope.jpg\nhttps://example.com/x.jpg\n",
                       encoding="utf-8")
        code, out, err = self.run_cli("fetch", "--list", str(lst), "--out", self.out)
        self.assertEqual(code, 1)                    # one page missing on Commons
        self.assertIn("2 saved", out)
        self.assertIn("1 refused", out)
        self.assertEqual(sorted(r["file"] for r in self.credits()), ["b.png", "x_01_a.jpg"])
        self.assertEqual([r["note"] for r in self.credits() if r["file"] == "x_01_a.jpg"], ["first"])

    def test_search(self):
        self.fake.add("File:A.jpg", 100, 50)
        self.fake.add("File:B.jpg", 100, 50, lic="CC BY-ND 4.0")
        code, out, err = self.run_cli("search", "phoenix bronze", "--limit", "5")
        self.assertEqual(code, 0, err)
        self.assertIn("File:A.jpg | 100x50 | CC BY-SA 4.0 | Some Painter", out)
        self.assertIn("[NON-FREE]", out)
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.fake.calls[-1]).query)
        self.assertEqual((q["gsrsearch"], q["gsrnamespace"], q["gsrlimit"]), (["phoenix bronze"], ["6"], ["5"]))
        code, out, _ = self.run_cli("search", "x", "--free-only")
        self.assertNotIn("File:B.jpg", out)
        self.assertFalse(os.path.exists(self.out))  # search never writes

    def test_usage_errors(self):
        self.assertEqual(self.run_cli("fetch", "--out", self.out)[0], 2)
        self.assertEqual(self.run_cli("fetch", "File:A.jpg", "File:B.jpg", "--name", "x", "--out", self.out)[0], 2)


class TestRateLimit(unittest.TestCase):
    def test_min_interval_between_requests(self):
        t = [100.0]
        waits = []
        c = netfetch.Client(min_interval=1.5, clock=lambda: t[0], sleep=waits.append)
        c._throttle()
        t[0] += 0.5
        c._throttle()
        self.assertEqual(waits, [1.0])


if __name__ == "__main__":
    unittest.main()
