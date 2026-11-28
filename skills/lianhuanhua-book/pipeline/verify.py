#!/usr/bin/env python3
"""Strict programmatic verification and optional visual-review gate."""
import argparse
from PIL import Image
from common import IMAGES, expected_size, load_story, output_settings, page_file
from progress import manifest, state

def check(story, require_approved=False):
    img_dir = IMAGES / story["slug"]
    issues = []
    data = manifest(story)
    for page in story["pages"]:
        f = img_dir / page_file(page)
        if not f.is_file():
            issues.append(f"Missing {f.name}")
            continue
        try:
            with Image.open(f) as im:
                im.load()
                if im.format != "JPEG":
                    issues.append(f"{f.name}: not JPEG")
                if im.size != expected_size(story, page):
                    issues.append(f"{f.name}: {im.size}, expected {expected_size(story, page)}")
        except (OSError, ValueError) as e:
            issues.append(f"{f.name}: unreadable image: {e}")
            continue
        if f.stat().st_size > output_settings(story)["max_kb"] * 1024:
            issues.append(f"{f.name}: size exceeds max_kb")
        status, _ = state(story, page, data)
        if status in ("stale", "missing_or_changed", "rejected", "generating"):
            issues.append(f"{f.name}: {status}")
        if require_approved and status != "approved":
            issues.append(f"{f.name}: visual review not approved ({status})")
    extra = sorted(p.name for p in img_dir.glob("*.jpg") if p.name not in {page_file(p) for p in story["pages"]})
    if extra:
        issues.append("Extra pages: " + ", ".join(extra))
    return issues

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", required=True)
    p.add_argument("--require-approved", action="store_true")
    args = p.parse_args()
    try:
        story = load_story(args.slug)
        issues = check(story, args.require_approved)
    except (ValueError, OSError) as e:
        issues = [str(e)]
    if issues:
        print("FAIL:\n" + "\n".join(issues))
        return 1
    print("PASS: page count, dimensions, JPEG integrity, file size and version checks" +
          ("; visual approvals complete" if args.require_approved else "; visual approval not checked"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
