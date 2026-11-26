"""tools/drive_sync.py: snapshot / plan / record round trip on a temp project with fake Drive IDs (no network)."""
import base64, hashlib, json, os, re, shutil, subprocess, sys, time, unittest, zipfile

from helpers import FIX, TmpDirCase, load, run_main

ds = load("drive_sync.py", "film_drive_sync")

PROJECT_MD = """---
project: demo
title: Demo
style: thuy-mac
drive:
  name: Demo
  lab_root: LAB-ROOT
  root: ROOT-ID
  folders:
    00_QuanLy: F-QL
    01_TaiLieuGoc: F-TLG
    02_KinhThu: F-KT
    02_KinhThu/NhanVat: F-NV
    02_KinhThu/NhanVat/bac-thi: F-NV-BT
    02_KinhThu/BoiCanh: <id>
    03_KichBan: F-KB
    03_KichBan/ep01-bac-thi: F-KB-E1
    03_KichBan/ep01-bac-thi/prompts: F-KB-E1-P
    04_SanXuat: F-SX
    04_SanXuat/ep01-bac-thi: F-SX-E1
    05_ThanhPham: F-TP
    99_LuuTru: F-LT
  files:
    00_QuanLy/README_CauTruc: DOC-ID
    00_QuanLy/TienDo_SanXuat: SHEET-ID
---

# Demo
"""

FILES = {
    "PROJECT.md": PROJECT_MD,
    "SERIES.md": "# series\n",
    "TienDo_SanXuat.csv": "tap,khau\nep01,2\n",
    "characters/bac-thi/CHARACTER.md": "# Bac thi\n",
    "ep01-bac-thi/EPISODE.md": "---\nstage: 2\n---\n",
    "ep01-bac-thi/script.md": "[00:00] mo dau\n",
    "ep01-bac-thi/prompts/s01_L1.txt": "nui\n",
    "sources/DanhMuc.csv": "file,thu_muc,mo_ta,nguon,ngay_them\n",
    "sources/NguyenVan/shk_nam-son_01_co-son.txt": "nguyen van\n",
}


