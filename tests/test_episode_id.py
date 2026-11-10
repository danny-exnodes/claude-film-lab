"""Episode ids ep<NN> and q<NN>t<NN> (book numbering) across tools, and tools/rename_episode.py."""
import json, os, re, shutil, unittest, zipfile

from helpers import EPISODE_FIX, TmpDirCase, load, run_main

eid = load("episode_id.py", "film_episode_id")
ce = load("check_episode.py", "film_check_episode_ids")
bundle = load("bundle.py", "film_bundle_ids")
ds = load("drive_sync.py", "film_drive_sync_ids")
ren = load("rename_episode.py", "film_rename_episode")
anchors = load("layers/anchors.py", "film_anchors_ids")
matte = load("layers/matte.py", "film_matte_ids")

PLATES = ["s01_L1_nui-co_v01.png", "s02_L4_bac-thi_v02.png", "s02_P1-duoi_bac-thi_v01.png"]


class TestEpisodeIdModule(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(eid.make_id(1), "ep01")
        self.assertEqual(eid.make_id(3, 2), "q02t03")
        self.assertEqual(eid.parse_id("ep07"), (None, 7))
        self.assertEqual(eid.parse_id("q01t12"), (1, 12))
        for bad in ("ep1", "q1t1", "q01-t01", "e01", "q01t01x", ""):
            self.assertIsNone(eid.parse_id(bad), bad)

    def test_dirs(self):
        self.assertEqual(eid.parse_dir("ep01-bac-thi"), ("ep01", "bac-thi"))
        self.assertEqual(eid.parse_dir("q01-t01-nam-son-kinh"), ("q01t01", "nam-son-kinh"))
        self.assertIsNone(eid.parse_dir("q01t01-nam-son-kinh"))
        self.assertIsNone(eid.parse_dir("ep01_bac"))
        self.assertEqual(eid.dir_name("q01t01", "nam-son-kinh"), "q01-t01-nam-son-kinh")
        self.assertEqual(eid.dir_name("ep02", "x"), "ep02-x")

    def test_file_prefix_and_display(self):
        self.assertEqual(eid.file_id("q01t01_s03_L4_bac-di_v02.png"), "q01t01")
        self.assertEqual(eid.file_id("ep01_draft_v01.mp4"), "ep01")
        self.assertIsNone(eid.file_id("s03_L4.png"))
        self.assertEqual(eid.display("q01t01"), "Quyển 1 · Tập 1")
        self.assertEqual(eid.display("ep04"), "Tập 4")

    def test_tool_regexes_accept_both(self):
        for name in ("ep01_s03_L4_bac-di_v02.png", "q01t01_s03_L4_bac-di_v02.png"):
            self.assertTrue(ce.RE_LAYER_FILE.match(name), name)
            self.assertTrue(anchors.RE_LAYER_FILE.match(name), name)
            self.assertEqual(matte.RE_LAYER.match(name).group(1), "L4")
        for name in ("ep01_s03_seedance25_v01.mp4", "q01t01_s03_seedance25_v01.mp4"):
            self.assertTrue(ce.RE_CLIP_FILE.match(name), name)
        for name in ("ep01_draft_v01.mp4", "q01t01_final_v02.mp4"):
            self.assertTrue(ce.RE_RENDER_FILE.match(name), name)
        self.assertTrue(ce.RE_START_FRAME.match("q01t01_s03_start_v01.png"))
        self.assertTrue(ce.RE_CLIP_STEM.match("q01t01_s03_seedance25_v01"))
        for bad in ("q1t1_s03_L4_x_v01.png", "q01-t01_s03_L4_x_v01.png", "Q01T01_s03_L4_x_v01.png"):
            self.assertFalse(ce.RE_LAYER_FILE.match(bad), bad)


def make_episode(root, eid_, folder, book=None):
    """Fixture episode (ep01 text) rewritten for id eid_ under root/projects/test-series/<folder>, with media."""
    ep = root / "projects" / "test-series" / folder
    shutil.copytree(EPISODE_FIX, ep)
    for name in ("EPISODE.md", "prompts.csv", "anchors.json"):
        p = ep / name
        s = p.read_text(encoding="utf-8").replace("ep01_", eid_ + "_").replace("ep01-test-ep", folder)
        s = s.replace("out/test-series/ep01", f"out/test-series/{eid_}")
        if name == "EPISODE.md" and book is not None:
            s = s.replace("episode: 1", f"book: {book}\nepisode: 1")
        p.write_text(s, encoding="utf-8")
    media = root / "out" / "test-series" / eid_
    for sub, names in (("plates", [f"{eid_}_{n}" for n in PLATES]), ("clips", [f"{eid_}_s02_seedance25_v01.mp4"]),
                       ("renders", [f"{eid_}_draft_v01.mp4"])):
        (media / sub).mkdir(parents=True)
        for n in names:
            (media / sub / n).write_bytes(b"x")
    (media / "ledger.csv").write_text(",".join(ce.LEDGER_HEADER) + "\n"
                                      f"2026,image,m,2K,,1,ok,out/test-series/{eid_}/plates/{eid_}_{PLATES[0]},,,,\n")
    return ep, media


class BookCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep, self.media = make_episode(self.tmp, "q01t01", "q01-t01-test-ep", book=1)

    def check(self, ep=None, media=None):
        return run_main(ce.main, ["episode", str(ep or self.ep), "--media", str(media or self.media)])

    def edit(self, name, old, new):
        p = self.ep / name
        s = p.read_text(encoding="utf-8")
        self.assertIn(old, s)
        p.write_text(s.replace(old, new, 1), encoding="utf-8")

    def assert_error(self, pattern, **kw):
        code, out, _ = self.check(**kw)
        self.assertEqual(code, 1, out)
        self.assertTrue(any(l.startswith("ERROR") and re.search(pattern, l) for l in out.splitlines()),
                        f"no ERROR matching {pattern!r} in:\n{out}")


class TestCheckEpisodeBooks(BookCase):
    def test_book_episode_passes(self):
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("Summary: 0 error(s)", out)
        self.assertNotIn("differs from the convention", out)
        self.assertNotIn("unknown front matter key 'book'", out)

    def test_ep_scheme_still_passes(self):
        ep, media = make_episode(self.tmp / "b", "ep01", "ep01-test-ep")
        code, out, _ = self.check(ep, media)
        self.assertEqual(code, 0, out)

    def test_book_missing_for_book_folder(self):
        self.edit("EPISODE.md", "book: 1\n", "")
        self.assert_error(r"episode 1 != folder number q01-t01 \(folder uses books: set 'book:'\)")

    def test_book_number_mismatch(self):
        self.edit("EPISODE.md", "book: 1", "book: 2")
        self.assert_error(r"book 2, episode 1 != folder number q01-t01")

    def test_book_set_on_ep_folder(self):
        ep, media = make_episode(self.tmp / "b", "ep01", "ep01-test-ep", book=1)
        self.assert_error(r"book 1, episode 1 != folder number ep01 \(folder has no book", ep=ep, media=media)

    def test_bad_book_value(self):
        self.edit("EPISODE.md", "book: 1", "book: one")
        self.assert_error(r"book 'one' must be an integer")

    def test_media_folder_must_match_id(self):
        other = self.media.parent / "ep01"
        shutil.copytree(self.media, other)
        self.assert_error(r"media folder 'ep01' does not match episode id 'q01t01'", media=other)

    def test_file_prefix_must_match_id(self):
        (self.media / "plates" / "ep01_s01_L1_nui-co_v03.png").write_bytes(b"x")
        self.assert_error(r"media/plates/ep01_s01_L1_nui-co_v03.png: file is not for episode q01t01")

    def test_prompts_prefix_must_match_id(self):
        self.edit("prompts.csv", "q01t01_s02_P1-duoi", "q01t02_s02_P1-duoi")
        self.assert_error(r"file 'q01t02_s02_P1-duoi_bac-thi_v01.png' is not for episode q01t01")

    def test_media_and_drive_convention_warn(self):
        self.edit("EPISODE.md", "03_KichBan/q01-t01-test-ep", "03_KichBan/ep01-test-ep")
        code, out, _ = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("'ClaudeFilmLab/<ProjectName>/03_KichBan/q01-t01-test-ep'", out)


class TestBundleBooks(BookCase):
    def test_bundle_q_episode(self):
        code, out, err = run_main(bundle.main, [str(self.media), "--shot", "s02", "--episode-dir", str(self.ep)])
        self.assertEqual(code, 0, err)
        zips = list((self.media / "bundles").glob("q01t01_s02_*.zip"))
        self.assertEqual(len(zips), 1, out)
        with zipfile.ZipFile(zips[0]) as z:
            names = set(z.namelist())
            self.assertIn("plates/q01t01_s02_L4_bac-thi_v02.png", names)
            self.assertIn("prompts.csv", names)
            self.assertIn("q01t01_s02_L4_bac-thi_v02.png", json.loads(z.read("anchors.json")))

    def test_bundle_rejects_other_folder(self):
        bad = self.media.parent / "q1t1"
        bad.mkdir()
        code, _, err = run_main(bundle.main, [str(bad), "--shot", "s02"])
        self.assertNotEqual(code, 0)
        self.assertIn("q<NN>t<NN>", err)


class TestDriveSyncBooks(TmpDirCase, unittest.TestCase):
    MAN = ("---\nproject: demo\ntitle: Demo\nstyle: thuy-mac\ndrive:\n  name: Demo\n  lab_root: L\n  root: R\n"
           "  folders:\n    03_KichBan: F-KB\n    03_KichBan/q01-t01-nam-son: F-KB-Q1\n    04_SanXuat: F-SX\n"
           "    04_SanXuat/q01-t01-nam-son: F-SX-Q1\n    05_ThanhPham: F-TP\n    05_ThanhPham/q01-t01-nam-son: F-TP-Q1\n"
           "    99_LuuTru: F-LT\n  files: {}\n---\n")

    def test_map_project_book_folder(self):
        self.assertEqual(ds.map_project("q01-t01-nam-son/script.md"), "03_KichBan/q01-t01-nam-son")
        self.assertEqual(ds.map_project("q01-t01-nam-son/prompts/a.txt"), "03_KichBan/q01-t01-nam-son/prompts")
        self.assertEqual(ds.map_project("ep01-bac-thi/script.md"), "03_KichBan/ep01-bac-thi")
        self.assertIsNone(ds.map_project("q01t01-nam-son/script.md"))

    def test_plan_media_book(self):
        pd, out = self.tmp / "projects" / "demo", self.tmp / "out" / "demo"
        (pd / "q01-t01-nam-son").mkdir(parents=True)
        (pd / "PROJECT.md").write_text(self.MAN, encoding="utf-8")
        (pd / "q01-t01-nam-son" / "script.md").write_text("[00:00] a\n", encoding="utf-8")
        for rel in ("ledger.csv", "bundles/q01t01_s01_20261109.zip", "renders/q01t01_draft_v01.mp4",
                    "renders/q01t01_final_v01.mp4"):
            (out / "q01t01" / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / "q01t01" / rel).write_bytes(b"x")
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            code, so, err = run_main(ds.main, ["plan", "projects/demo", "--include-out", "out/demo", "--json",
                                               "--now", "20261110-1530", "--date", "2026-11-10"])
        finally:
            os.chdir(cwd)
        self.assertEqual(code, 1, err + so)   # dated 04_SanXuat/<folder>/<YYYY-MM-DD> folders still to create
        folders = {a["local"]: a["folder"]["path"] for a in json.loads(so)["actions"]}
        self.assertEqual(folders["projects/demo/q01-t01-nam-son/script.md"], "03_KichBan/q01-t01-nam-son")
        self.assertEqual(folders["out/demo/q01t01/ledger.csv"], "04_SanXuat/q01-t01-nam-son")
        self.assertEqual(folders["out/demo/q01t01/bundles/q01t01_s01_20261109.zip"], "04_SanXuat/q01-t01-nam-son/2026-11-09")
        self.assertEqual(folders["out/demo/q01t01/renders/q01t01_draft_v01.mp4"], "04_SanXuat/q01-t01-nam-son/2026-11-10")
        self.assertEqual(folders["out/demo/q01t01/renders/q01t01_final_v01.mp4"], "05_ThanhPham/q01-t01-nam-son")


class TestRenameEpisode(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ep, self.media = make_episode(self.tmp, "ep01", "ep01-test-ep")
        clip_frames = self.media / "clips" / "ep01_s02_seedance25_v01"
        (clip_frames / "raw").mkdir(parents=True)
        (clip_frames / "000001.png").write_bytes(b"x")
        (clip_frames / "raw" / "000001.png").write_bytes(b"x")
        (self.ep / "prompts" / "ep01_s02_seedance25_v01.txt").write_text("clip prompt\n", encoding="utf-8")
        self.edit_prompts = self.ep / "prompts.csv"
        s = self.edit_prompts.read_text(encoding="utf-8")
        self.edit_prompts.write_text(s.replace("prompts/s02_L4.txt,,,,,", "prompts/ep01_s02_seedance25_v01.txt,,,,,"),
                                     encoding="utf-8")
        (self.ep.parent / "PROJECT.md").write_text(
            "---\ndrive:\n  folders:\n    03_KichBan/ep01-test-ep: F1\n    04_SanXuat/ep01-test-ep: F2\n---\n",
            encoding="utf-8")

    def run_rename(self, old="ep01", new="q01t01", *extra, ep=None, media=None):
        return run_main(ren.main, [old, new, "--project-dir", str(ep or self.ep),
                                   "--media", str(media or self.media), *extra])

    def tree(self):
        return sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob("*"))

    def test_dry_run_changes_nothing(self):
        before = self.tree()
        texts = {p: p.read_bytes() for p in self.tmp.rglob("*") if p.is_file()}
        code, out, err = self.run_rename()
        self.assertEqual(code, 0, err)
        self.assertIn("dry run", out)
        self.assertIn("-> q01-t01-test-ep", out)
        self.assertIn("-> q01t01_s02_seedance25_v01", out)
        self.assertEqual(self.tree(), before)
        self.assertTrue(all(p.read_bytes() == b for p, b in texts.items()))

    def test_apply_then_check_passes(self):
        code, out, err = self.run_rename("ep01", "q01t01", "--apply")
        self.assertEqual(code, 0, err)
        new_ep = self.tmp / "projects" / "test-series" / "q01-t01-test-ep"
        new_media = self.tmp / "out" / "test-series" / "q01t01"
        self.assertFalse(self.ep.exists())
        self.assertFalse(self.media.exists())
        self.assertFalse([p for p in self.tmp.rglob("ep01*")], self.tree())
        self.assertTrue((new_media / "clips" / "q01t01_s02_seedance25_v01" / "raw" / "000001.png").is_file())
        self.assertTrue((new_ep / "prompts" / "q01t01_s02_seedance25_v01.txt").is_file())
        epmd = (new_ep / "EPISODE.md").read_text(encoding="utf-8")
        self.assertIn("book: 1\nepisode: 1\n", epmd)
        self.assertIn("media: out/test-series/q01t01\n", epmd)
        self.assertIn("03_KichBan/q01-t01-test-ep", epmd)
        prompts = (new_ep / "prompts.csv").read_text(encoding="utf-8")
        self.assertNotIn("ep01", prompts)
        self.assertIn("prompts/q01t01_s02_seedance25_v01.txt", prompts)
        self.assertIn("q01t01_s02_L4_bac-thi_v02.png", json.loads((new_ep / "anchors.json").read_text()))
        self.assertIn("out/test-series/q01t01/plates/q01t01_s01_", (new_media / "ledger.csv").read_text())
        man = (self.ep.parent / "PROJECT.md").read_text(encoding="utf-8")
        self.assertIn("03_KichBan/q01-t01-test-ep: F1", man)
        self.assertIn("04_SanXuat/q01-t01-test-ep: F2", man)
        code, out, _ = run_main(ce.main, ["episode", str(new_ep), "--media", str(new_media)])
        self.assertEqual(code, 0, out)

    def test_round_trip_back_to_ep(self):
        self.assertEqual(self.run_rename("ep01", "q01t01", "--apply")[0], 0)
        new_ep = self.tmp / "projects" / "test-series" / "q01-t01-test-ep"
        new_media = self.tmp / "out" / "test-series" / "q01t01"
        code, out, err = self.run_rename("q01t01", "ep01", "--apply", ep=new_ep, media=new_media)
        self.assertEqual(code, 0, err)
        epmd = (self.ep / "EPISODE.md").read_text(encoding="utf-8")
        self.assertNotIn("book:", epmd)
        self.assertIn("episode: 1\n", epmd)
        code, out, _ = run_main(ce.main, ["episode", str(self.ep), "--media", str(self.media)])
        self.assertEqual(code, 0, out)

    def test_refusals(self):
        before = self.tree()
        self.assertEqual(self.run_rename("ep01", "q1t1")[0], 2)
        self.assertEqual(self.run_rename("ep02", "q01t01")[0], 2)          # folder is not ep02
        (self.tmp / "out" / "test-series" / "q01t01").mkdir()
        code, _, err = self.run_rename("ep01", "q01t01", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)
        self.assertEqual(sorted(set(self.tree()) - {"out/test-series/q01t01"}), before)

    def test_does_not_touch_lookalikes(self):
        (self.ep / "script.md").write_text("> ghi chú: xep01_ và step01_ giữ nguyên, ep01 nói chung giữ nguyên\n"
                                           "[00:00] mở đầu\n", encoding="utf-8")
        self.assertEqual(self.run_rename("ep01", "q01t01", "--apply")[0], 0)
        s = (self.tmp / "projects" / "test-series" / "q01-t01-test-ep" / "script.md").read_text(encoding="utf-8")
        self.assertIn("xep01_ và step01_ giữ nguyên, ep01 nói chung", s)


if __name__ == "__main__":
    unittest.main()
