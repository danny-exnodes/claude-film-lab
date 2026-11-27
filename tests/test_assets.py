"""tools/assets.py (Poly Haven + ambientCG CC0 assets) and the download half of tools/netfetch.py (.part, Range
resume, md5), against a local fake API server. Never touches the real network."""
import csv, hashlib, io, json, os, threading, unittest, urllib.parse, zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import helpers

assets = helpers.load("assets.py")
netfetch = assets.netfetch
spec = helpers.load("blender/spec.py", "film_blender_spec_assets_t")


def blob(name, n):
    """Deterministic bytes for a fake file."""
    seed = hashlib.sha256(name.encode()).digest()
    return (seed * (n // len(seed) + 1))[:n]


def zip_bytes(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeAPI:
    """/ph/... = Poly Haven (assets, info/<id>, files/<id>), /acg = ambientCG v2 full_json, /dl/<name> = files with
    Range support. Knobs: wrong_md5 (names served with other bytes), ignore_range, fail_dl (name -> [(status, hdrs)])."""

    def __init__(self):
        self.files, self.ranges, self.calls = {}, [], []
        self.wrong_md5, self.ignore_range, self.fail_dl = set(), False, {}
        self.ph, self.acg = {}, []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
                fake.calls.append(self.path)
                p = u.path
                if p == "/ph/assets":
                    want = {"hdris": 0, "textures": 1, "models": 2}[q["type"]]
                    return self.json({k: v["info"] for k, v in fake.ph.items() if v["info"]["type"] == want})
                if p.startswith("/ph/info/") or p.startswith("/ph/files/"):
                    aid = p.rsplit("/", 1)[1]
                    if aid not in fake.ph:
                        return self.status(404)
                    return self.json(fake.ph[aid]["info" if "/info/" in p else "files"])
                if p == "/acg":
                    if "id" in q:
                        found = [a for a in fake.acg if a["assetId"] == q["id"]]
                    else:
                        found = [a for a in fake.acg if a["dataType"] == q["type"]]
                    return self.json({"foundAssets": found})
                if p.startswith("/dl/"):
                    name = urllib.parse.unquote(p[4:])
                    if fake.fail_dl.get(name):
                        st, hdrs = fake.fail_dl[name].pop(0)
                        return self.status(st, hdrs)
                    if name not in fake.files:
                        return self.status(404)
                    data = fake.files[name]
                    if name in fake.wrong_md5:
                        data = bytes(255 - b for b in data)
                    rng = self.headers.get("Range")
                    fake.ranges.append((name, rng))
                    if rng and not fake.ignore_range:
                        start = int(rng.split("=")[1].split("-")[0])
                        body = data[start:]
                        self.send_response(206)
                        self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                    else:
                        body = data
                        self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.status(404)

            def json(self, obj):
                body = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def status(self, st, hdrs=None):
                self.send_response(st)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", "0")
                self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def file(self, name, n=None, data=None, md5=True):
        """Register a downloadable file -> its API entry {url, size, md5}."""
        data = data if data is not None else blob(name, n)
        self.files[name] = data
        e = {"url": f"{self.base}/dl/{name}", "size": len(data)}
        if md5:
            e["md5"] = hashlib.md5(data).hexdigest()
        return e

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def setup_catalogue(f):
    f.ph["sky_puresky"] = {
        "info": {"name": "Sky (Pure Sky)", "type": 0, "categories": ["skies", "outdoor"], "tags": ["dawn", "clear"],
                 "max_resolution": [8192, 4096], "download_count": 50},
        "files": {"hdri": {"1k": {"hdr": f.file("sky_puresky_1k.hdr", 3000)},
                           "2k": {"hdr": f.file("sky_puresky_2k.hdr", 9000), "exr": f.file("sky_puresky_2k.exr", 9500)}}}}
    f.ph["rock_face"] = {
        "info": {"name": "Rock Face", "type": 1, "categories": ["rock"], "tags": ["cliff", "grey"],
                 "max_resolution": [4096, 4096], "download_count": 90},
        "files": {"Diffuse": {"2k": {"jpg": f.file("rock_face_diff_2k.jpg", 5000), "png": f.file("rock_face_diff_2k.png", 8000)}},
                  "nor_gl": {"2k": {"png": f.file("rock_face_nor_gl_2k.png", 7000), "jpg": f.file("rock_face_nor_gl_2k.jpg", 4000)}},
                  "Rough": {"2k": {"jpg": f.file("rock_face_rough_2k.jpg", 3000)}},
                  "Displacement": {"2k": {"png": f.file("rock_face_disp_2k.png", 6000)}}}}
    gl = f.file("boulder_2k.gltf", 1200)
    gl["include"] = {"boulder.bin": f.file("boulder.bin", 4000),
                     "textures/boulder_diff_2k.jpg": f.file("boulder_diff_2k.jpg", 2500)}
    f.ph["boulder"] = {"info": {"name": "Boulder", "type": 2, "categories": ["rocks"], "tags": ["stone"],
                                "max_resolution": [2048, 2048], "download_count": 10},
                       "files": {"gltf": {"2k": {"gltf": gl}}}}
    z = zip_bytes({"Rock030_2K-JPG_Color.jpg": blob("c", 900), "Rock030_2K-JPG_NormalGL.jpg": blob("n", 800),
                   "Rock030_2K-JPG_Roughness.jpg": blob("r", 700), "Rock030.mtlx": b"<xml/>",
                   "../escape_Color.jpg": blob("e", 10), "sub/": b""})
    zentry = f.file("Rock030_2K-JPG.zip", data=z, md5=False)
    f.acg.append({"assetId": "Rock030", "displayName": "Rock 030", "dataType": "Material", "tags": ["rock", "cliff"],
                  "downloadFolders": {"default": {"downloadFiletypeCategories": {"zip": {"downloads": [
                      {"attribute": "1K-JPG", "fileName": "Rock030_1K-JPG.zip", "filetype": "zip", "size": 10,
                       "fullDownloadPath": f.base + "/dl/Rock030_1K-JPG.zip"},
                      {"attribute": "2K-JPG", "fileName": "Rock030_2K-JPG.zip", "filetype": "zip",
                       "size": zentry["size"], "fullDownloadPath": zentry["url"]}]}}}}})
    exr = f.file("DaySky001_2K-HDR.exr", 5000, md5=False)
    f.acg.append({"assetId": "DaySky001", "displayName": "Day Sky 001", "dataType": "HDRI", "tags": ["sky"],
                  "downloadFolders": {"default": {"downloadFiletypeCategories": {"exr": {"downloads": [
                      {"attribute": "2K-HDR", "fileName": "DaySky001_2K-HDR.exr", "filetype": "exr",
                       "size": exr["size"], "fullDownloadPath": exr["url"]}]}}}}})


class AssetsCase(helpers.TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeAPI()
        self.addCleanup(self.fake.close)
        setup_catalogue(self.fake)
        for name, value in (("PH_API", self.fake.base + "/ph"), ("ACG_API", self.fake.base + "/acg")):
            p = mock.patch.object(assets, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.slept = []
        s = mock.patch.object(netfetch.time, "sleep", side_effect=lambda t: self.slept.append(t))
        s.start()
        self.addCleanup(s.stop)
        self.root = str(self.tmp / "assets")

    def cli(self, *argv):
        return helpers.run_main(assets.main, ["--interval", "0", *argv])

    def manifest(self):
        with open(os.path.join(self.root, "ASSETS_MANIFEST.csv"), newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            return r.fieldnames, list(r)

    def downloads(self):
        return [c for c in self.fake.calls if c.startswith("/dl/")]


class TestPlan(AssetsCase):
    def test_plan_totals_and_downloads_nothing(self):
        code, out, err = self.cli("plan", "rock_face", "sky_puresky", "--asset-root", self.root)
        self.assertEqual(code, 0, err)
        self.assertIn("rock_face  texture  polyhaven  CC0  2k  https://polyhaven.com/a/rock_face", out)
        self.assertIn("new      textures/rock_face/rock_face_diff_2k.jpg", out)      # jpg preferred for colour
        self.assertIn("textures/rock_face/rock_face_nor_gl_2k.png", out)              # png preferred for normals
        self.assertIn("hdri/sky_puresky_2k.hdr", out)
        self.assertNotIn("_ao_", out)                                                 # no AO map: skipped
        total = 5000 + 7000 + 3000 + 6000 + 9000
        self.assertIn(f"total: 5 file(s) to download, {assets.human(total)} ({assets.human(0)} already on disk)", out)
        self.assertIn("free on disk:", out)
        self.assertEqual(self.downloads(), [])
        self.assertFalse(os.path.exists(self.root))

    def test_plan_counts_existing_and_partial(self):
        os.makedirs(os.path.join(self.root, "hdri"))
        with open(os.path.join(self.root, "hdri", "sky_puresky_2k.hdr"), "wb") as f:
            f.write(self.fake.files["sky_puresky_2k.hdr"])
        tex = os.path.join(self.root, "textures", "rock_face")
        os.makedirs(tex)
        with open(os.path.join(tex, "rock_face_diff_2k.jpg.part"), "wb") as f:
            f.write(self.fake.files["rock_face_diff_2k.jpg"][:2000])
        code, out, _ = self.cli("plan", "rock_face", "sky_puresky", "--asset-root", self.root)
        self.assertEqual(code, 0)
        self.assertIn("exists   hdri/sky_puresky_2k.hdr", out)
        self.assertIn("partial  textures/rock_face/rock_face_diff_2k.jpg", out)
        left = 3000 + 7000 + 3000 + 6000
        self.assertIn(f"total: 4 file(s) to download, {assets.human(left)} ({assets.human(9000)} already on disk)", out)

    def test_unknown_resolution_and_type(self):
        code, _, err = self.cli("plan", "rock_face", "--res", "8k", "--asset-root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("has no 8k (has: 2k)", err)
        code, _, err = self.cli("plan", "rock_face", "--type", "hdri", "--asset-root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("is a texture, not a hdri", err)
        self.assertEqual(self.cli("plan", "nope", "--asset-root", self.root)[0], 2)
        self.assertEqual(self.cli("plan", "../x", "--asset-root", self.root)[0], 2)


class TestFetch(AssetsCase):
    def test_refuses_without_yes(self):
        code, out, err = self.cli("fetch", "rock_face", "--asset-root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("total: 4 file(s)", out)
        self.assertIn("--yes", err)
        self.assertEqual(self.downloads(), [])

    def test_texture_fetch_manifest_and_no_overwrite(self):
        code, out, err = self.cli("fetch", "rock_face", "--asset-root", self.root, "--use", "cliff s03", "--yes")
        self.assertEqual(code, 0, err)
        tex = os.path.join(self.root, "textures", "rock_face")
        self.assertEqual(sorted(os.listdir(tex)), ["rock_face_diff_2k.jpg", "rock_face_disp_2k.png",
                                                   "rock_face_nor_gl_2k.png", "rock_face_rough_2k.jpg"])
        header, rows = self.manifest()
        self.assertEqual(header, assets.HEADER)
        [row] = rows
        self.assertEqual({k: row[k] for k in ("asset_id", "kind", "source", "title", "url_page", "licence", "resolution",
                                               "suggested_use")},
                         {"asset_id": "rock_face", "kind": "texture", "source": "polyhaven", "title": "Rock Face",
                          "url_page": "https://polyhaven.com/a/rock_face", "licence": "CC0", "resolution": "2k",
                          "suggested_use": "cliff s03"})
        self.assertEqual(row["files"], "rock_face_diff_2k.jpg;rock_face_nor_gl_2k.png;rock_face_rough_2k.jpg;"
                                       "rock_face_disp_2k.png")
        self.assertEqual(row["bytes"], str(5000 + 7000 + 3000 + 6000))
        # the Blender realistic look finds the set through asset_root
        found = spec.resolve_texture("rock_face", self.root, str(self.tmp))
        self.assertEqual(sorted(found), ["diff", "disp", "nor_gl", "rough"])
        # again: nothing downloaded, nothing overwritten, one row; the use hint is kept unless given
        before = self.downloads()
        with open(os.path.join(tex, "rock_face_diff_2k.jpg"), "ab") as f:
            f.write(b"local edit")
        code, out, _ = self.cli("fetch", "rock_face", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.downloads(), before)
        with open(os.path.join(tex, "rock_face_diff_2k.jpg"), "rb") as f:
            self.assertTrue(f.read().endswith(b"local edit"))
        self.assertEqual([r["suggested_use"] for r in self.manifest()[1]], ["cliff s03"])

    def test_md5_mismatch_keeps_part_and_errors(self):
        self.fake.wrong_md5.add("sky_puresky_2k.hdr")
        code, out, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 1)
        self.assertIn("md5 mismatch for sky_puresky_2k.hdr", err)
        hdri = os.path.join(self.root, "hdri")
        self.assertEqual(os.listdir(hdri), ["sky_puresky_2k.hdr.part"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "ASSETS_MANIFEST.csv")))
        # run again: the complete .part is checked again, not downloaded again, and still refused
        n = len(self.downloads())
        code, _, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 1)
        self.assertEqual(len(self.downloads()), n)
        self.assertIn("delete it and run again", err)

    def test_resume_with_range(self):
        hdri = os.path.join(self.root, "hdri")
        os.makedirs(hdri)
        data = self.fake.files["sky_puresky_2k.hdr"]
        with open(os.path.join(hdri, "sky_puresky_2k.hdr.part"), "wb") as f:
            f.write(data[:4000])
        code, out, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn(("sky_puresky_2k.hdr", "bytes=4000-"), self.fake.ranges)
        self.assertIn("resumed at", out)
        with open(os.path.join(hdri, "sky_puresky_2k.hdr"), "rb") as f:
            self.assertEqual(f.read(), data)
        self.assertEqual(spec.resolve_hdri("sky_puresky", self.root, str(self.tmp)),
                         os.path.join(self.root, "hdri", "sky_puresky_2k.hdr"))

    def test_server_ignoring_range_starts_over(self):
        self.fake.ignore_range = True
        hdri = os.path.join(self.root, "hdri")
        os.makedirs(hdri)
        with open(os.path.join(hdri, "sky_puresky_2k.hdr.part"), "wb") as f:
            f.write(b"x" * 100)                      # garbage that must not stay in front
        code, _, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        with open(os.path.join(hdri, "sky_puresky_2k.hdr"), "rb") as f:
            self.assertEqual(f.read(), self.fake.files["sky_puresky_2k.hdr"])

    def test_429_on_download_is_retried(self):
        self.fake.fail_dl["sky_puresky_2k.hdr"] = [(429, {"Retry-After": "3"})]
        code, _, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn(3.0, self.slept)

    def test_model_with_includes(self):
        code, out, err = self.cli("fetch", "boulder", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        base = os.path.join(self.root, "models", "boulder")
        for rel in ("boulder_2k.gltf", "boulder.bin", "textures/boulder_diff_2k.jpg"):
            self.assertTrue(os.path.isfile(os.path.join(base, rel)), rel)
        [row] = self.manifest()[1]
        self.assertEqual(row["files"], "boulder_2k.gltf;boulder.bin;textures/boulder_diff_2k.jpg")
        self.assertEqual(row["kind"], "model")

    def test_unsafe_include_path_refused(self):
        self.fake.ph["boulder"]["files"]["gltf"]["2k"]["gltf"]["include"]["../../evil.bin"] = self.fake.file("e.bin", 5)
        code, _, err = self.cli("plan", "boulder", "--asset-root", self.root)
        self.assertEqual(code, 2)
        self.assertIn("unsafe file name", err)

    def test_ambientcg_zip_extracted(self):
        code, out, err = self.cli("fetch", "Rock030", "--source", "ambientcg", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("size only zip→extract", out)
        tex = os.path.join(self.root, "textures", "Rock030")
        self.assertEqual(sorted(os.listdir(tex)), ["Rock030_2K-JPG_Color.jpg", "Rock030_2K-JPG_NormalGL.jpg",
                                                   "Rock030_2K-JPG_Roughness.jpg", "escape_Color.jpg"])
        self.assertFalse(os.path.exists(os.path.join(self.root, "textures", "escape_Color.jpg")))
        [row] = self.manifest()[1]
        self.assertEqual((row["source"], row["licence"], row["resolution"], row["url_page"]),
                         ("ambientcg", "CC0", "2k", "https://ambientcg.com/view?id=Rock030"))
        self.assertIn("Rock030_2K-JPG_Color.jpg", row["files"].split(";"))
        self.assertEqual(sorted(spec.resolve_texture("Rock030", self.root, str(self.tmp))), ["diff", "nor_gl", "rough"])
        # second run: the zip is not downloaded again
        n = len(self.downloads())
        code, out, _ = self.cli("fetch", "Rock030", "--source", "ambientcg", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0)
        self.assertIn("exists   textures/Rock030/Rock030_2K-JPG.zip", out)
        self.assertEqual(len(self.downloads()), n)

    def test_zip_on_disk_never_extracted_is_extracted_on_rerun(self):
        # an earlier run downloaded the zip and stopped before extracting it (no manifest row): no crash, no download
        tex = os.path.join(self.root, "textures", "Rock030")
        os.makedirs(tex)
        with open(os.path.join(tex, "Rock030_2K-JPG.zip"), "wb") as f:
            f.write(zip_bytes({"Rock030_2K-JPG_Color.jpg": blob("c", 900)}))
        code, out, err = self.cli("fetch", "Rock030", "--source", "ambientcg", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.downloads(), [])
        self.assertEqual(sorted(os.listdir(tex)), ["Rock030_2K-JPG_Color.jpg"])
        self.assertEqual(self.manifest()[1][0]["files"], "Rock030_2K-JPG_Color.jpg")

    def test_extract_duplicates_and_model_subfolders(self):
        z = self.tmp / "m.zip"
        z.write_bytes(zip_bytes({"a/x_Color.jpg": b"1", "b/x_Color.jpg": b"2"}))
        dest = self.tmp / "flat"
        dest.mkdir()
        with self.assertRaises(netfetch.FetchError) as cm:
            assets.extract(str(z), str(dest))
        self.assertIn("two members", str(cm.exception))
        self.assertEqual(os.listdir(dest), [])                     # nothing half-extracted
        z.write_bytes(zip_bytes({"rock.gltf": b"{}", "rock.bin": b"0", "textures/rock_diff.jpg": b"1",
                                 "../evil.jpg": b"e", "a/../b.jpg": b"e"}))
        model = self.tmp / "model"
        model.mkdir()
        got = assets.extract(str(z), str(model), keep_dirs=True)
        self.assertEqual(got, ["b.jpg", "evil.jpg", "rock.bin", "rock.gltf", "textures/rock_diff.jpg"])
        self.assertTrue((model / "textures" / "rock_diff.jpg").is_file())
        self.assertFalse((self.tmp / "evil.jpg").exists())
        with mock.patch.object(assets, "free_space", return_value=1):
            with self.assertRaises(netfetch.FetchError):
                assets.extract(str(z), str(self.tmp / "model2"), keep_dirs=True)

    def test_ambientcg_hdri_size_check(self):
        self.fake.acg[1]["downloadFolders"]["default"]["downloadFiletypeCategories"]["exr"]["downloads"][0]["size"] = 1
        code, _, err = self.cli("fetch", "DaySky001", "--source", "ambientcg", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 1)
        self.assertIn("size mismatch", err)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "hdri", "DaySky001_2K-HDR.exr.part")))

    def test_existing_manifest_kept(self):
        os.makedirs(self.root)
        with open(os.path.join(self.root, "ASSETS_MANIFEST.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(assets.HEADER)
            w.writerow(["old_rock", "texture", "polyhaven", "Old Rock", "https://polyhaven.com/a/old_rock", "CC0", "2k",
                        "old_rock_diff_2k.jpg", "12", "valley, \"wet\" rock"])
        code, _, err = self.cli("fetch", "sky_puresky", "--asset-root", self.root, "--yes")
        self.assertEqual(code, 0, err)
        header, rows = self.manifest()
        self.assertEqual(header, assets.HEADER)
        self.assertEqual([r["asset_id"] for r in rows], ["old_rock", "sky_puresky"])
        self.assertEqual(rows[0]["suggested_use"], 'valley, "wet" rock')


class TestSearch(AssetsCase):
    def test_search_both_sources(self):
        code, out, err = self.cli("search", "--type", "texture", "--tag", "cliff", "--query", "rock")
        self.assertEqual(code, 0, err)
        self.assertIn("rock_face | texture | polyhaven | Rock Face | rock | max 4096x4096 | https://polyhaven.com/a/rock_face", out)
        self.assertIn("Rock030 | texture | ambientcg | Rock 030 | rock, cliff | https://ambientcg.com/view?id=Rock030", out)
        acg = [c for c in self.fake.calls if c.startswith("/acg?")][-1]
        q = urllib.parse.parse_qs(urllib.parse.urlparse(acg).query)
        self.assertEqual((q["type"], q["q"], q["tags"]), (["Material"], ["rock"], ["cliff"]))
        code, out, _ = self.cli("search", "--type", "hdri", "--source", "polyhaven", "--tag", "night")
        self.assertEqual(code, 0)
        self.assertNotIn("sky_puresky", out)
        self.assertEqual(self.downloads(), [])


class TestNetfetchDownload(helpers.TmpDirCase, unittest.TestCase):
    def test_exists_is_never_overwritten(self):
        dest = str(self.tmp / "a.bin")
        with open(dest, "wb") as f:
            f.write(b"mine")
        r = netfetch.Client(min_interval=0).download("http://127.0.0.1:9/never", dest, size=10, md5="0" * 32)
        self.assertEqual(r["status"], "exists")
        with open(dest, "rb") as f:
            self.assertEqual(f.read(), b"mine")

    def test_backoff_without_retry_after_doubles(self):
        waits = []
        err = __import__("urllib.error").error.HTTPError("http://x", 503, "busy", {}, None)
        c = netfetch.Client(min_interval=0, retries=3, backoff=2.0, sleep=waits.append)
        with mock.patch.object(netfetch.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(netfetch.FetchError):
                c.get("http://x")
        self.assertEqual(waits, [2.0, 4.0, 8.0])

    def test_404_is_not_retried(self):
        waits = []
        err = __import__("urllib.error").error.HTTPError("http://x", 404, "nope", {}, None)
        c = netfetch.Client(min_interval=0, sleep=waits.append)
        with mock.patch.object(netfetch.urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(netfetch.FetchError) as cm:
                c.get("http://x")
        self.assertEqual((cm.exception.status, waits), (404, []))

    def test_retry_after_above_the_cap_gives_up_instead_of_retrying_early(self):
        waits = []
        err = __import__("urllib.error").error.HTTPError("http://x", 429, "slow down", {"Retry-After": "600"}, None)
        c = netfetch.Client(min_interval=0, max_wait=120, sleep=waits.append)
        with mock.patch.object(netfetch.urllib.request, "urlopen", side_effect=err) as m:
            with self.assertRaises(netfetch.FetchError) as cm:
                c.get("http://x")
        self.assertIn("wait 600 s", str(cm.exception))
        self.assertEqual((waits, m.call_count), ([], 1))

    def test_cut_body_string_size_and_complete_part(self):
        import http.client

        class Resp:
            status = 200

            def __init__(self, data=b"", cut=False):
                self.data, self.cut = io.BytesIO(data), cut

            def read(self, n=-1):
                if self.cut:
                    raise http.client.IncompleteRead(b"ab", 10)
                return self.data.read(n)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def getcode(self):
                return self.status

        c = netfetch.Client(min_interval=0, sleep=lambda t: None)
        dest = str(self.tmp / "f.bin")
        with mock.patch.object(netfetch.urllib.request, "urlopen", return_value=Resp(cut=True)):
            with self.assertRaises(netfetch.FetchError) as cm:
                c.download("http://x/f.bin", dest)
            self.assertIn("connection cut", str(cm.exception))
            with self.assertRaises(netfetch.FetchError):
                c.get("http://x")
        # size from an API as a string
        with mock.patch.object(netfetch.urllib.request, "urlopen", return_value=Resp(b"hello")):
            self.assertEqual(c.download("http://x/f.bin", str(self.tmp / "g.bin"), size="5")["bytes"], 5)
        # size unknown, the .part is already complete: the server answers 416 to the Range request
        with open(str(self.tmp / "h.bin.part"), "wb") as f:
            f.write(b"done!")
        e416 = __import__("urllib.error").error.HTTPError("http://x", 416, "range", {}, None)
        with mock.patch.object(netfetch.urllib.request, "urlopen", side_effect=e416):
            r = c.download("http://x/h.bin", str(self.tmp / "h.bin"))
        self.assertEqual((r["status"], r["bytes"]), ("done", 5))


if __name__ == "__main__":
    unittest.main()