class DriveSyncCase(TmpDirCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.pd = self.tmp / "projects" / "demo"
        self.out = self.tmp / "out" / "demo"
        for rel, text in FILES.items():
            self.write(rel, text)
        (self.out / "ep01" / "plates").mkdir(parents=True)
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n")
        (self.out / "ep01" / "plates" / "ep01_s01_L1_nui_v01.png").write_bytes(b"png")
        self.cwd = os.getcwd()
        os.chdir(self.tmp)          # like the repo root: paths as `find projects/demo` prints them

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def write(self, rel, text, append=False):
        p = self.pd / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a" if append else "w", encoding="utf-8") as f:
            f.write(text)
        return p

    def run_tool(self, *argv):
        return run_main(ds.main, list(argv))

    def plan(self, *extra):
        code, out, err = self.run_tool("plan", "projects/demo", "--json", "--now", "20261110-1530", *extra)
        self.assertIn(code, (0, 1), err)
        return code, json.loads(out)

    def snapshot(self, *extra):
        code, out, err = self.run_tool("snapshot", "projects/demo", *extra)
        self.assertEqual(code, 0, err)
        return out

    def action(self, plan, local):
        hits = [a for a in plan["actions"] if a["local"] == local]
        self.assertEqual(len(hits), 1, f"{local} not planned once: {[a['local'] for a in plan['actions']]}")
        return hits[0]


class TestTempFiles(unittest.TestCase):
    def test_lock_and_swap_files_are_temp(self):
        for rel in ("ep01-x/anchors.json.lock", "ep01-x/script.md.swp", "ep01-x/notes.tmp", "ep01-x/a.md~"):
            self.assertTrue(ds.is_temp(rel), rel)
        for rel in ("ep01-x/anchors.json", "ep01-x/prompts/s01.txt", "PROJECT.md"):
            self.assertFalse(ds.is_temp(rel), rel)


class TestSnapshot(DriveSyncCase):
    def test_sha256sum_format_and_pulled_at(self):
        self.write(".hidden", "x")
        self.write("__pycache__/x.pyc", "x")
        self.snapshot()
        lines = (self.pd / ".pulled.sha256").read_text().splitlines()
        self.assertEqual(len(lines), len(FILES))
        for line in lines:
            self.assertRegex(line, r"^[0-9a-f]{64}  projects/demo/[^.]")
        self.assertFalse(any("__pycache__" in l or ".hidden" in l for l in lines))
        self.assertRegex((self.pd / ".pulled.at").read_text(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\n$")

    def test_include_out_keys(self):
        self.snapshot("--include-out", "out/demo")
        text = (self.pd / ".pulled.sha256").read_text()
        self.assertIn("  out/demo/ep01/ledger.csv\n", text)

    def test_reads_shell_snapshot(self):
        """A snapshot made by the §11.6 shell command (relative paths from the repo root) is understood."""
        snap = ds.read_snapshot(str(self.pd))
        self.assertIsNone(snap)
        lines = [f"{ds.sha256(self.pd / r)}  ./projects/demo/{r}" for r in sorted(FILES)]
        (self.pd / ".pulled.sha256").write_text("\n".join(lines) + "\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["counts"]["unchanged"], len(FILES))

    def test_bad_snapshot_line(self):
        (self.pd / ".pulled.sha256").write_text("not a hash line\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("not a sha256sum line", err)


class TestPlan(DriveSyncCase):
    def test_nothing_after_snapshot(self):
        self.snapshot()
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 0, out)
        self.assertIn("Nothing to push.", out)

    def test_changed_vs_new(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        code, plan = self.plan()
        self.assertEqual(code, 0)
        self.assertEqual(plan["counts"]["changed"], 1)
        self.assertEqual(plan["counts"]["new"], 1)

        ch = self.action(plan, "projects/demo/ep01-bac-thi/script.md")
        self.assertEqual(ch["status"], "changed")
        self.assertEqual(ch["folder"], {"path": "03_KichBan/ep01-bac-thi", "id": "F-KB-E1", "missing": []})
        cf = ch["create_file"]
        self.assertEqual((cf["title"], cf["parentId"], cf["contentMimeType"]), ("script.md", "F-KB-E1", "text/markdown"))
        self.assertTrue(cf["disableConversionToGoogleType"])
        self.assertEqual(cf["base64Content"], f"sha256:{ds.sha256(script)}:{script.resolve()}")
        ar = ch["archive"]
        self.assertEqual(ar["search_files"], "parentId = 'F-KB-E1' and title = 'script.md' and trashed = false")
        self.assertEqual(ar["parentId"], "F-LT")
        self.assertEqual(ar["title"], "03_KichBan__ep01-bac-thi__script_20261110-1530.md")
        self.assertNotIn("fileId", ar)            # old versions are found at archive time, never remembered
        self.assertEqual(ar["when"], "always")
        self.assertNotIn("condition", ar)

        new = self.action(plan, "projects/demo/ep01-bac-thi/prompts/s02_L4.txt")
        self.assertEqual(new["status"], "new")
        self.assertEqual(new["archive"]["search_files"],
                         "parentId = 'F-KB-E1-P' and title = 's02_L4.txt' and trashed = false")
        self.assertEqual(new["archive"]["title"], "03_KichBan__ep01-bac-thi__prompts__s02_L4_20261110-1530.txt")
        self.assertEqual(new["archive"]["when"], "if_exists")
        self.assertEqual(new["archive"]["condition"], ds.IF_EXISTS)
        self.assertEqual(new["folder"]["id"], "F-KB-E1-P")
        self.assertEqual(new["create_file"]["contentMimeType"], "text/plain")

    def test_mapping_table(self):
        cases = {
            "PROJECT.md": "00_QuanLy", "SERIES.md": "02_KinhThu", "pronunciation.csv": "02_KinhThu",
            "characters/bac-thi/CHARACTER.md": "02_KinhThu/NhanVat/bac-thi",
            "locations/co-son/LOCATION.md": "02_KinhThu/BoiCanh/co-son",
            "style/notes.md": "02_KinhThu/PhongCach",
            "ep01-bac-thi/review/qc-v1.md": "03_KichBan/ep01-bac-thi/review",
            "sources/DanhMuc.csv": "01_TaiLieuGoc",
            "sources/SachThamKhao/SHK_Quach/a.txt": "01_TaiLieuGoc/SachThamKhao/SHK_Quach",
            "notes.txt": None, "random/x.md": None, "ep01-bac-thi/pronunciation.csv": "03_KichBan/ep01-bac-thi",
            "style/pronunciation.csv": "02_KinhThu/PhongCach",
        }
        for rel, folder in cases.items():
            self.assertEqual(ds.map_project(rel), folder, rel)

    def test_project_md_last(self):
        self.write("PROJECT.md", "\n<!-- 2026-11-10 them thu muc -->\n", append=True)
        self.write("SERIES.md", "x\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["actions"][-1]["local"], "projects/demo/PROJECT.md")
        self.assertTrue(plan["warnings"][0].startswith("no .pulled.sha256"))

    def test_missing_folder(self):
        self.snapshot()
        self.write("locations/co-son/LOCATION.md", "# Co son\n")      # 02_KinhThu/BoiCanh is a <id> placeholder
        self.write("ep02-cuu-vi/EPISODE.md", "x\n")
        code, plan = self.plan()
        self.assertEqual(code, 1)
        loc = self.action(plan, "projects/demo/locations/co-son/LOCATION.md")
        self.assertIsNone(loc["folder"]["id"])
        self.assertIsNone(loc["create_file"]["parentId"])
        self.assertEqual([c["path"] for c in loc["folder"]["missing"]],
                         ["02_KinhThu/BoiCanh", "02_KinhThu/BoiCanh/co-son"])
        self.assertEqual(loc["folder"]["missing"][0]["parent_id"], "F-KT")
        self.assertIsNone(loc["folder"]["missing"][1]["parent_id"])
        self.assertEqual([c["path"] for c in plan["create_folders"]],
                         ["02_KinhThu/BoiCanh", "03_KichBan/ep02-cuu-vi", "02_KinhThu/BoiCanh/co-son"])
        _, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("02_KinhThu/BoiCanh/co-son = MISSING – create folder 02_KinhThu/BoiCanh under F-KT first", out)
        self.assertIn("03_KichBan/ep02-cuu-vi = MISSING – create folder 03_KichBan/ep02-cuu-vi under F-KB first", out)

    def test_unmapped_file_blocks(self):
        self.snapshot()
        self.write("notes.txt", "x")
        code, plan = self.plan()
        self.assertEqual(code, 1)
        self.assertEqual([u["local"] for u in plan["unmapped"]], ["projects/demo/notes.txt"])

    def test_pronunciation_csv(self):
        """Project-level Hán Việt map (tools/tts --pron) goes next to SERIES.md, not UNMAPPED."""
        self.snapshot()
        pron = self.write("pronunciation.csv", "term,doc\nChiêu Diêu,Chiêu Diêu\n")
        code, plan = self.plan()
        self.assertEqual(code, 0)
        self.assertEqual(plan["unmapped"], [])
        x = self.action(plan, "projects/demo/pronunciation.csv")
        self.assertEqual(x["folder"], {"path": "02_KinhThu", "id": "F-KT", "missing": []})
        self.assertEqual((x["create_file"]["title"], x["create_file"]["contentMimeType"]),
                         ("pronunciation.csv", "text/csv"))
        self.assertTrue(x["create_file"]["disableConversionToGoogleType"])
        self.assertEqual(x["create_file"]["base64Content"], f"sha256:{ds.sha256(pron)}:{pron.resolve()}")
        self.assertEqual(x["archive"]["title"], "02_KinhThu__pronunciation_20261110-1530.csv")

    def test_template_pronunciation_csv(self):
        tpl = os.path.join(os.path.dirname(ds.__file__), "..", "templates", "project", "pronunciation.csv")
        with open(tpl, encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), ["term,doc"])

    def test_new_file_archive_if_exists(self):
        """No snapshot line (first push after a manual upload, lost snapshot): still search and archive duplicates."""
        os.remove(self.pd / "SERIES.md")
        self.snapshot()
        self.write("SERIES.md", "# series\n")
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/SERIES.md")
        self.assertEqual(x["status"], "new")
        ar = x["archive"]
        self.assertEqual(ar["search_files"], "parentId = 'F-KT' and title = 'SERIES.md' and trashed = false")
        self.assertEqual((ar["parentId"], ar["title"], ar["when"]),
                         ("F-LT", "02_KinhThu__SERIES_20261110-1530.md", "if_exists"))
        _, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        block = out.split("NEW     projects/demo/SERIES.md", 1)[1]
        self.assertIn("archive      if a file with this title already exists in the folder (first push), archive it:",
                      block)
        self.assertIn("search_files parentId = 'F-KT' and title = 'SERIES.md' and trashed = false", block)
        self.assertIn("title=02_KinhThu__SERIES_20261110-1530.md", block)
        self.assertIn("Before uploading a NEW file", out)

    def test_no_snapshot_every_file_has_archive(self):
        code, plan = self.plan()
        self.assertTrue(plan["actions"])
        for x in plan["actions"]:
            self.assertEqual(x["archive"]["when"], "if_exists", x["local"])

    def test_sheet_is_apart(self):
        self.snapshot()
        self.write("TienDo_SanXuat.csv", "ep02,0\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        sh = plan["sheet"]
        self.assertEqual(sh["create_file"]["title"], "TienDo_SanXuat")
        self.assertFalse(sh["create_file"]["disableConversionToGoogleType"])
        self.assertEqual(sh["archive"]["title"], "00_QuanLy__TienDo_SanXuat_20261110-1530")
        self.assertEqual(sh["archive"]["drive_files_id"], "SHEET-ID")

    def test_sources_are_read_only_except_catalog(self):
        self.snapshot()
        self.write("sources/NguyenVan/shk_nam-son_01_co-son.txt", "sua\n", append=True)
        self.write("sources/DanhMuc.csv", "a.txt,NguyenVan,x,y,2026-11-10\n", append=True)
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/sources/DanhMuc.csv"])
        self.assertEqual(plan["actions"][0]["folder"]["id"], "F-TLG")
        self.assertTrue(any("never edited" in w for w in plan["warnings"]))

    def test_deleted_locally(self):
        self.snapshot()
        os.remove(self.pd / "SERIES.md")
        code, plan = self.plan()
        self.assertEqual(plan["deleted"], ["projects/demo/SERIES.md"])

    def test_include_out(self):
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261109.zip").write_bytes(b"zip")
        (self.out / "ep01" / "renders").mkdir()
        (self.out / "ep01" / "renders" / "ep01_draft_v01.mp4").write_bytes(b"mp4")
        (self.out / "ep01" / "renders" / "ep01_final_v01.mp4").write_bytes(b"mp4")
        (self.out / "ep01" / "plates" / "ep01_s02_L1_nui_v01.png").write_bytes(b"png")
        code, plan = self.plan("--include-out", "out/demo", "--date", "2026-11-10")
        led = self.action(plan, "out/demo/ep01/ledger.csv")
        self.assertEqual((led["status"], led["folder"]["id"]), ("changed", "F-SX-E1"))
        self.assertEqual(led["archive"]["title"], "04_SanXuat__ep01-bac-thi__ledger_20261110-1530.csv")
        self.assertEqual(self.action(plan, "out/demo/ep01/bundles/ep01_s01_20261109.zip")["folder"]["path"],
                         "04_SanXuat/ep01-bac-thi/2026-11-09")
        draft = self.action(plan, "out/demo/ep01/renders/ep01_draft_v01.mp4")
        self.assertEqual(draft["folder"]["path"], "04_SanXuat/ep01-bac-thi/_ChuaDuyet")     # pushed before approval
        self.assertEqual(draft["create_file"]["contentMimeType"], "video/mp4")
        self.assertEqual(draft["unapproved"], {"move_when_approved": "04_SanXuat/ep01-bac-thi/2026-11-10",
                                               "parentId": None})
        final = self.action(plan, "out/demo/ep01/renders/ep01_final_v01.mp4")
        self.assertEqual(final["folder"],
                         {"path": "04_SanXuat/ep01-bac-thi/_ChuaDuyet", "id": None,
                          "missing": [{"path": "04_SanXuat/ep01-bac-thi/_ChuaDuyet", "name": "_ChuaDuyet",
                                       "parent_path": "04_SanXuat/ep01-bac-thi", "parent_id": "F-SX-E1"}]})
        self.assertEqual(final["unapproved"]["move_when_approved"], "05_ThanhPham/ep01-bac-thi")
        self.assertIn("update_file <new ID> parentId=<ID of 05_ThanhPham/ep01-bac-thi>", " ".join(final["notes"]))
        self.assertEqual(plan["skipped_media"], 2)      # plates travel inside bundles
        self.assertFalse(any("plates" in a["local"] for a in plan["actions"]))

    def test_unsaved_media(self):
        """Renders, takes and stems not on Drive: mapped to _ChuaDuyet/ and announced loudly, even without
        --include-out; a recorded upload makes them saved."""
        self.snapshot("--include-out", "out/demo")
        ep = self.out / "ep01"
        for rel, data in (("renders/ep01_draft_v01.mp4", b"mp4"), ("vo/VO1.wav", b"w1"), ("vo/VO2.wav", b"w2"),
                          ("vo/tts-log.json", b"[]"), ("vo/_stale/VO3.wav", b"old"), ("vo/VO4.wav.raw.wav", b"t"),
                          ("audio/music.wav", b"m"), ("audio/v02/foley.wav", b"f"), ("renders/sub/x.png", b"p")):
            (ep / rel).parent.mkdir(parents=True, exist_ok=True)
            (ep / rel).write_bytes(data)
        code, plan = self.plan("--include-out", "out/demo", "--date", "2026-11-26")
        u = plan["unsaved_media"]
        self.assertEqual(u["by_kind"], {"renders": 1, "vo": 3, "audio": 2})
        self.assertIn("out/demo/ep01/vo/VO1.wav", u["files"])
        self.assertNotIn("out/demo/ep01/vo/_stale/VO3.wav", u["files"])
        self.assertEqual(self.action(plan, "out/demo/ep01/vo/VO1.wav")["folder"]["path"],
                         "04_SanXuat/ep01-bac-thi/_ChuaDuyet/vo")
        self.assertEqual(self.action(plan, "out/demo/ep01/audio/v02/foley.wav")["folder"]["path"],
                         "04_SanXuat/ep01-bac-thi/_ChuaDuyet/audio/v02")
        self.assertIsNone(self.action(plan, "out/demo/ep01/vo/VO1.wav")["unapproved"]["move_when_approved"])
        self.assertFalse(any("_stale" in a["local"] or "sub/x.png" in a["local"] for a in plan["actions"]))

        code, out, _ = self.run_tool("plan", "projects/demo")          # text only: the media are still announced
        self.assertIn("!!! UNSAVED MEDIA: 6 file(s) not on Drive (renders 1, vo 3, audio 2)", out)
        self.assertIn("--include-out out/<project> lists the uploads", out)
        self.assertIn("!!!   out/demo/ep01/renders/ep01_draft_v01.mp4", out)
        self.assertIn("Nothing to push (text). Media not on Drive", out)
        self.assertEqual(out.count("!!! UNSAVED MEDIA:"), 2)            # at the top and again before the summary

        for i, rel in enumerate(u["files"]):
            self.run_tool("record", "projects/demo", "--uploaded", rel, "--id", f"M{i}")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["unsaved_media"]["files"], [])
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertNotIn("UNSAVED", out)
        (ep / "vo" / "VO1.wav").write_bytes(b"new take")                # a new take: unsaved again
        self.assertEqual(ds.unsaved_media(str(self.pd))["files"], ["out/demo/ep01/vo/VO1.wav"])

    def test_unsaved_media_without_snapshot(self):
        (self.out / "ep01" / "renders").mkdir()
        (self.out / "ep01" / "renders" / "ep01_final_v01.mp4").write_bytes(b"mp4")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertIn("!!! UNSAVED MEDIA: 1 file(s) not on Drive (renders 1) · 1 plate/clip file(s) in no bundle", out)
        self.assertIn("no .pulled.sha256: every file counts as not on Drive", out)

    def test_text_output(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        self.assertEqual(code, 0)
        self.assertIn("CHANGED projects/demo/ep01-bac-thi/script.md", out)
        self.assertIn("search_files parentId = 'F-KB-E1' and title = 'script.md' and trashed = false", out)
        self.assertIn("title=03_KichBan__ep01-bac-thi__script_20261110-1530.md", out)
        self.assertIn("archive      search_files parentId = 'F-KB-E1'", out)    # CHANGED: unconditional
        self.assertNotIn("first push", out)
        self.assertNotIn("Before uploading a NEW file", out)
        self.assertRegex(out, r"base64Content=sha256:[0-9a-f]{64}:/\S+/projects/demo/ep01-bac-thi/script\.md")
        self.assertIn("record projects/demo --uploaded projects/demo/ep01-bac-thi/script.md --id <new ID>", out)

    def test_bad_now(self):
        code, _, err = self.run_tool("plan", "projects/demo", "--now", "2026-11-10")
        self.assertEqual(code, 2)
        self.assertIn("YYYYMMDD-HHMM", err)


class TestArchiveName(unittest.TestCase):
    def test_format(self):
        self.assertEqual(ds.archive_name("03_KichBan/ep01-bac-thi", "script.md", "20261110-1530"),
                         "03_KichBan__ep01-bac-thi__script_20261110-1530.md")
        self.assertEqual(ds.archive_name("03_KichBan/ep01-bac-thi/prompts", "s01_L1.txt", "20260101-0000"),
                         "03_KichBan__ep01-bac-thi__prompts__s01_L1_20260101-0000.txt")
        self.assertEqual(ds.archive_name("00_QuanLy", "TienDo_SanXuat", "20261110-1530"),
                         "00_QuanLy__TienDo_SanXuat_20261110-1530")


class TestRecord(DriveSyncCase):
    def test_round_trip(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        self.write("SERIES.md", "y\n", append=True)
        code, plan = self.plan()
        self.assertEqual(plan["counts"]["changed"], 2)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--id", "NEW-SCRIPT")
        self.assertEqual(code, 0, err)
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/SERIES.md"])   # declined upload stays
        self.assertEqual(plan["pushed_ids"], ["NEW-SCRIPT"])
        log = (self.pd / ".pushed.log").read_text().splitlines()
        self.assertRegex(log[0], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z projects/demo/ep01-bac-thi/script\.md NEW-SCRIPT$")
        # only that line of the snapshot changed
        self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "NEW-SERIES")
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to push.", out)
        self.assertEqual(len((self.pd / ".pushed.log").read_text().splitlines()), 2)

    def test_record_media(self):
        self.snapshot()
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/ledger.csv", "--id", "L1")
        self.assertEqual(code, 0, err)
        self.assertIn("  out/demo/ep01/ledger.csv\n", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["actions"], [])

    def test_record_errors(self):
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--uploaded", "PROJECT.md",
                                     "--id", "A")
        self.assertEqual(code, 2)
        self.assertIn("one --id per --uploaded", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "nope.md", "--id", "A")
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "<new ID>")
        self.assertEqual(code, 2)


class TestSnapshotGuard(DriveSyncCase):
    """A second snapshot must not mark unpushed local edits as pulled."""

    def state(self):
        return (self.pd / ".pulled.sha256").read_bytes(), (self.pd / ".pulled.at").read_bytes()

    def test_second_snapshot_refuses_pending_change(self):
        self.snapshot()
        (self.pd / ".pulled.at").write_text("2026-11-01T00:00:00Z\n")
        before = self.state()
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)     # local edit, not pushed
        self.write("ep01-bac-thi/research.md", "# keo sau\n")                    # the later pull
        code, out, err = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)
        text = out + err
        self.assertIn("2 local change(s) not yet pushed would be marked as pulled", text)
        self.assertIn("drive_sync.py pulled projects/demo <path>...", text)
        self.assertIn("projects/demo/ep01-bac-thi/script.md", text)
        self.assertIn("projects/demo/ep01-bac-thi/research.md", text)
        self.assertEqual(self.state(), before)
        code, plan = self.plan()
        self.assertEqual((plan["counts"]["changed"], plan["counts"]["new"]), (1, 1))

    def test_refusal_lists_at_most_20(self):
        self.snapshot()
        for i in range(25):
            self.write(f"ep01-bac-thi/prompts/s{i:02d}_L9.txt", "x\n")
        code, out, err = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)
        self.assertIn("25 local change(s)", out + err)
        self.assertEqual(len(re.findall(r"_L9\.txt", out + err)), 20)

    def test_force_overrides(self):
        self.snapshot()
        (self.pd / ".pulled.at").write_text("2026-11-01T00:00:00Z\n")
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        code, out, err = self.run_tool("snapshot", "projects/demo", "--force")
        self.assertEqual(code, 0, err)
        self.assertNotEqual((self.pd / ".pulled.at").read_text(), "2026-11-01T00:00:00Z\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_first_snapshot_and_clean_resnapshot(self):
        out = self.snapshot()
        self.assertRegex(out, rf"^snapshot  projects/demo/\.pulled\.sha256: {len(FILES)} file\(s\) · pulled at ")
        first = (self.pd / ".pulled.sha256").read_bytes()
        self.snapshot()                                   # nothing pending: allowed, same content
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), first)
        os.remove(self.pd / "SERIES.md")                  # a deletion is not an unpushed change
        self.snapshot()

    def test_temp_files_and_ledger_copies_do_not_block(self):
        self.snapshot("--include-out", "out/demo")
        self.write("ep01-bac-thi/script.md.b64", "eA==\n")
        (self.out / "ep01" / "ledger.drive-1.csv").write_text("ts,kind\n")
        self.snapshot("--include-out", "out/demo")
        text = (self.pd / ".pulled.sha256").read_text()
        self.assertNotIn(".b64", text)
        self.assertNotIn("ledger.drive-1.csv", text)

    def test_pulled_updates_one_line(self):
        self.snapshot()
        (self.pd / ".pulled.at").write_text("2026-11-01T00:00:00Z\n")     # an old pull: a rewrite would show
        at = (self.pd / ".pulled.at").read_bytes()
        self.write("ep01-bac-thi/script.md", "[00:05] them\n", append=True)
        research = self.write("ep01-bac-thi/research.md", "# keo sau\n")
        code, out, err = self.run_tool("pulled", "projects/demo", "projects/demo/ep01-bac-thi/research.md")
        self.assertEqual(code, 0, err)
        self.assertIn("pulled    projects/demo/ep01-bac-thi/research.md", out)
        self.assertIn(f"{ds.sha256(research)}  projects/demo/ep01-bac-thi/research.md\n",
                      (self.pd / ".pulled.sha256").read_text())
        self.assertEqual((self.pd / ".pulled.at").read_bytes(), at)
        self.assertFalse((self.pd / ".pushed.log").exists())
        code, plan = self.plan()
        self.assertEqual([a["local"] for a in plan["actions"]], ["projects/demo/ep01-bac-thi/script.md"])
        self.assertEqual(plan["actions"][0]["status"], "changed")
        # the remaining pending change still blocks a full snapshot
        code, _, _ = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 1)

    def test_pulled_several_and_media(self):
        self.snapshot()
        self.write("ep01-bac-thi/research.md", "# keo sau\n")
        code, out, err = self.run_tool("pulled", "projects/demo", "ep01-bac-thi/research.md",
                                       "out/demo/ep01/ledger.csv")
        self.assertEqual(code, 0, err)
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["actions"], [])

    def test_pulled_outside_project(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        other = self.tmp / "projects" / "other" / "SERIES.md"
        other.parent.mkdir(parents=True)
        other.write_text("x\n")
        for path in ("/etc/hostname", "projects/other/SERIES.md"):
            if not os.path.exists(path):
                continue
            code, _, err = self.run_tool("pulled", "projects/demo", path)
            self.assertEqual(code, 2, path)
            self.assertIn("projects/demo/", err)
        code, _, err = self.run_tool("pulled", "projects/demo", "nope.md")
        self.assertEqual(code, 2)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)

    def test_pulled_needs_a_snapshot(self):
        code, _, err = self.run_tool("pulled", "projects/demo", "SERIES.md")
        self.assertEqual(code, 2)
        self.assertIn("snapshot", err)
        self.assertFalse((self.pd / ".pulled.sha256").exists())


