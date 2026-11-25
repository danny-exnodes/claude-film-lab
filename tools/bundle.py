#!/usr/bin/env python3
"""Zip one shot's media for a single Drive upload (docs/CONVENTIONS.md §9).

  python3 tools/bundle.py out/<project>/<id> --shot s03 [--episode-dir projects/<project>/<episode folder>]

<id> is ep<NN> (episode folder ep<NN>-<slug>) or, for a project split into books, q<NN>t<NN> (episode folder
q<NN>-t<NN>-<slug>); docs/CONVENTIONS.md §2, tools/episode_id.py.

The zip holds every file under plates/ and clips/ whose name contains `_s03_`, the prompts.csv rows for
that shot (header kept) and the anchors.json entries for that shot's files, if those files exist. It is
written to out/<project>/<id>/bundles/<id>_s03_<YYYYMMDD>.zip (UTC date; same-day re-runs replace it).
Without --episode-dir the episode text folder is looked up in the project working copy
projects/<project>/<ep<NN>|q<NN>-t<NN>>-*/ (git-ignored, pulled from Drive), then in the legacy series/<project>/.
The zip goes to Drive ClaudeFilmLab/<ProjectName>/04_SanXuat/<episode folder>/<YYYY-MM-DD>/ (docs/CONVENTIONS.md §11).
Prints the path, size and the Drive connector file reference `sha256:<hex>:<absolute path>`.
"""
import argparse, csv, datetime, glob, hashlib, io, json, os, re, shutil, sys, zipfile

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(LAB, "tools"))
import episode_id  # noqa: E402
STORED = {".png", ".jpg", ".jpeg", ".mp4", ".webp", ".zip"}   # already compressed


EPISODE_ROOTS = ("projects", "series")   # project working copy first; series/ is the pre-Drive layout


def find_series_dir(media):
    """Episode text folder for out/<project>/<id>: projects/<project>/<ep<NN>|q<NN>-t<NN>>-*/ (or legacy series/...)."""
    ep = os.path.basename(os.path.normpath(media))
    project = os.path.basename(os.path.dirname(os.path.abspath(media)))
    if episode_id.parse_id(ep) is None:
        return None
    hits = []
    for root in EPISODE_ROOTS:
        hits = sorted(d for d in glob.glob(os.path.join(LAB, root, project, episode_id.dir_prefix(ep) + "-*"))
                      if os.path.isdir(d) and (episode_id.parse_dir(os.path.basename(d)) or ("",))[0] == ep)
        if hits:
            break
    if len(hits) > 1:
        print(f"warning: several episode folders match, using {hits[0]}", file=sys.stderr)
    return hits[0] if hits else None


def shot_media(media, shot):
    tag = f"_{shot}_"
    found = []
    for sub in ("plates", "clips"):
        root_dir = os.path.join(media, sub)
        for root, _dirs, names in os.walk(root_dir):
            for n in sorted(names):
                if tag in n:
                    full = os.path.join(root, n)
                    found.append((full, os.path.relpath(full, media)))
    return sorted(found, key=lambda x: x[1])


def prompts_rows(series_dir, shot):
    path = os.path.join(series_dir, "prompts.csv") if series_dir else None
    if not path or not os.path.isfile(path):
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return None
    header = rows[0]
    if "shot" not in header:
        print(f"warning: {path} has no 'shot' column; prompts not bundled", file=sys.stderr)
        return None
    i = header.index("shot")
    keep = [r for r in rows[1:] if len(r) > i and r[i].strip() == shot]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")   # RFC 4180
    w.writerow(header)
    w.writerows(keep)
    return buf.getvalue(), len(keep)


def anchors_for(series_dir, shot):
    path = os.path.join(series_dir, "anchors.json") if series_dir else None
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sub = {k: v for k, v in data.items() if f"_{shot}_" in k}
    return json.dumps(sub, ensure_ascii=False, indent=2, sort_keys=True) + "\n", len(sub)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


FILM_TEXT_EXT = {".html", ".md", ".json", ".js", ".mjs", ".txt", ".csv", ".yaml", ".yml"}
FILM_SKIP_DIRS = {"node_modules", "renders", "frames", "cache", ".cache", "stills"}


