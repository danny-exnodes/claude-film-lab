"""tools/comfy/comfy.py models --inventory / --suggest-clean / --fetch (issue #75). The Hugging Face side is a fake
server (http.server in a thread, tree API + resolve with Range); nothing reaches the network or a real model folder."""
import hashlib, json, os, re, threading, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlparse

import test_comfy as tc
from helpers import REPO

comfy = tc.comfy
LOCK = json.loads((REPO / "tools" / "comfy" / "comfy.lock.json").read_text(encoding="utf-8"))


class FakeHF:
    """GET /api/models/<org>/<repo>/tree/<rev>[/<dir>] and /<org>/<repo>/resolve/<rev>/<path> (Range: 206)."""

    def __init__(self, files):
        self.files = files                 # {(repo, path): bytes}
        self.calls, self.ranges = [], []
        self.ignore_range, self.serve = False, {}     # serve: (repo, path) -> other bytes (a corrupt mirror)
        self.oid = {}                       # (repo, path) -> sha256 shown by the API (default: the real one)
        self.redirect = True                # resolve answers 302 to a /cdn/ URL first, like huggingface.co
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def send(self, code, body=b"", headers=()):
                self.send_response(code)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = unquote(urlparse(self.path).path)
                fake.calls.append(path)
                m = re.fullmatch(r"/api/models/([^/]+/[^/]+)/tree/([^/]+)(?:/(.*))?", path)
                if m:
                    repo, d = m.group(1), m.group(3) or ""
                    out = []
                    for (r, p), data in fake.files.items():
                        parent = p.rsplit("/", 1)[0] if "/" in p else ""
                        if r == repo and parent == d:
                            oid = fake.oid.get((r, p), hashlib.sha256(data).hexdigest())
                            out.append({"type": "file", "oid": "0" * 40, "size": len(data), "path": p,
                                        "lfs": {"oid": oid, "size": len(data), "pointerSize": 134}})
                    return self.send(200, json.dumps(out).encode(), [("Content-Type", "application/json")])
                m = re.fullmatch(r"/(cdn/)?([^/]+/[^/]+)/resolve/([^/]+)/(.*)", path)
                if m:
                    key = (m.group(2), m.group(4))
                    if key not in fake.files:
                        return self.send(404, b"not found")
                    if fake.redirect and not m.group(1):
                        return self.send(302, b"", [("Location", "/cdn" + self.path)])
                    data = fake.serve.get(key, fake.files[key])
                    rng = self.headers.get("Range")
                    fake.ranges.append(rng)
                    if rng and not fake.ignore_range:
                        start = int(re.match(r"bytes=(\d+)-", rng).group(1))
                        return self.send(206, data[start:], [("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")])
                    return self.send(200, data)
                self.send(404, b"no route")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class ModelsCase(tc.ComfyCase):
    def setUp(self):
        super().setUp()
        os.environ["FILM_HF_URL"] = "http://127.0.0.1:9"        # closed port unless a test starts the fake HF
        os.environ.pop("FILM_AGENT", None)                      # --fetch --yes is main-session only
        self.models = self.tmp / "models"

    def put(self, rel, size_or_data, root=None):
        p = (root or self.models) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = size_or_data if isinstance(size_or_data, bytes) else None
        with open(p, "wb") as f:
            if data is not None:
                f.write(data)
            else:
                f.truncate(size_or_data)            # sparse
        return p

    def hf(self, files):
        f = FakeHF(files)
        self.addCleanup(f.stop)
        os.environ["FILM_HF_URL"] = f.url
        return f

    def lock(self, entries, sets=None):
        lock = {"comfyui": LOCK["comfyui"], "custom_nodes": [], "models": entries}
        if sets:
            lock["sets"] = sets
        self.n_locks = getattr(self, "n_locks", 0) + 1
        p = self.tmp / f"lock{self.n_locks}.json"
        p.write_text(json.dumps(lock), encoding="utf-8")
        return str(p)

    def entry(self, file, data, folder="diffusion_models", repo="Org/Repo", path=None, sha=None, set_="edit-set"):
        return {"set": set_, "folder": folder, "file": file, "workflows": [], "size": len(data),
                "sha256": sha, "hf": {"repo": repo, "path": path or f"split_files/{folder}/{file}", "revision": "main"},
                "license": "test"}