class TestLockedState(DriveSyncCase):
    def test_parallel_record_keeps_every_line(self):
        tool = os.path.join(os.path.dirname(os.path.abspath(ds.__file__)), "drive_sync.py")
        names = [f"ep01-bac-thi/prompts/s{i:02d}_L1.txt" for i in range(10, 22)]
        for n in names:
            self.write(n, "v1\n")
        self.snapshot()
        total = len((self.pd / ".pulled.sha256").read_text().splitlines())
        for rnd in range(3):
            for n in names:
                self.write(n, f"round {rnd}\n", append=True)
            procs = [subprocess.Popen([sys.executable, tool, "record", "projects/demo", "--uploaded",
                                       f"projects/demo/{n}", "--id", f"ID-{rnd}-{i}"],
                                      cwd=self.tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for i, n in enumerate(names)]
            for pr in procs:
                _, err = pr.communicate(timeout=60)
                self.assertEqual(pr.returncode, 0, err.decode())
            self.assertEqual(len((self.pd / ".pulled.sha256").read_text().splitlines()), total, f"round {rnd}")
            self.assertEqual(len((self.pd / ".pushed.log").read_text().splitlines()), 12 * (rnd + 1))
            code, out, _ = self.run_tool("plan", "projects/demo")
            self.assertEqual(code, 0, out)
            self.assertIn("Nothing to push.", out)
        self.assertEqual([f for f in os.listdir(self.pd) if f.endswith(".tmp")], [])

    def test_lock_file_is_never_planned(self):
        self.snapshot()
        self.assertTrue((self.pd / ".drive_sync.lock").exists())
        code, plan = self.plan()
        self.assertEqual((plan["actions"], plan["unmapped"]), ([], []))
        self.assertNotIn(".drive_sync.lock", (self.pd / ".pulled.sha256").read_text())


class TestRecordSafety(DriveSyncCase):
    def test_sha256_keeps_later_edit_changed(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "v2\n", append=True)
        code, plan = self.plan()
        planned = self.action(plan, "projects/demo/ep01-bac-thi/script.md")["sha256"]
        self.write("ep01-bac-thi/script.md", "v3\n", append=True)           # edit after create_file
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--sha256", planned, "--id", "NEW1")
        self.assertEqual(code, 0, err)
        self.assertIn("WARN projects/demo/ep01-bac-thi/script.md changed after the upload: still to push", out + err)
        self.assertIn(f"{planned}  projects/demo/ep01-bac-thi/script.md\n", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/ep01-bac-thi/script.md")
        self.assertEqual((x["status"], x["sha256"]), ("changed", ds.sha256(script)))
        self.assertEqual(plan["pushed_ids"], ["NEW1"])

    def test_sha256_matching_file(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "v2\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects/demo/ep01-bac-thi/script.md",
                                       "--sha256", ds.sha256(script).upper(), "--id", "NEW1")
        self.assertEqual(code, 0, err)
        self.assertNotIn("WARN", out + err)
        self.assertNotIn("--sha256", out + err)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_without_sha256_reminder(self):
        self.snapshot()
        self.write("SERIES.md", "y\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "S1")
        self.assertEqual(code, 0, err)
        self.assertEqual(len([l for l in (out + err).splitlines() if "--sha256" in l]), 1)
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_bad_sha256(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--sha256", "abc123",
                                     "--id", "S1")
        self.assertEqual(code, 2)
        self.assertIn("64 hex", err)
        code, _, err = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--uploaded", "PROJECT.md",
                                     "--sha256", "a" * 64, "--id", "S1", "--id", "S2")
        self.assertEqual(code, 2)
        self.assertIn("one --sha256 per --uploaded", err)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)
        self.assertFalse((self.pd / ".pushed.log").exists())

    def test_foreign_paths_refused(self):
        self.snapshot()
        before = (self.pd / ".pulled.sha256").read_bytes()
        other = self.tmp / "projects" / "other" / "SERIES.md"
        other.parent.mkdir(parents=True)
        other.write_text("x\n")
        (self.tmp / "out" / "other").mkdir()
        (self.tmp / "out" / "other" / "ledger.csv").write_text("ts,kind\n")
        for path in ("/etc/hostname", "projects/other/SERIES.md", "out/other/ledger.csv"):
            if not os.path.exists(path):
                continue
            code, _, err = self.run_tool("record", "projects/demo", "--uploaded", path, "--id", "X")
            self.assertEqual(code, 2, path)
            self.assertIn("projects/demo/", err)
        # one bad path refuses the whole call
        code, _, _ = self.run_tool("record", "projects/demo", "--uploaded", "SERIES.md", "--id", "A",
                                   "--uploaded", "projects/other/SERIES.md", "--id", "B")
        self.assertEqual(code, 2)
        self.assertEqual((self.pd / ".pulled.sha256").read_bytes(), before)
        self.assertFalse((self.pd / ".pushed.log").exists())

    def test_backslash_path(self):
        self.snapshot()
        self.write("SERIES.md", "y\n", append=True)
        code, out, err = self.run_tool("record", "projects/demo", "--uploaded", "projects\\demo\\SERIES.md",
                                       "--id", "S1")
        self.assertEqual(code, 0, err)
        self.assertRegex((self.pd / ".pushed.log").read_text(), r" projects/demo/SERIES\.md S1\n$")
        self.assertNotIn("\\", (self.pd / ".pulled.sha256").read_text())
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])

    def test_backslash_snapshot_keys(self):
        lines = [f"{ds.sha256(self.pd / r)}  " + f"projects/demo/{r}".replace("/", "\\") for r in sorted(FILES)]
        (self.pd / ".pulled.sha256").write_text("\n".join(lines) + "\n")
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["counts"]["unchanged"], len(FILES))