def film_text_files(media):
    """Text sources of the cinecode film folder(s) under <media>/film (film.html, STATE.md, review/*.md, audio/mix.json...).

    Media and render output are skipped: they are large and rebuilt from these sources."""
    root = os.path.join(media, "film")
    out = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in FILM_SKIP_DIRS and not d.startswith("."))
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() in FILM_TEXT_EXT:
                full = os.path.join(dp, fn)
                out.append((full, os.path.join("film", os.path.relpath(full, root))))
    return out


def add_member(z, arc, compress_type, src=None, data=None):
    """Write one zip member with fixed metadata (1980-01-01, mode 0644), from file `src` or text/bytes `data`.

    No mtime, no file mode, no clock: the same inputs give the same zip bytes, so an unchanged re-run keeps its
    sha256 and drive_sync.py does not plan the bundle for upload again."""
    info = zipfile.ZipInfo(arc.replace(os.sep, "/"), date_time=(1980, 1, 1, 0, 0, 0))
    info.external_attr = 0o644 << 16
    info.compress_type = compress_type
    if src is None:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with z.open(info, "w") as dst:
            dst.write(payload)
        return
    with open(src, "rb") as f, z.open(info, "w", force_zip64=os.path.getsize(src) >= 1 << 31) as dst:
        shutil.copyfileobj(f, dst, 1 << 20)


def bundle(media, shot, series_dir=None, today=None, with_film=False):
    if not episode_id.RE_SHOT.match(shot):
        raise SystemExit(f"--shot must be s<NN> or s<NNN> (got {shot!r})")
    if not os.path.isdir(media):
        raise SystemExit(f"{media}: media folder not found")
    ep = os.path.basename(os.path.normpath(media))
    if episode_id.parse_id(ep) is None:
        raise SystemExit(f"{media}: expected out/<project>/ep<NN> or out/<project>/q<NN>t<NN>")
    series_dir = series_dir or find_series_dir(media)
    files = shot_media(media, shot)
    if not files:
        raise SystemExit(f"no files containing _{shot}_ under {media}/plates or {media}/clips")
    day = (today or datetime.datetime.now(datetime.timezone.utc).date()).strftime("%Y%m%d")
    out = os.path.join(os.path.abspath(media), "bundles", f"{ep}_{shot}_{day}.zip")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".part"
    notes = []
    with zipfile.ZipFile(tmp, "w") as z:
        for full, arc in files:
            comp = zipfile.ZIP_STORED if os.path.splitext(full)[1].lower() in STORED else zipfile.ZIP_DEFLATED
            add_member(z, arc, comp, src=full)
        pr = prompts_rows(series_dir, shot)
        if pr:
            add_member(z, "prompts.csv", zipfile.ZIP_DEFLATED, data=pr[0])
            notes.append(f"prompts.csv ({pr[1]} row(s))")
        if with_film:
            ft = film_text_files(media)
            for full, arc in ft:
                add_member(z, arc, zipfile.ZIP_DEFLATED, src=full)
            notes.append(f"film sources ({len(ft)} text file(s))")
        an = anchors_for(series_dir, shot)
        if an:
            add_member(z, "anchors.json", zipfile.ZIP_DEFLATED, data=an[0])
            notes.append(f"anchors.json ({an[1]} file(s))")
    os.replace(tmp, out)
    return out, files, notes, series_dir


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__.split("\n\n", 1)[1])
    p.add_argument("media", help="out/<project>/<id> (ep<NN> or q<NN>t<NN>)")
    p.add_argument("--shot", required=True, help="shot id, e.g. s03")
    p.add_argument("--episode-dir", "--series-dir", dest="series_dir", default=None,
                   help="projects/<project>/<episode folder> (prompts.csv, anchors.json); default: looked up")
    p.add_argument("--with-film", action="store_true",
                   help="also include the cinecode film sources under <media>/film (html, md, json...; no media)")
    a = p.parse_args(argv)
    out, files, notes, sdir = bundle(a.media, a.shot, a.series_dir, with_film=a.with_film)
    size = os.path.getsize(out)
    print(f"bundle {out}")
    print(f"files  {len(files)} media" + (", " + ", ".join(notes) if notes else "")
          + ("" if sdir else " (no episode dir found under projects/: prompts.csv/anchors.json not included)"))
    print(f"size   {size} bytes ({size / 1e6:.2f} MB)")
    print(f"drive  sha256:{sha256(out)}:{out}")


if __name__ == "__main__":
    main()