class TestInventory(ModelsCase):
    def test_inventory_families_usage_and_drives(self):
        self.put("diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors", 3000)
        self.put("diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors", 2000)
        self.put("loras/Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors", 100)
        self.put("text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors", 900)
        self.put("diffusion_models/wan2.2_animate_14B_bf16.safetensors", 5000)
        self.put("diffusion_models/ltx-2.3-22b-dev-fp8.safetensors", 4000)
        self.put("text_encoders/gemma_3_12B_it_fp4.safetensors", 700)
        self.put("diffusion_models/seedvr2_3b_int8_convrot.safetensors", 600)
        self.put("checkpoints/hunyuan_3d_v2.1.safetensors", 800)
        self.put("diffusion_models/z_image_turbo_bf16.safetensors", 500)
        self.put("upscale_models/4x_foo.pth", 50)
        self.put("loras/readme.txt", 10)                                    # not a model file
        other = self.tmp / "other-root"                                     # an extra_model_paths base_path
        self.put("vae/wan_2.1_vae.safetensors", 300, root=other)
        yaml = self.tmp / "paths.yaml"
        yaml.write_text(f"comfy.desktop_0:\n  base_path: '{self.models}'\n  is_default: true\n"
                        f"other:\n  base_path: \"{other}\"\n  vae: vae/\n", encoding="utf-8")
        os.environ["FILM_COMFY_MODEL_PATHS"] = str(yaml)
        before = sorted(p for p in self.tmp.rglob("*"))
        code, out, err = self.run_comfy("models", "--inventory")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p for p in self.tmp.rglob("*")), before, "read-only")
        self.assertIn(f"model folders: [1] {self.models} · [2] {other}", out)
        self.assertRegex(out, r"(?m)^Wan +0\.00  \[2\] vae/wan_2\.1_vae\.safetensors +-$")
        line = lambda name: next(l for l in out.splitlines() if name in l)
        self.assertRegex(line("minimax_h3_fl2va"), r"^H3 .* h3-i2v \(lock set minimax-h3\)$")
        self.assertRegex(line("qwen_image_edit_2511"), r"^Qwen-Edit .* qwen-edit \(lock set qwen-image-edit-2511\)$")
        self.assertRegex(line("Lightning-8steps"), r"^Qwen-Edit .* qwen-edit ")
        self.assertRegex(line("qwen_2.5_vl"), r"^Qwen-Image .* qwen-edit, qwen-t2i \(lock set qwen-image\)$")
        self.assertRegex(line("wan2.2_animate"), r"^Wan .* -$")
        self.assertRegex(line("wan_2.1_vae"), r"^Wan ")
        self.assertRegex(line("ltx-2.3"), r"^LTX ")
        self.assertRegex(line("gemma_3"), r"^LTX ")
        self.assertRegex(line("seedvr2_3b"), r"^SeedVR2 ")
        self.assertRegex(line("hunyuan_3d_v2.1"), r"^Hunyuan3D .*\(lock set hunyuan3d-2.1\)")
        self.assertRegex(line("z_image_turbo"), r"^Z-Image ")
        self.assertRegex(line("4x_foo.pth"), r"^other ")
        self.assertNotIn("readme.txt", out)
        self.assertRegex(out, r"families: H3 0\.0 GB \(1\) · Qwen-Edit 0\.0 GB \(2\) · .* total 0\.0 GB in 12 files")
        self.assertRegex(out, r"drives: .* GB free of .* GB")
        self.assertNotIn("clean-up candidates", out)

    def test_suggest_clean_never_deletes_and_never_lists_lab_files(self):
        lab = self.put("diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors", 1000)
        lab_lock_only = self.put("checkpoints/hunyuan_3d_v2.1.safetensors", 800)
        unused = self.put("diffusion_models/wan2.2_animate_14B_bf16.safetensors", 5000)
        dup = self.put("unet/qwen_image_2512_fp8_e4m3fn.safetensors", 1000)              # same name + size
        part = self.put("diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors_.part", 400)   # the \r bug
        bad = self.put("loras/x.safetensors.bad", 30)
        before = {p: p.stat().st_size for p in self.tmp.rglob("*") if p.is_file()}
        code, out, err = self.run_comfy("models", "--suggest-clean")
        self.assertEqual(code, 0, err)
        self.assertEqual({p: p.stat().st_size for p in self.tmp.rglob("*") if p.is_file()}, before, "never deletes")
        cands = out.split("clean-up candidates", 1)[1]
        self.assertIn(f"{unused}  -- no lab workflow or lock set uses it", cands)
        self.assertRegex(cands, re.escape(str(dup)) + r"  -- duplicate \(same name and size\) of .*" +
                         re.escape(str(lab)))
        self.assertIn(f"{part}  -- a download that did not finish", cands)
        self.assertIn("the name ends in '_': a \\r from a shell pipe?", cands)
        self.assertIn(f"{bad}  -- a download that did not finish", cands)
        self.assertNotIn(f"{lab}  --", cands)
        self.assertNotIn(str(lab_lock_only), cands)
        self.assertIn("total 0.0 GB in 4 file(s)", cands)
        self.assertNotIn("families:", out)                                  # --inventory not asked
        code, out, _ = self.run_comfy("models", "--inventory", "--suggest-clean")
        self.assertEqual(code, 0)
        self.assertIn("families:", out)
        self.assertIn("clean-up candidates", out)

    def test_flag_combinations(self):
        for argv, want in ((["--inventory", "--fetch", "x"], "one at a time"),
                           (["--inventory", "--set", "qwen-image"], "do not take them"),
                           (["--yes"], "--yes goes with --fetch")):
            code, _, err = self.run_comfy("models", *argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(want, err)


class TestFetch(ModelsCase):
    DATA = os.urandom(3000) + b"tail"

    def setUp(self):
        super().setUp()
        self.e = self.entry("qwen_image_edit_2511_fp8mixed.safetensors", self.DATA)
        self.lockp = self.lock([self.e], {"edit-set": {"license": "Apache-2.0 (test)", "note": "n"}})
        self.dest = self.models / "diffusion_models" / self.e["file"]
        self.key = ("Org/Repo", self.e["hf"]["path"])
        self.f = self.hf({self.key: self.DATA})
        comfy_chunk = mock.patch.object(comfy, "FETCH_PROGRESS", 0)
        comfy_chunk.start()
        self.addCleanup(comfy_chunk.stop)

    def fetch(self, *extra, set_="edit-set", lock=None):
        return self.run_comfy("models", "--fetch", set_, "--lock", lock or self.lockp, *extra)

    def test_plan_only_without_yes(self):
        code, out, err = self.fetch()
        self.assertEqual(code, 0, err)
        self.assertEqual(self.f.calls, [], "the plan contacts nothing")
        self.assertFalse(self.dest.exists())
        self.assertFalse(Path(str(self.dest) + ".part").exists())
        self.assertIn("licence: Apache-2.0 (test)", out)
        self.assertRegex(out, r"fetch +diffusion_models/qwen_image_edit_2511_fp8mixed\.safetensors +0\.00 GB  "
                              r"hf Org/Repo@main:split_files/diffusion_models/qwen_image_edit_2511_fp8mixed\.safetensors"
                              r" · sha256 = the HF LFS oid")
        self.assertRegex(out, r"to download: 1 file\(s\), 0\.00 GB · .* free [0-9.]+ GB \(after: ")
        self.assertIn("plan only: nothing downloaded. Ask the owner first", out)
        self.assertIn("models --fetch edit-set --yes", out)

    def test_yes_downloads_checks_sha_and_renames(self):
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.dest.read_bytes(), self.DATA)
        self.assertFalse(Path(str(self.dest) + ".part").exists())
        self.assertIn(f"sha256 {hashlib.sha256(self.DATA).hexdigest()[:16]}", out)
        self.assertIn("1/1 downloaded", out)
        self.assertTrue(any(c.startswith("/api/models/Org/Repo/tree/main/split_files/diffusion_models")
                            for c in self.f.calls))
        self.assertTrue(any(c.startswith("/cdn/Org/Repo/resolve/main/") for c in self.f.calls), "redirect followed")
        code, out, _ = self.fetch("--yes")                                 # second time: present, nothing fetched
        self.assertEqual(code, 0)
        self.assertIn("nothing to download", out)

    def test_resume_with_range(self):
        part = Path(str(self.dest) + ".part")
        part.parent.mkdir(parents=True)
        part.write_bytes(self.DATA[:1000])
        code, out, err = self.fetch()
        self.assertIn("resume at 0.00 GB", out)
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.f.ranges, ["bytes=1000-"])
        self.assertEqual(self.dest.read_bytes(), self.DATA)
        self.assertIn("resuming", out)

    def test_server_ignoring_range_restarts(self):
        part = Path(str(self.dest) + ".part")
        part.parent.mkdir(parents=True)
        part.write_bytes(b"x" * 1000)                                      # garbage: must not stay in the file
        self.f.ignore_range = True
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 0, err)
        self.assertIn("ignored the Range request", out)
        self.assertEqual(self.dest.read_bytes(), self.DATA)

    def test_hash_mismatch_keeps_bad_and_makes_no_file(self):
        self.f.serve[self.key] = bytes(len(self.DATA))                      # right size, wrong bytes
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 1, out + err)
        self.assertFalse(self.dest.exists())
        self.assertTrue(Path(str(self.dest) + ".bad").exists())
        self.assertIn("sha256", err)
        self.assertIn("not used", err)

    def test_lock_pin_must_match_hf(self):
        lockp = self.lock([dict(self.e, sha256="0" * 64)])
        code, _, err = self.fetch("--yes", lock=lockp)
        self.assertEqual(code, 2, err)
        self.assertIn("the lock pins sha256 0000000000000000..., Hugging Face has", err)
        self.assertFalse(any("/resolve/" in c for c in self.f.calls), "nothing downloaded")
        lockp = self.lock([dict(self.e, size=len(self.DATA) + 1)])
        code, _, err = self.fetch("--yes", lock=lockp)
        self.assertEqual(code, 2, err)
        self.assertIn("Hugging Face has 3004 bytes, the lock 3005", err)
        self.assertFalse(self.dest.exists())

    def test_missing_on_hf_downloads_nothing(self):
        lockp = self.lock([self.e, self.entry("other.safetensors", b"abc", path="nowhere/other.safetensors")])
        code, _, err = self.fetch("--yes", lock=lockp)
        self.assertEqual(code, 1, err)
        self.assertIn("is not in the listing of Org/Repo@main", err)
        self.assertFalse(any("/resolve/" in c for c in self.f.calls))
        self.assertFalse(self.dest.exists())

    def test_never_overwrites(self):
        self.put(f"diffusion_models/{self.e['file']}", b"another file")
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 2, out + err)
        self.assertIn("never overwritten", out)
        self.assertEqual(self.dest.read_bytes(), b"another file")
        self.assertEqual(self.f.calls, [])
        with self.assertRaises(FileExistsError):
            comfy.download_verified(self.f.url + "/x", str(self.dest), 3, "0" * 64)

    def test_names_with_control_chars_are_refused(self):
        bad = self.lock([dict(self.e, file=self.e["file"] + "\r")])
        code, _, err = self.fetch(lock=bad)
        self.assertEqual(code, 2)
        self.assertIn("control character(s) '\\r'", err)
        for field, value in (("folder", "diffusion_models\n"), ("folder", "../up"), ("file", "a/b.safetensors"),
                             ("file", " x.safetensors")):
            code, _, err = self.fetch(lock=self.lock([dict(self.e, **{field: value})]))
            self.assertEqual(code, 2, (field, value))
        code, _, err = self.fetch(lock=self.lock([dict(self.e, hf=dict(self.e["hf"], path="x/../y.safetensors"))]))
        self.assertEqual(code, 2)
        code, _, err = self.fetch(lock=self.lock([dict(self.e, hf=dict(self.e["hf"], path="x/other.safetensors"))]))
        self.assertEqual(code, 2)
        self.assertIn("must end in the file name", err)
        code, out, err = self.fetch(set_="edit-set\r\n")                     # a CLI name from a pipe: stripped
        self.assertEqual(code, 0, err)
        self.assertIn("blanks/line ends around the name dropped", err)
        code, _, err = self.fetch(set_="edit\x07set")
        self.assertEqual(code, 2)
        self.assertIn("control character", err)
        self.assertEqual(self.f.calls, [])

    def test_agent_cannot_download_and_space_is_checked(self):
        os.environ["FILM_AGENT"] = "film-3d-artist"
        code, out, err = self.fetch("--yes")
        self.assertEqual(code, 2, err)
        self.assertIn("main session only", err)
        self.assertEqual(self.f.calls, [])
        code, out, err = self.fetch()                                       # the plan is fine for an agent
        self.assertEqual(code, 0, err)
        os.environ.pop("FILM_AGENT")
        full = mock.Mock(free=1024, total=2048, used=1024)
        with mock.patch.object(comfy.shutil, "disk_usage", return_value=full):
            code, _, err = self.fetch("--yes")
        self.assertEqual(code, 2)
        self.assertIn("not enough space", err)
        self.assertFalse(self.dest.exists())

    def test_set_without_source_or_unknown(self):
        code, _, err = self.run_comfy("models", "--fetch", "minimax-h3")    # the real lock: no HF source pinned
        self.assertEqual(code, 2, err)
        self.assertIn("cannot be fetched safely", err)
        code, _, err = self.run_comfy("models", "--fetch", "nope")
        self.assertEqual(code, 2)
        self.assertIn("the lock has ", err)