class TestLedgerPlan(DriveSyncCase):
    def setUp(self):
        super().setUp()
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "ledger.csv").write_text("ts,kind\n1,image\n")

    def test_ledger_action(self):
        (self.out / "ep01" / "renders").mkdir()
        (self.out / "ep01" / "renders" / "ep01_draft_v01.mp4").write_bytes(b"mp4")
        code, plan = self.plan("--include-out", "out/demo")
        led = self.action(plan, "out/demo/ep01/ledger.csv")
        self.assertEqual(led["notes"], ["ledger: push after every stage that generated; no approval gate"])
        self.assertEqual(led["pre"], {"ledger_merge": {
            "into": "out/demo/ep01/ledger.csv", "copies_glob": "out/demo/ep01/ledger.drive-*.csv",
            "search_files": "parentId = 'F-SX-E1' and title = 'ledger.csv' and trashed = false",
            "excludeContentSnippets": True}})
        draft = self.action(plan, "out/demo/ep01/renders/ep01_draft_v01.mp4")
        self.assertEqual(len(draft["notes"]), 1)
        self.assertTrue(draft["notes"][0].startswith("unapproved media: push now, before any approval"))
        self.action(plan, "out/demo/ep01/ledger.csv")
        self.assertNotIn("pre", draft)

    def test_text_merge_before_upload(self):
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo", "--now", "20261110-1530")
        self.assertEqual(code, 0)
        block = out.split("CHANGED out/demo/ep01/ledger.csv", 1)[1]
        self.assertLess(block.index("ledger-merge"), block.index("create_file"))
        self.assertIn("1) search_files parentId = 'F-SX-E1' and title = 'ledger.csv' and trashed = false"
                      "  excludeContentSnippets=true", block)
        self.assertIn("2) download EVERY result to out/demo/ep01/ledger.drive-<n>.csv", block)
        self.assertIn("3) python3 tools/ark.py ledger-merge out/demo/ep01/ledger.csv out/demo/ep01/ledger.drive-*.csv "
                      "-o out/demo/ep01/ledger.csv", block)
        self.assertIn("4) run plan again", block)
        self.assertIn("note         ledger: push after every stage that generated; no approval gate", block)
        self.assertNotIn("only after the user approved", block)

    def test_drive_copies_never_planned(self):
        (self.out / "ep01" / "ledger.drive-1.csv").write_text("ts,kind\n9,image\n")
        (self.out / "ledger.drive-2.csv").write_text("ts,kind\n")
        self.write("ep01-bac-thi/ledger.drive-1.csv", "ts,kind\n")
        self.write("ledger.drive-3.csv", "ts,kind\n")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertEqual([a["local"] for a in plan["actions"]], ["out/demo/ep01/ledger.csv"])
        self.assertEqual(plan["unmapped"], [])
        self.assertEqual(plan["skipped_media"], 1)          # the plate only
        self.assertEqual(plan["ignored_temp"], [])


