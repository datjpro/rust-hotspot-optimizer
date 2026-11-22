#!/usr/bin/env python3
"""Validate and package this skill repository into a distributable `.skill` archive.

Usage:
    python scripts/package_skill.py [--out dist/rust-hotspot-optimizer.skill]
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
INCLUDE_DIRS = ("references", "assets", "scripts")
EXCLUDE_NAMES = {"package_skill.py", "__pycache__", ".DS_Store", "Thumbs.db"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def validate_skill(root: Path) -> str:
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        sys.exit(f"error: SKILL.md not found in {root}")
    text = skill_md.read_text(encoding="utf-8")
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        sys.exit("error: SKILL.md is missing YAML frontmatter (--- ... ---)")
    fm = m.group(1)
    name_m = re.search(r"^name:\s*([a-z0-9][a-z0-9-]*)\s*$", fm, re.MULTILINE)
    desc_m = re.search(r"^description:\s*\S+", fm, re.MULTILINE)
    if not name_m:
        sys.exit("error: SKILL.md frontmatter must declare a valid lowercase `name:`")
    if not desc_m:
        sys.exit("error: SKILL.md frontmatter must declare `description:`")

    # Verify every scripts/, references/, assets/ file path mentioned in SKILL.md exists.
    missing = []
    for ref in sorted(set(re.findall(r"`((?:scripts|references|assets)/[^`\s]+)`", text))):
        if ref.endswith("/"):
            if not (root / ref).is_dir():
                missing.append(ref)
        elif not (root / ref).exists():
            missing.append(ref)
    if missing:
        sys.exit("error: SKILL.md references missing paths:\n  " + "\n  ".join(missing))
    return name_m.group(1)


def collect_files(root: Path):
    files = [root / "SKILL.md"]
    for sub in INCLUDE_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if any(part in EXCLUDE_NAMES for part in p.parts):
                continue
            if p.suffix in EXCLUDE_SUFFIXES:
                continue
            files.append(p)
    return files


def package(root: Path, out_path: Path) -> int:
    skill_name = validate_skill(root)
    files = collect_files(root)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = f"{skill_name}/{f.relative_to(root).as_posix()}"
            zf.write(f, arcname)
    return len(files)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(SKILL_ROOT / "dist" / "rust-hotspot-optimizer.skill"),
                    help="output .skill archive path")
    args = ap.parse_args()
    out_path = Path(args.out)
    count = package(SKILL_ROOT, out_path)
    print(f"packaged {count} files -> {out_path} ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
