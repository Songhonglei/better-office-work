#!/usr/bin/env python3
"""Import numbered raw images without overwriting archived versions."""
import argparse
import re
from common import IMAGES, load_story, get_page
from progress import ingest, canvas

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", required=True)
    p.add_argument("--page", type=int)
    p.add_argument("--cut", type=int, help="Deprecated: set story.output.crop_bottom instead")
    p.add_argument("--quality", type=int, help="Deprecated: set story.output.quality instead")
    args = p.parse_args()
    if args.cut is not None or args.quality is not None:
        p.error("Set crop/quality in story.output so verification uses the same settings")
    story = load_story(args.slug, complete=False)
    if args.page is not None:
        get_page(story, args.page)
    root = IMAGES / args.slug / "_raw"
    if not root.is_dir():
        p.error(f"Raw directory not found: {root}")
    inputs = {}
    for f in sorted(root.iterdir()):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        m = re.fullmatch(r"(\d{2})(?:-.*)?\.(?:png|jpe?g|webp)", f.name, re.I)
        if not m:
            p.error(f"Invalid raw filename: {f.name}")
        no = int(m.group(1))
        get_page(story, no)
        if args.page is not None and no != args.page:
            continue
        if no in inputs:
            p.error(f"Duplicate raw page {no:02d}; move candidates to another directory and import explicitly")
        inputs[no] = f
    if not inputs:
        p.error("No matching raw images")
    # Validate every candidate before writing any output.
    for no, f in inputs.items():
        canvas(story, get_page(story, no), f.read_bytes())
    for no, f in inputs.items():
        version = ingest(story, no, f.read_bytes(), "legacy-import", {"source_file": f.name})
        print(f"{f.name} -> {no:03d}.jpg ({version['id']})")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