class TestPlanHygiene(DriveSyncCase):
    def test_search_lines_exclude_snippets(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        self.write("TienDo_SanXuat.csv", "ep02,0\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        searches = [l for l in out.splitlines() if re.search(r"\bsearch_files parentId", l)]
        self.assertEqual(len(searches), 3)
        for line in searches:
            self.assertTrue(line.endswith("and trashed = false  excludeContentSnippets=true"), line)
        code, plan = self.plan()
        for x in plan["actions"] + [plan["sheet"]]:
            self.assertIs(x["archive"]["excludeContentSnippets"], True)

    def test_apostrophe_and_backslash_title(self):
        self.assertEqual(ds.search_query("F1", "02_KinhThu", "quach-phac's_note.txt"),
                         "parentId = 'F1' and title = 'quach-phac\\'s_note.txt' and trashed = false")
        self.assertEqual(ds.search_query("F1", "02_KinhThu", "a\\b.txt"),
                         "parentId = 'F1' and title = 'a\\\\b.txt' and trashed = false")
        self.snapshot()
        self.write("ep01-bac-thi/quach-phac's_note.txt", "x\n")
        code, plan = self.plan()
        x = self.action(plan, "projects/demo/ep01-bac-thi/quach-phac's_note.txt")
        self.assertIn("title = 'quach-phac\\'s_note.txt'", x["archive"]["search_files"])
        self.assertEqual(x["create_file"]["title"], "quach-phac's_note.txt")

    def test_temp_files_ignored(self):
        self.snapshot("--include-out", "out/demo")
        for name in ("research.md.b64", "script.md.orig", "script.md.bak", "x.tmp", "shots.csv~"):
            self.write(f"ep01-bac-thi/{name}", "x\n")
        self.write("notes.part", "x\n")                                  # would be UNMAPPED
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261110.zip.part").write_bytes(b"x")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertEqual((plan["actions"], plan["unmapped"]), ([], []))
        self.assertEqual(len(plan["ignored_temp"]), 7)
        self.assertIn("projects/demo/ep01-bac-thi/research.md.b64", plan["ignored_temp"])
        self.assertEqual(plan["skipped_media"], 1)
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(out.count("ignored temp files"), 1)
        self.assertIn("script.md.orig", out)
        self.assertNotIn("NEW", out)
        self.assertNotIn("UNMAPPED", out)

    def test_old_snapshot_lines_of_temp_files_are_not_deleted(self):
        self.snapshot("--include-out", "out/demo")
        with open(self.pd / ".pulled.sha256", "a") as f:                 # lines written by an older snapshot
            f.write("0" * 64 + "  projects/demo/ep01-bac-thi/script.md.b64\n")
            f.write("0" * 64 + "  out/demo/ep01/ledger.drive-1.csv\n")
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual((code, plan["deleted"], plan["actions"]), (0, [], []))

    def test_changed_paragraph_only_with_a_changed_file(self):
        self.snapshot()
        self.write("ep01-bac-thi/prompts/s02_L4.txt", "bac thi\n")
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("Before uploading a NEW file", out)
        self.assertNotIn("Before uploading a CHANGED file", out)
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("Before uploading a CHANGED file", out)

    def test_record_line_carries_sha256(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo")
        self.assertIn("record projects/demo --uploaded projects/demo/ep01-bac-thi/script.md --id <new ID> "
                      f"--sha256 {ds.sha256(script)}", out)

    def test_unbundled_media_message(self):
        self.snapshot("--include-out", "out/demo")
        ep = self.out / "ep01"
        (ep / "clips").mkdir()
        (ep / "clips" / "ep01_s01_seedance_v01.mp4").write_bytes(b"mp4")
        (ep / "plates" / "notes.txt").write_text("no shot tag")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertIn("Nothing to push (text). 2 plate/clip file(s) are in no bundle: "
                      "they exist only in this container", out)
        self.assertNotIn("Nothing to push.", out)
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["unbundled_media"], 2)

        (ep / "bundles").mkdir()
        zp = ep / "bundles" / "ep01_s01_20261110.zip"
        with zipfile.ZipFile(zp, "w") as z:
            z.writestr("plates/ep01_s01_L1_nui_v01.png", b"png")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z1")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertIn("Nothing to push (text). 1 plate/clip file(s) are in no bundle", out)

        with zipfile.ZipFile(zp, "a") as z:
            z.writestr("clips/ep01_s01_seedance_v01.mp4", b"mp4")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z2")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertIn("Nothing to push.", out)
        self.assertNotIn("in no bundle", out)

    def test_unreadable_bundle_counts_as_empty(self):
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "bundles").mkdir()
        (self.out / "ep01" / "bundles" / "ep01_s01_20261110.zip").write_bytes(b"not a zip")
        self.run_tool("record", "projects/demo", "--uploaded", "out/demo/ep01/bundles/ep01_s01_20261110.zip",
                      "--id", "Z1")
        code, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        self.assertEqual(code, 0)
        self.assertIn("1 plate/clip file(s) are in no bundle", out)


class TestCli(unittest.TestCase):
    def test_help_lists_commands(self):
        code, out, _ = run_main(ds.main, ["--help"])
        self.assertEqual(code, 0)
        self.assertRegex(out, r"\{save,snapshot,pulled,plan,record\}")


class TestManifestErrors(DriveSyncCase):
    def test_missing_project_md(self):
        os.remove(self.pd / "PROJECT.md")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("PROJECT.md not found", err)
        self.assertIn("pull 00_QuanLy/PROJECT.md", err)

    def test_missing_project_dir(self):
        code, _, err = self.run_tool("plan", "projects/nope")
        self.assertEqual(code, 2)
        self.assertIn("project working copy not found", err)

    def test_no_folders(self):
        self.write("PROJECT.md", "---\nproject: demo\ndrive:\n  name: Demo\n---\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("drive.folders", err)

    def test_no_front_matter(self):
        self.write("PROJECT.md", "# Demo\n")
        code, _, err = self.run_tool("plan", "projects/demo")
        self.assertEqual(code, 2)
        self.assertIn("no YAML front matter", err)

    def test_template_manifest(self):
        """The repo template parses; its <id> placeholders count as unknown folders."""
        tpl = ds.load_manifest(os.path.join(os.path.dirname(ds.__file__), "..", "templates", "project"))
        self.assertIn("99_LuuTru", tpl["folders"])
        self.assertIsNone(ds.folder_id(tpl, "99_LuuTru"))


# --- pull side: save, snapshot --only, out/ lines, symlinks, ledger pre block ------------------------------------

DRIVE_FIX = FIX / "drive"         # synthetic transcripts: fake file IDs, fake tiny content (no real session)
EP2 = b"---\nstage: 2\n---\n"     # newest FAKE-EP-0001 download in session-main.jsonl
KEY_PNG = b"\x89PNG\r\n\x1a\n\xfb\xff\xfe\xfd\xfc"


class SaveCase(DriveSyncCase):
    """A fake Claude Code store: this repo's transcript folder (main session + a subagent) and another project's."""

    def setUp(self):
        super().setUp()
        self.claude = self.tmp / "claude-home"
        self.env = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.claude)
        store = self.claude / "projects"
        self.own = store / ds.transcript_slug(os.getcwd())
        (self.own / "session-main" / "subagents").mkdir(parents=True)
        shutil.copy(DRIVE_FIX / "session-main.jsonl", self.own / "session-main.jsonl")
        shutil.copy(DRIVE_FIX / "session-fallback.jsonl", self.own / "session-fallback.jsonl")
        shutil.copy(DRIVE_FIX / "agent-sub.jsonl", self.own / "session-main" / "subagents" / "agent-sub.jsonl")
        (store / "-other-project").mkdir()
        shutil.copy(DRIVE_FIX / "session-old.jsonl", store / "-other-project" / "session-old.jsonl")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self.env
        super().tearDown()

    def save(self, *argv):
        return self.run_tool("save", "projects/demo", *argv)

    def snap_text(self):
        return (self.pd / ".pulled.sha256").read_text()

    def transcript(self, name, records):
        (self.own / name).write_text("".join(json.dumps(r) + "\n" for r in records))


class TestDecode(unittest.TestCase):
    def test_variants(self):
        data = KEY_PNG + b"x"
        std, url = base64.b64encode(data).decode(), base64.urlsafe_b64encode(data).decode()
        self.assertNotEqual(std, url)
        for text in (std, url, std.rstrip("="), url.rstrip("="), std[:8] + "\n " + std[8:]):
            self.assertEqual(ds.decode_b64(text), data, text)

    def test_refused(self):
        for text in ("ab+-cd==", "abcde", "not base64!", "ab=c"):
            with self.assertRaises(ValueError, msg=text):
                ds.decode_b64(text)

    def test_slug(self):
        self.assertEqual(ds.transcript_slug("/home/user/claude-film-lab"), "-home-user-claude-film-lab")


class TestSave(SaveCase):
    def test_newest_result_written_and_marked_pulled(self):
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/research.md", "--size", "17")
        self.assertEqual(code, 0, err)
        target = self.pd / "ep01-bac-thi" / "research.md"
        self.assertEqual(target.read_bytes(), EP2)
        self.assertIn("saved     projects/demo/ep01-bac-thi/research.md  17 bytes  sha256 "
                      f"{hashlib.sha256(EP2).hexdigest()[:12]}  <- FAKE-EP-0001 (session-main.jsonl:5)", out)
        self.assertIn("pulled    projects/demo/ep01-bac-thi/research.md", out)
        self.assertIn(f"{ds.sha256(target)}  projects/demo/ep01-bac-thi/research.md\n", self.snap_text())
        self.assertNotIn(base64.b64encode(EP2).decode(), out + err)      # never prints the content
        self.assertNotIn("stage: 2", out + err)
        self.assertFalse((self.pd / ".pushed.log").exists())
        code, plan = self.plan()
        self.assertEqual(plan["actions"], [])
        self.assertEqual([f for f in os.listdir(target.parent) if f.endswith(".part")], [])

    def test_several_files_subagent_and_url_safe(self):
        self.snapshot("--include-out", "out/demo")
        code, out, err = self.save(
            "--id", "FAKE-LEDGER-0002", "--to", "out/demo/ep01/ledger.drive-1.csv",
            "--id", "FAKE-KEY-0003", "--to", "out/demo/characters/bac-thi/bac-thi_key_v01.png", "--size", "13",
            "--id", "FAKE-SUB-0006", "--to", "characters/bac-thi/NOTES.md")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.out / "ep01" / "ledger.drive-1.csv").read_bytes(),
                         b"ts,kind,model,size,seconds,count,status,out,task_id,usage,agent,note\n")
        self.assertEqual((self.out / "characters" / "bac-thi" / "bac-thi_key_v01.png").read_bytes(), KEY_PNG)
        self.assertEqual((self.pd / "characters" / "bac-thi" / "NOTES.md").read_bytes(), b"# nhan vat gia\n")
        self.assertIn("(agent-sub.jsonl:2)", out)
        self.assertIn("out/demo/ep01/ledger.drive-1.csv: temp file or Drive ledger copy, not marked pulled", out)
        text = self.snap_text()
        self.assertIn("  out/demo/characters/bac-thi/bac-thi_key_v01.png\n", text)
        self.assertIn("  projects/demo/characters/bac-thi/NOTES.md\n", text)
        self.assertNotIn("ledger.drive-1.csv", text)

    def test_other_project_folder_is_searched_last(self):
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-OTHER-0008", "--to", "ep01-bac-thi/other.md")
        self.assertEqual(code, 0, err)
        self.assertIn("(session-old.jsonl:4)", out)
        self.assertIn("no --size", out)

    def test_timestamps_beat_file_times(self):
        """--transcript: only those files; the newest result by record time, not by file mtime."""
        t = self.tmp / "t"
        t.mkdir()
        for name in ("session-main.jsonl", "session-old.jsonl"):
            shutil.copy(DRIVE_FIX / name, t / name)
        later = time.time() + 100
        os.utime(t / "session-old.jsonl", (later, later))        # written last, but its download is older
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/research.md",
                                   "--transcript", str(t / "*.jsonl"))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.pd / "ep01-bac-thi" / "research.md").read_bytes(), EP2)
        code, _, err = self.save("--id", "FAKE-SUB-0006", "--to", "x.md", "--transcript", str(t / "*.jsonl"))
        self.assertEqual(code, 2)
        self.assertIn("--transcript", err)
        code, _, err = self.save("--id", "FAKE-EP-0001", "--to", "x.md", "--transcript", str(t / "none-*.jsonl"))
        self.assertEqual(code, 2)
        self.assertIn("no file matches", err)

    def test_persisted_output_file(self):
        """A large result kept by Claude Code in a file beside the transcript is read from there."""
        data = b"# lon\n" * 50
        saved = self.own / "session-big" / "tool-results" / "toolu_FAKE_41.txt"
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps({"id": "FAKE-BIG-0010", "content": base64.b64encode(data).decode()}))
        outside = self.tmp / "elsewhere.txt"
        outside.write_text(json.dumps({"id": "FAKE-OUT-0011", "content": base64.b64encode(b"x").decode()}))
        recs = []
        for uid, fid, path in (("toolu_FAKE_41", "FAKE-BIG-0010", saved), ("toolu_FAKE_42", "FAKE-OUT-0011", outside)):
            recs.append({"type": "assistant", "timestamp": "2026-11-12T12:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": uid, "name": "mcp__x__download_file_content", "input": {"fileId": fid}}]}})
            recs.append({"type": "user", "timestamp": "2026-11-12T12:00:01Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": [{"type": "text", "text":
                 f"<persisted-output>\nOutput too large (2KB). Full output saved to: {path}\n\nPreview (first 2KB):\n"
                 '{"id": "' + fid + '", "content": "IyBs\n...\n</persisted-output>'}]}]}})
        self.transcript("session-big.jsonl", recs)
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-BIG-0010", "--to", "ep01-bac-thi/big.md", "--size", str(len(data)))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.pd / "ep01-bac-thi" / "big.md").read_bytes(), data)
        code, _, err = self.save("--id", "FAKE-OUT-0011", "--to", "ep01-bac-thi/out.md", "--size", "1")
        self.assertEqual(code, 2)                # the file outside the store is not read; the preview is cut short
        self.assertFalse((self.pd / "ep01-bac-thi" / "out.md").exists())

    def blob_result(self, uid, fid, path, mime="text/markdown", size="0.3KB"):
        """The two records of a local-session download: the connector saved the file and only names it."""
        return [
            {"type": "assistant", "timestamp": "2026-11-26T09:00:00Z", "message": {"content": [
                {"type": "tool_use", "id": uid, "name": "mcp__claude_ai_Google_Drive__download_file_content",
                 "input": {"fileId": fid}}]}},
            {"type": "user", "timestamp": "2026-11-26T09:00:01Z", "message": {"content": [
                {"type": "tool_result", "tool_use_id": uid, "content": [
                    {"type": "text", "text": f"[Resource from claude.ai Google Drive at googledrive://file/{fid}] "
                                             f"Binary content ({mime}, {size}) saved to {path}"},
                    {"type": "text", "text": json.dumps({"id": fid, "title": "x.md", "mimeType": mime,
                                                         "content": "(file sent separately)"})}]}]}}]

    def test_connector_saved_file(self):
        """Local session: `Binary content (...) saved to <file>` → the saved file is copied, size checked."""
        data = "---\nstage: 3\n---\n# Tập 3 – sinh vật\n".encode("utf-8")
        blob = self.own / "session-local" / "tool-results" / "mcp-claude_ai_Google_Drive-blob-1795651653356-ab12cd.md"
        blob.parent.mkdir(parents=True)
        blob.write_bytes(data)
        gone = self.own / "session-local" / "tool-results" / "mcp-claude_ai_Google_Drive-blob-2-gone.md"
        outside = self.tmp / "mcp-claude_ai_Google_Drive-blob-3-out.md"
        outside.write_bytes(b"x")
        self.transcript("session-local.jsonl",
                        self.blob_result("toolu_FAKE_61", "FAKE-BLOB-0061", blob)
                        + self.blob_result("toolu_FAKE_62", "FAKE-GONE-0062", gone)
                        + self.blob_result("toolu_FAKE_63", "FAKE-OUTS-0063", outside))
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-BLOB-0061", "--to", "ep01-bac-thi/EPISODE.md",
                                   "--size", str(len(data)))
        self.assertEqual(code, 0, err)
        self.assertEqual((self.pd / "ep01-bac-thi" / "EPISODE.md").read_bytes(), data)
        self.assertIn("<- FAKE-BLOB-0061 (session-local.jsonl:2, saved file)", out)
        self.assertIn(f"{hashlib.sha256(data).hexdigest()}  projects/demo/ep01-bac-thi/EPISODE.md\n", self.snap_text())
        self.assertNotIn("sinh vật", out + err)
        code, _, err = self.save("--id", "FAKE-BLOB-0061", "--to", "ep01-bac-thi/x.md", "--size", "5")
        self.assertEqual(code, 2)
        self.assertIn(f"decoded {len(data)} bytes, --size says 5", err)
        code, _, err = self.save("--id", "FAKE-GONE-0062", "--to", "ep01-bac-thi/x.md")
        self.assertEqual(code, 2)
        self.assertIn("is gone", err)
        code, _, err = self.save("--id", "FAKE-OUTS-0063", "--to", "ep01-bac-thi/x.md")
        self.assertEqual(code, 2)
        self.assertIn("outside the Claude transcript store", err)
        self.assertIn("--from-file", err)
        self.assertFalse((self.pd / "ep01-bac-thi" / "x.md").exists())

    def test_separately_sent_without_a_file_hints_from_file(self):
        rec = self.blob_result("toolu_FAKE_64", "FAKE-SEP-0064", "x")
        rec[1]["message"]["content"][0]["content"] = rec[1]["message"]["content"][0]["content"][1:]   # JSON part only
        self.transcript("session-sep.jsonl", rec)
        code, _, err = self.save("--id", "FAKE-SEP-0064", "--to", "ep01-bac-thi/x.md")
        self.assertEqual(code, 2)
        self.assertIn("not base64", err)
        self.assertIn("--from-file <file>", err)

    def test_from_file(self):
        """--from-file copies the named file without any transcript (the ID is in none); --size is required."""
        data = b"\x89PNG\r\n\x1a\nraw blob"
        blob = self.tmp / "blob.png"
        blob.write_bytes(data)
        self.snapshot("--include-out", "out/demo")
        code, _, err = self.save("--id", "FAKE-FILE-0065", "--to", "out/demo/characters/bac-thi/k.png",
                                 "--from-file", str(blob))
        self.assertEqual(code, 2)
        self.assertIn("--from-file needs --size", err)
        code, _, err = self.save("--id", "FAKE-FILE-0065", "--to", "out/demo/characters/bac-thi/k.png",
                                 "--from-file", str(self.tmp / "none.png"), "--size", "3")
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)
        code, _, err = self.save("--id", "FAKE-FILE-0065", "--to", "out/demo/characters/bac-thi/k.png",
                                 "--from-file", str(blob), "--size", str(len(data) + 1))
        self.assertEqual(code, 2)
        self.assertFalse((self.out / "characters" / "bac-thi" / "k.png").exists())
        code, out, err = self.save("--id", "FAKE-FILE-0065", "--to", "out/demo/characters/bac-thi/k.png",
                                   "--from-file", str(blob), "--size", str(len(data)),
                                   "--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/research.md")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.out / "characters" / "bac-thi" / "k.png").read_bytes(), data)
        self.assertEqual((self.pd / "ep01-bac-thi" / "research.md").read_bytes(), EP2)
        self.assertIn("<- FAKE-FILE-0065 (--from-file blob.png)", out)
        self.assertIn("  out/demo/characters/bac-thi/k.png\n", self.snap_text())

    def test_native_path(self):
        if os.sep == "/":
            self.assertEqual(ds.native_path("C:\\Users\\A\\.claude\\x-blob.md"), "/mnt/c/Users/A/.claude/x-blob.md")
        self.assertEqual(ds.native_path(" /tmp/a b.md "), "/tmp/a b.md")

    def test_errors_write_nothing(self):
        self.snapshot()
        before = self.snap_text()
        cases = [
            (("--id", "FAKE-ERR-0004", "--to", "a.md"), "the download failed"),
            (("--id", "FAKE-TRUNC-0005", "--to", "a.md", "--size", "60"), "decoded 55 bytes, --size says 60"),
            (("--id", "FAKE-NONE-0099", "--to", "a.md"), "no download_file_content result for file id(s) FAKE-NONE-0099"),
            (("--id", "FAKE-EP-0001", "--to", "a.md", "--size", "18"), "decoded 17 bytes"),
            (("--id", "FAKE-EP-0001", "--to", "b.md", "--id", "FAKE-NONE-0099", "--to", "a.md"), "FAKE-NONE-0099"),
            (("--id", "FAKE-EP-0001", "--to", "a.md", "--id", "FAKE-SUB-0006", "--to", "a.md"), "given twice"),
        ]
        for argv, msg in cases:
            code, out, err = self.save(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn(msg, err, argv)
            self.assertFalse((self.pd / "a.md").exists(), argv)
            self.assertFalse((self.pd / "b.md").exists(), argv)
        self.assertEqual(self.snap_text(), before)

    def test_size_in_the_result_warns_without_size(self):
        self.snapshot()
        code, out, err = self.save("--id", "FAKE-TRUNC-0005", "--to", "ep01-bac-thi/research.md")
        self.assertEqual(code, 0, err)
        self.assertIn("WARN      projects/demo/ep01-bac-thi/research.md: the result says size 60, decoded 55 bytes", out)

    def test_search_snippets_are_not_downloads(self):
        self.transcript("session-search.jsonl", [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "toolu_FAKE_51",
             "name": "mcp__claude_ai_Google_Drive__search_files", "input": {"query": "title = 'x'"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_FAKE_51",
             "content": [{"type": "text", "text": json.dumps({"files": [
                 {"id": "FAKE-SNIP-0012", "content": base64.b64encode(b"snip").decode()}]})}]}]}}])
        code, _, err = self.save("--id", "FAKE-SNIP-0012", "--to", "a.md", "--size", "4")
        self.assertEqual(code, 2)
        self.assertIn("no download_file_content result", err)

    def test_text_search_fallback_needs_size(self):
        code, _, err = self.save("--id", "FAKE-FB-0007", "--to", "ep01-bac-thi/budget.yaml")
        self.assertEqual(code, 2)
        self.assertIn("found only by text search", err)
        code, out, err = self.save("--id", "FAKE-FB-0007", "--to", "ep01-bac-thi/budget.yaml", "--size", "10")
        self.assertEqual(code, 0, err)
        self.assertIn("text search", out)
        self.assertEqual((self.pd / "ep01-bac-thi" / "budget.yaml").read_bytes(), b"images: 4\n")

    def test_overwrite_guard(self):
        self.snapshot()
        script = self.write("ep01-bac-thi/script.md", "[00:05] sua tai cho\n", append=True)   # not pushed
        local = script.read_bytes()
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/script.md")
        self.assertEqual(code, 1)
        self.assertIn("projects/demo/ep01-bac-thi/script.md: local changes not pushed yet", err)
        self.assertIn("--to <path>.orig", err)
        self.assertEqual(script.read_bytes(), local)
        self.write("ep01-bac-thi/notes.md", "tu tao\n")                                         # made locally
        code, _, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/notes.md")
        self.assertEqual(code, 1)
        self.assertIn("not in the snapshot", err)
        # a file untouched since the pull is replaced by the newer Drive version; .orig beside a change is fine
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "SERIES.md",
                                   "--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/script.md.orig")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.pd / "SERIES.md").read_bytes(), EP2)
        self.assertEqual((self.pd / "ep01-bac-thi" / "script.md.orig").read_bytes(), EP2)
        self.assertNotIn("script.md.orig", self.snap_text())
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/script.md", "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(script.read_bytes(), EP2)

    def test_no_snapshot_yet(self):
        code, out, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/research.md")
        self.assertEqual(code, 0, err)
        self.assertIn("no .pulled.sha256 yet", out)
        self.assertFalse((self.pd / ".pulled.sha256").exists())
        code, _, err = self.save("--id", "FAKE-SUB-0006", "--to", "SERIES.md")            # exists, unknown origin
        self.assertEqual(code, 1)
        self.assertIn("no snapshot yet", err)
        code, _, err = self.save("--id", "FAKE-EP-0001", "--to", "ep01-bac-thi/EPISODE.md")  # same bytes
        self.assertEqual(code, 0, err)

    def test_new_project_folder(self):
        code, out, err = self.run_tool("save", "projects/moi", "--id", "FAKE-EP-0001", "--to", "PROJECT.md")
        self.assertEqual(code, 0, err)
        self.assertEqual((self.tmp / "projects" / "moi" / "PROJECT.md").read_bytes(), EP2)
        self.assertIn("created   projects/moi/", out)
        code, _, err = self.run_tool("save", "khac/moi", "--id", "FAKE-EP-0001", "--to", "PROJECT.md")
        self.assertEqual(code, 2)
        self.assertFalse((self.tmp / "khac").exists())

    def test_paths_leaving_the_project(self):
        (self.tmp / "elsewhere").mkdir()
        os.symlink(self.tmp / "elsewhere", self.pd / "ep01-bac-thi" / "link")
        (self.tmp / "projects" / "other").mkdir()
        for to in ("../other/x.md", "projects/other/x.md", "out/other/x.md", str(self.tmp / "x.md"),
                   ".hidden.md", "ep01-bac-thi/link/x.md", "ep01-bac-thi"):
            code, _, err = self.save("--id", "FAKE-EP-0001", "--to", to)
            self.assertEqual(code, 2, to)
            self.assertIn("--to", err, to)
        self.assertEqual(os.listdir(self.tmp / "elsewhere"), [])
        self.assertFalse((self.tmp / "projects" / "other" / "x.md").exists())

    def test_cli_groups(self):
        for argv in (("--to", "a.md", "--id", "X"), ("--id", "X", "--to", "a.md", "--to", "b.md"),
                     ("--id", "X", "--size", "abc", "--to", "a.md")):
            code, _, _ = self.save(*argv)
            self.assertEqual(code, 2, argv)
        code, _, err = self.save("--id", "FAKE-EP-0001")
        self.assertEqual(code, 2)
        self.assertIn("--to", err)
        code, _, err = self.save()
        self.assertEqual(code, 2)