class TestRealLock(ModelsCase):
    def test_new_sets(self):
        lock = comfy.load_lock()
        by = {m["file"]: m for m in lock["models"]}
        want = {"qwen_image_edit_2511_fp8mixed.safetensors": ("qwen-image-edit-2511", "diffusion_models", 20533762817,
                                                              "Comfy-Org/Qwen-Image-Edit_ComfyUI"),
                "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors": ("qwen-image-edit-2511", "loras",
                                                                                849608296, "lightx2v/Qwen-Image-Edit-2511-Lightning"),
                "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors": ("qwen-image-edit-2511", "loras",
                                                                                849608296, "lightx2v/Qwen-Image-Edit-2511-Lightning"),
                "hunyuan_3d_v2.1.safetensors": ("hunyuan3d-2.1", "checkpoints", 7365943290,
                                                "Comfy-Org/hunyuan3D_2.1_repackaged")}
        for f, (s, folder, size, repo) in want.items():
            m = by[f]
            self.assertEqual((m["set"], m["folder"], m["size"], m["hf"]["repo"]), (s, folder, size, repo), f)
            self.assertTrue(m["hf"]["path"].endswith(f))
            self.assertIsNone(m["sha256"])                                  # unknown: never hashed on C:
            self.assertTrue(m["license"])
        self.assertIn("không áp dụng EU/UK/Hàn Quốc", by["hunyuan_3d_v2.1.safetensors"]["license"])
        self.assertIn("Tencent Hunyuan", lock["sets"]["hunyuan3d-2.1"]["license"])

    def test_real_lock_plan_lists_the_edit_set(self):
        roomy = mock.Mock(free=500 * 10**9, total=1000 * 10**9, used=500 * 10**9)
        with mock.patch.object(comfy.shutil, "disk_usage", return_value=roomy):
            code, out, err = self.run_comfy("models", "--fetch", "qwen-image-edit-2511")
        self.assertEqual(code, 0, err)
        self.assertIn("also uses set qwen-image: 0/4 present", out)
        self.assertIn("to download: 3 file(s), 22.23 GB", out)
        self.assertIn("plan only: nothing downloaded", out)


if __name__ == "__main__":
    unittest.main()
