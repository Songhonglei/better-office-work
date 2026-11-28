#!/usr/bin/env python3
"""Copy the reusable runtime into a new empty project folder."""
import argparse
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parent.parent
def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=pathlib.Path)
    args = p.parse_args()
    dest = args.directory.resolve()
    if dest == ROOT or (dest.exists() and (not dest.is_dir() or any(dest.iterdir()))):
        p.error("Choose a new or empty project directory")
    dest.mkdir(parents=True, exist_ok=True)
    for folder in ("pipeline", "templates", "styles", "references", "workflows"):
        shutil.copytree(ROOT / folder, dest / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (dest / "stories").mkdir()
    for template in (ROOT / "stories").glob("_*.json"):
        shutil.copy2(template, dest / "stories" / template.name)
    for name in ("serve.sh", "requirements.txt", ".gitignore"):
        shutil.copy2(ROOT / name, dest / name)
    (dest / "assets" / "images").mkdir(parents=True)
    print(dest)
if __name__ == "__main__":
    main()