class TestSnapshotOnly(DriveSyncCase):
    def snap_text(self):
        return (self.pd / ".pulled.sha256").read_text()

    def test_first_snapshot_of_just_the_pulled_files(self):
        self.write("ep01-bac-thi/notes.md", "tao truoc khi chup dau\n")
        code, out, err = self.run_tool("snapshot", "projects/demo", "--only", "PROJECT.md", "SERIES.md",
                                       "projects/demo/characters", "out/demo/ep01/ledger.csv")
        self.assertEqual(code, 0, err)
        keys = [l.split("  ", 1)[1] for l in self.snap_text().splitlines()]
        self.assertEqual(keys, ["out/demo/ep01/ledger.csv", "projects/demo/PROJECT.md", "projects/demo/SERIES.md",
                                "projects/demo/characters/bac-thi/CHARACTER.md"])
        self.assertTrue((self.pd / ".pulled.at").exists())
        self.assertIn("4 file(s) (--only", out)
        code, plan = self.plan()
        new = {a["local"] for a in plan["actions"] if a["status"] == "new"}
        self.assertIn("projects/demo/ep01-bac-thi/notes.md", new)
        self.assertNotIn("projects/demo/SERIES.md", new)

    def test_refused_when_a_snapshot_exists(self):
        self.snapshot()
        before = self.snap_text()
        code, _, err = self.run_tool("snapshot", "projects/demo", "--only", "SERIES.md")
        self.assertEqual(code, 1)
        self.assertIn("drive_sync.py pulled projects/demo", err)
        self.assertEqual(self.snap_text(), before)
        code, _, err = self.run_tool("snapshot", "projects/demo", "--only", "SERIES.md", "--force")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.snap_text().splitlines()), 1)

    def test_errors(self):
        code, _, err = self.run_tool("snapshot", "projects/demo", "--only", "SERIES.md", "--include-out", "out/demo")
        self.assertEqual(code, 2)
        code, _, err = self.run_tool("snapshot", "projects/demo", "--only", "nope.md")
        self.assertEqual(code, 2)
        self.assertFalse((self.pd / ".pulled.sha256").exists())


