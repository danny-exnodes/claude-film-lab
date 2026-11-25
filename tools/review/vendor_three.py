#!/usr/bin/env python3
"""Copy the pinned three.js into the review web app (tools/review/web/vendor/three/, git-ignored). Standard library only.

  python tools/review/vendor_three.py --from <three package dir>     # e.g. <some project>/node_modules/three
  python tools/review/vendor_three.py --check                         # verify what is already in web/vendor/three/

Core files (build/three.module.js, build/three.core.js) must match tools/toon/three.lock (the lab's one pinned
three.js). The example modules the web app imports (GLTFLoader, OrbitControls, BufferGeometryUtils and SkeletonUtils,
which GLTFLoader imports) are checked against tools/review/three-examples.lock: a file the lock pins must match; a
file it does not pin yet is recorded (the lock is committed, so a later copy has to be the same bytes).
Nothing is downloaded. Exit: 0 ok · 2 refused (version or hash mismatch, missing file; nothing copied).
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = os.path.dirname(os.path.dirname(HERE))
CORE_LOCK = os.path.join(LAB, "tools", "toon", "three.lock")
EXAMPLES_LOCK = os.path.join(HERE, "three-examples.lock")
DEST = os.path.join(HERE, "web", "vendor", "three")
CORE = ("build/three.module.js", "build/three.core.js")
EXAMPLES = ("examples/jsm/loaders/GLTFLoader.js", "examples/jsm/controls/OrbitControls.js",
            "examples/jsm/utils/BufferGeometryUtils.js", "examples/jsm/utils/SkeletonUtils.js")
FILES = CORE + EXAMPLES
HEADER = ("# three.js example modules vendored into the review web app (tools/review/vendor_three.py).\n"
          "# Same release as tools/toon/three.lock; MIT (THIRD_PARTY.md). Change on purpose only.\n")


class Refused(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_lock(path):
    """-> (version or None, {relpath: sha256})."""
    version, pins = None, {}
    if not os.path.isfile(path):
        return version, pins
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if not parts or parts[0].startswith("#"):
                continue
            if parts[0] == "version" and len(parts) == 2:
                version = parts[1]
            elif parts[0] == "sha256" and len(parts) == 3:
                pins[parts[1]] = parts[2].lower()
    return version, pins


def write_lock(path, version, pins):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER)
        f.write(f"version {version}\n")
        for rel in EXAMPLES:
            if rel in pins:
                f.write(f"sha256 {rel} {pins[rel]}\n")
    os.replace(tmp, path)


def package_version(src):
    try:
        with open(os.path.join(src, "package.json"), encoding="utf-8") as f:
            return json.load(f).get("version")
    except (OSError, ValueError):
        return None


def plan(src, core_lock=CORE_LOCK, examples_lock=EXAMPLES_LOCK):
    """Check every file of src. -> (version, {rel: sha}, new pins to record). Raises Refused."""
    cver, cpins = read_lock(core_lock)
    if not cver or not all(r in cpins for r in CORE):
        raise Refused(f"{core_lock} has no version or no pin for {', '.join(CORE)}")
    ver = package_version(src)
    if ver != cver:
        raise Refused(f"{src}: three.js {ver or '?'} is not the pinned {cver} ({core_lock})")
    ever, epins = read_lock(examples_lock)
    if ever and ever != cver:
        raise Refused(f"{examples_lock} pins three.js {ever}, the core lock {cver}: update both on purpose")
    hashes, new = {}, {}
    for rel in FILES:
        path = os.path.join(src, *rel.split("/"))
        if not os.path.isfile(path):
            raise Refused(f"missing {path}")
        h = sha256(path)
        hashes[rel] = h
        want = cpins.get(rel) if rel in CORE else epins.get(rel)
        if want and want != h:
            raise Refused(f"{rel}: sha256 {h} differs from the lock ({want})")
        if not want:
            new[rel] = h
    return cver, hashes, new


def copy(src, dest=DEST, core_lock=CORE_LOCK, examples_lock=EXAMPLES_LOCK):
    version, hashes, new = plan(src, core_lock, examples_lock)
    for rel in FILES:
        target = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        shutil.copyfile(os.path.join(src, *rel.split("/")), tmp)
        if sha256(tmp) != hashes[rel]:
            os.remove(tmp)
            raise Refused(f"{rel}: the copy does not match its source")
        os.replace(tmp, target)
    if new:
        _, pins = read_lock(examples_lock)
        pins.update(new)
        write_lock(examples_lock, version, pins)
    return version, hashes, new


def verify(dest=DEST, core_lock=CORE_LOCK, examples_lock=EXAMPLES_LOCK):
    """Problems with the vendored files (empty list = ready to serve)."""
    _, cpins = read_lock(core_lock)
    _, epins = read_lock(examples_lock)
    problems = []
    for rel in FILES:
        path = os.path.join(dest, *rel.split("/"))
        want = cpins.get(rel) if rel in CORE else epins.get(rel)
        if not os.path.isfile(path):
            problems.append(f"missing {rel}")
        elif not want:
            problems.append(f"{rel} is not pinned in {os.path.basename(examples_lock if rel in EXAMPLES else core_lock)}")
        elif sha256(path) != want:
            problems.append(f"{rel} does not match its pinned sha256")
    return problems


def main(argv=None):
    p = argparse.ArgumentParser(prog="vendor_three.py", description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--from", dest="src", help="an installed three package folder (has package.json, build/, examples/)")
    g.add_argument("--check", action="store_true", help="verify the vendored files against the locks")
    p.add_argument("--dest", default=DEST, help=argparse.SUPPRESS)
    p.add_argument("--core-lock", default=CORE_LOCK, help=argparse.SUPPRESS)
    p.add_argument("--lock", default=EXAMPLES_LOCK, help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.check:
        problems = verify(a.dest, a.core_lock, a.lock)
        for x in problems:
            print(f"vendor: {x}", file=sys.stderr)
        if problems:
            print("vendor: run python tools/review/vendor_three.py --from <three package dir>", file=sys.stderr)
            return 2
        print(f"vendor: {len(FILES)} files ok in {a.dest}")
        return 0
    try:
        version, hashes, new = copy(os.path.abspath(a.src), a.dest, a.core_lock, a.lock)
    except Refused as e:
        print(f"vendor: refused: {e} (nothing copied)", file=sys.stderr)
        return 2
    for rel in FILES:
        print(f"{'recorded' if rel in new else 'ok      '} {hashes[rel]}  {rel}")
    print(f"vendor: three.js {version} -> {a.dest}" + (f"; {len(new)} new pin(s) in {a.lock}" if new else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
