"""tools/drive_sync.py: snapshot / plan / record round trip on a temp project with fake Drive IDs (no network)."""
import json, os, re, unittest

from helpers import TmpDirCase, load, run_main

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

        new = self.action(plan, "projects/demo/ep01-bac-thi/prompts/s02_L4.txt")
        self.assertEqual(new["status"], "new")
        self.assertIsNone(new["archive"])
        self.assertEqual(new["folder"]["id"], "F-KB-E1-P")
        self.assertEqual(new["create_file"]["contentMimeType"], "text/plain")

    def test_mapping_table(self):
        cases = {
            "PROJECT.md": "00_QuanLy", "SERIES.md": "02_KinhThu",
            "characters/bac-thi/CHARACTER.md": "02_KinhThu/NhanVat/bac-thi",
            "locations/co-son/LOCATION.md": "02_KinhThu/BoiCanh/co-son",
            "style/notes.md": "02_KinhThu/PhongCach",
            "ep01-bac-thi/review/qc-v1.md": "03_KichBan/ep01-bac-thi/review",
            "sources/DanhMuc.csv": "01_TaiLieuGoc",
            "sources/SachThamKhao/SHK_Quach/a.txt": "01_TaiLieuGoc/SachThamKhao/SHK_Quach",
            "notes.txt": None, "random/x.md": None,
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
        self.assertEqual(draft["folder"]["path"], "04_SanXuat/ep01-bac-thi/2026-11-10")
        self.assertEqual(draft["create_file"]["contentMimeType"], "video/mp4")
        self.assertEqual(self.action(plan, "out/demo/ep01/renders/ep01_final_v01.mp4")["folder"],
                         {"path": "05_ThanhPham/ep01-bac-thi", "id": None,
                          "missing": [{"path": "05_ThanhPham/ep01-bac-thi", "name": "ep01-bac-thi",
                                       "parent_path": "05_ThanhPham", "parent_id": "F-TP"}]})
        self.assertEqual(plan["skipped_media"], 2)      # plates travel inside bundles
        self.assertFalse(any("plates" in a["local"] for a in plan["actions"]))

    def test_text_output(self):
        self.snapshot()
        self.write("ep01-bac-thi/script.md", "x\n", append=True)
        code, out, _ = self.run_tool("plan", "projects/demo", "--now", "20261110-1530")
        self.assertEqual(code, 0)
        self.assertIn("CHANGED projects/demo/ep01-bac-thi/script.md", out)
        self.assertIn("search_files parentId = 'F-KB-E1' and title = 'script.md' and trashed = false", out)
        self.assertIn("title=03_KichBan__ep01-bac-thi__script_20261110-1530.md", out)
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


if __name__ == "__main__":
    unittest.main()