class TestSnapshotKeepsOut(DriveSyncCase):
    def test_snapshot_without_include_out_keeps_out_lines(self):
        self.snapshot("--include-out", "out/demo")
        line = f"{ds.sha256(self.out / 'ep01' / 'ledger.csv')}  out/demo/ep01/ledger.csv\n"
        out = self.snapshot()
        self.assertIn(line, (self.pd / ".pulled.sha256").read_text())
        self.assertIn("2 out/ line(s) kept (no --include-out)", out)
        code, plan = self.plan("--include-out", "out/demo")
        self.assertEqual(plan["actions"], [])
        self.snapshot("--include-out", "out/demo")              # not refused: the media lines are still there
        code, _, err = self.run_tool("snapshot", "projects/demo", "--force")
        self.assertEqual(code, 0, err)
        self.assertIn(line, (self.pd / ".pulled.sha256").read_text())


class TestSymlinkEscape(DriveSyncCase):
    def setUp(self):
        super().setUp()
        outside = self.tmp / "secret.txt"
        outside.write_text("not ours\n")
        os.symlink(outside, self.pd / "ep01-bac-thi" / "link.md")
        os.symlink(self.pd / "SERIES.md", self.pd / "ep01-bac-thi" / "series-link.md")    # inside: fine

    def test_refused_everywhere(self):
        code, _, err = self.run_tool("snapshot", "projects/demo")
        self.assertEqual(code, 0, err)
        self.assertIn("projects/demo/ep01-bac-thi/link.md: symlink to a file outside the project", err)
        keys = [l.split("  ", 1)[1] for l in (self.pd / ".pulled.sha256").read_text().splitlines()]
        self.assertNotIn("projects/demo/ep01-bac-thi/link.md", keys)
        self.assertIn("projects/demo/ep01-bac-thi/series-link.md", keys)
        for argv in (("pulled", "projects/demo", "ep01-bac-thi/link.md"),
                     ("record", "projects/demo", "--uploaded", "ep01-bac-thi/link.md", "--id", "NEW")):
            code, _, err = self.run_tool(*argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("outside", err)
        code, plan = self.plan()
        self.assertEqual(code, 1)
        self.assertIn({"local": "projects/demo/ep01-bac-thi/link.md", "reason": ds.ESCAPE_REASON}, plan["unmapped"])
        self.assertNotIn("projects/demo/ep01-bac-thi/link.md", [a["local"] for a in plan["actions"]])
        code, _, err = self.run_tool("pulled", "projects/demo", "ep01-bac-thi/series-link.md")
        self.assertEqual(code, 0, err)


LEDGER_HEAD = "ts,kind,model,size,seconds,count,status,out,task_id,usage,agent,note\n"
ROW_A = "2026-11-10T10:00:00Z,image,m,2K,,1,ok,a.png,,,film-plate-maker,req=aa01\n"
ROW_B = "2026-11-10T11:00:00Z,image,m,2K,,1,ok,b.png,,,film-plate-maker,req=bb02\n"


class TestLedgerPreDone(DriveSyncCase):
    def setUp(self):
        super().setUp()
        self.snapshot("--include-out", "out/demo")
        (self.out / "ep01" / "ledger.csv").write_text(LEDGER_HEAD + ROW_A + ROW_B)

    def pre(self):
        code, plan = self.plan("--include-out", "out/demo")
        return self.action(plan, "out/demo/ep01/ledger.csv")["pre"]["ledger_merge"]

    def text(self):
        _, out, _ = self.run_tool("plan", "projects/demo", "--include-out", "out/demo")
        return out.split("CHANGED out/demo/ep01/ledger.csv", 1)[1]

    def test_no_copies_yet(self):
        self.assertNotIn("done", self.pre())
        self.assertIn("this block says `pre done` once every copy is merged", self.text())

    def test_done_when_every_copy_is_merged(self):
        (self.out / "ep01" / "ledger.drive-1.csv").write_text(LEDGER_HEAD + ROW_A)
        (self.out / "ep01" / "ledger.drive-2.csv").write_text(LEDGER_HEAD)
        pre = self.pre()
        self.assertEqual((pre["done"], pre["unmerged"]), (True, []))
        self.assertEqual(pre["copies"], ["out/demo/ep01/ledger.drive-1.csv", "out/demo/ep01/ledger.drive-2.csv"])
        block = self.text()
        self.assertIn("pre          done: every Drive copy (ledger.drive-1.csv, ledger.drive-2.csv) is merged", block)
        self.assertNotIn("ledger-merge", block)

    def test_not_done_lists_the_copy(self):
        extra = "2026-11-10T12:00:00Z,video,v,720p,5,1,ok,c.mp4,t1,,film-animator,req=cc03\n"
        (self.out / "ep01" / "ledger.drive-1.csv").write_text(LEDGER_HEAD + ROW_A + extra)
        pre = self.pre()
        self.assertEqual((pre["done"], pre["unmerged"]), (False, ["out/demo/ep01/ledger.drive-1.csv"]))
        block = self.text()
        self.assertIn("ledger-merge", block)
        self.assertIn("not merged yet: out/demo/ep01/ledger.drive-1.csv", block)

    def test_a_second_identical_row_without_req_is_not_merged(self):
        """Two identical old rows (no req=) are two requests to ledger-merge: one local copy of it is not enough."""
        old = "2026-11-09T09:00:00Z,image,m,2K,,1,ok,o.png,,,film-plate-maker,\n"
        (self.out / "ep01" / "ledger.csv").write_text(LEDGER_HEAD + old + ROW_A + ROW_B)
        (self.out / "ep01" / "ledger.drive-1.csv").write_text(LEDGER_HEAD + old + old)
        self.assertEqual(self.pre()["unmerged"], ["out/demo/ep01/ledger.drive-1.csv"])

    def test_a_copy_that_bills_more_for_a_request_is_not_merged(self):
        more = ROW_A.replace(",1,ok,", ",2,ok,")
        (self.out / "ep01" / "ledger.drive-1.csv").write_text(LEDGER_HEAD + more)
        self.assertEqual(self.pre()["unmerged"], ["out/demo/ep01/ledger.drive-1.csv"])


if __name__ == "__main__":
    unittest.main()
