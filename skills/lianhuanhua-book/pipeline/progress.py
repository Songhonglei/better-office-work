"""Page versions, review decisions, resumable generation and provenance."""
import argparse
import datetime
import fcntl
import io
import json
import pathlib
import uuid
from contextlib import contextmanager

from PIL import Image, ImageOps
from common import (IMAGES, atomic_bytes, atomic_json, expected_size, file_sha, generation_settings,
                    get_page, load_story, output_settings, read_json, sha, visual_checks)
from make_prompts import pick_names, render_page


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def book_dir(story):
    return IMAGES / story["slug"]


def manifest(story):
    f = book_dir(story) / "progress.json"
    return read_json(f) if f.exists() else {"schema": 1, "pages": {}}


def save(story, data):
    atomic_json(book_dir(story) / "progress.json", data)


@contextmanager
def locked(story):
    directory = book_dir(story)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".progress.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def entry(data, no):
    return data["pages"].setdefault(str(no), {"versions": [], "selected": None})


def canvas(story, page, raw):
    """Apply the configured canvas fit and optional bottom crop."""
    settings = output_settings(story)
    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        width, height = settings["width"], settings["height"]
        if settings.get("fit") == "strict":
            if im.width * height != im.height * width:
                raise ValueError(f"Original image {im.width}×{im.height} does not match "
                                 f"the {width}×{height} canvas ratio. Regenerate at the target aspect ratio.")
            im = im.resize((width, height), Image.Resampling.LANCZOS)
        else:
            im = ImageOps.pad(im, (width, height), method=Image.Resampling.LANCZOS, color="white")
        size = expected_size(story, page)
        im = im.crop((0, 0, size[0], size[1]))
        for quality in range(settings["quality"], 39, -4):
            out = io.BytesIO()
            im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
            data = out.getvalue()
            if len(data) <= settings["max_kb"] * 1024:
                return data
    raise ValueError("Image exceeds max_kb even after compression; adjust output settings")


def context(story, page):
    prompt = render_page(story, page)
    refs = {}
    names = pick_names(story, page)
    for c in story["cast"]:
        if c["name"] in names and c.get("reference"):
            f = book_dir(story) / "cast" / c["reference"]
            refs[c["name"]] = {"file": c["reference"], "sha256": file_sha(f) if f.is_file() else None}
    payload = {"prompt": prompt, "caption": page["caption"], "title": page["title"],
               "references": refs, "output": output_settings(story), "generation": generation_settings(story)}
    checks = visual_checks(story, page)
    if checks:
        payload["visual_checks"] = checks
    return payload, sha(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())


def find_version(row, version_id=None):
    selected = version_id if version_id is not None else row.get("selected")
    return next((v for v in row["versions"] if v["id"] == selected), None)


def version_dir(story, no, version):
    return book_dir(story) / "versions" / f"{no:03d}" / version["id"]


def select(story, data, no, version):
    folder = version_dir(story, no, version)
    image = folder / "render.jpg"
    if not image.is_file() or file_sha(image) != version["image_sha256"]:
        raise ValueError("Archived image missing or changed")
    atomic_bytes(book_dir(story) / f"{no:03d}.jpg", image.read_bytes())
    entry(data, no)["selected"] = version["id"]
    save(story, data)


def ingest(story, no, raw, backend="manual", metadata=None, select_version=True):
    with locked(story):
        return _ingest(story, no, raw, backend, metadata, select_version)


def _ingest(story, no, raw, backend, metadata, select_version):
    page = get_page(story, no)
    ctx, fingerprint = context(story, page)
    if any(ref["sha256"] is None for ref in ctx["references"].values()):
        raise ValueError("A declared character reference is missing; add it or update the cast")
    data = manifest(story)
    row = entry(data, no)
    raw_digest = sha(raw)
    selected = find_version(row)
    if backend == "legacy-import" and any(
        x["raw_sha256"] == raw_digest and x["context_sha256"] != fingerprint
        for x in row["versions"]
    ):
        if not any(x["raw_sha256"] == raw_digest and x["context_sha256"] == fingerprint for x in row["versions"]):
            raise ValueError("Raw image was generated under an older prompt; regenerate or explicitly import and review")
    task_id = (metadata or {}).get("task_id")
    existing = next((v for v in row["versions"] if v["raw_sha256"] == raw_digest and v["context_sha256"] == fingerprint
                     and (not task_id or v.get("metadata", {}).get("task_id") == task_id)), None)
    if existing:
        # A rerun of the legacy batch must not undo a newer manual selection.
        if backend == "legacy-import" and selected and selected["id"] != existing["id"]:
            return existing
        target = book_dir(story) / f"{no:03d}.jpg"
        if select_version and (not selected or selected["id"] != existing["id"]
                               or not target.is_file() or file_sha(target) != existing["image_sha256"]):
            select(story, data, no, existing)
        return existing
    jpg = canvas(story, page, raw)
    v = dict(id=uuid.uuid4().hex[:12], created=now(), backend=backend,
             raw_sha256=raw_digest, image_sha256=sha(jpg), context_sha256=fingerprint,
             context=ctx, metadata=metadata or {}, review="pending")
    folder = version_dir(story, no, v)
    # Keep the exact original bytes; the format is recorded by the image itself.
    atomic_bytes(folder / "original.image", raw)
    atomic_bytes(folder / "render.jpg", jpg)
    atomic_bytes(folder / "prompt.txt", ctx["prompt"].encode())
    for i, ref in enumerate(ctx["references"].values(), 1):
        source = book_dir(story) / "cast" / ref["file"]
        original = source.read_bytes()
        if sha(original) != ref["sha256"]:
            raise ValueError("Character reference changed during import")
        atomic_bytes(folder / "references" / f"{i:02d}{source.suffix}", original)
    row["versions"].append(v)
    save(story, data)
    if select_version:
        select(story, data, no, v)
    return v


def state(story, page, data=None):
    data = manifest(story) if data is None else data
    row = data["pages"].get(str(page["no"]), {"versions": [], "selected": None})
    v = find_version(row)
    f = book_dir(story) / f"{page['no']:03d}.jpg"
    if row.get("job"):
        return "generating", v
    if not v:
        return ("untracked" if f.exists() else "missing"), None
    if not f.is_file() or file_sha(f) != v["image_sha256"]:
        return "missing_or_changed", v
    if v["context_sha256"] != context(story, page)[1]:
        return "stale", v
    if v["review"] == "approved" and not check_results(visual_checks(story, page), v.get("review_checks")):
        return "pending", v
    return v["review"], v


def check_results(rules, results, *, require_pass=True):
    results = {} if results is None else results
    if not isinstance(results, dict) or results.keys() - rules.keys():
        return False
    if require_pass and results.keys() != rules.keys():
        return False
    return all(isinstance(item, dict) and set(item) == {"status", "note"}
               and item["status"] in (("pass",) if require_pass else ("pass", "fail", "unverified"))
               and isinstance(item["note"], str) and item["note"].strip() for item in results.values())


def review(story, no, decision, note, checks=None, version_id=None, promote=False):
    if not note.strip():
        raise ValueError("Review note must not be empty")
    p = get_page(story, no)
    rules = visual_checks(story, p)
    if not check_results(rules, checks, require_pass=decision == "approved"):
        raise ValueError("Review checks must use this page's exact checklist and visual notes; approval requires all pass")
    with locked(story):
        data = manifest(story)
        row = entry(data, no)
        v = find_version(row, version_id)
        if row.get("job") or not v or v["context_sha256"] != context(story, p)[1]:
            raise ValueError("Choose a current version to review after its generation completes")
        image = (version_dir(story, no, v) / "render.jpg" if version_id is not None
                 else book_dir(story) / f"{no:03d}.jpg")
        if not image.is_file() or file_sha(image) != v["image_sha256"]:
            raise ValueError("Image missing or changed")
        v.update(review=decision, review_note=note, reviewed=now())
        if rules:
            v["review_checks"] = checks or {}
        if promote:
            select(story, data, no, v)
        else:
            save(story, data)


def checklist(story, pages, version_id=None):
    data = manifest(story)
    output = []
    for p in pages:
        row = entry(data, p["no"])
        status, _ = state(story, p, data)
        v = find_version(row, version_id)
        if version_id is not None and v is None:
            raise ValueError(f"Page {p['no']}: version not found")
        fingerprint = context(story, p)[1]
        current = v and v["context_sha256"] == fingerprint
        results = v.get("review_checks", {}) if current else {}
        rules = visual_checks(story, p)
        output.append(dict(page=p["no"], title=p["title"], selected=row["selected"], status=status,
                           version=v["id"] if v else None, current=bool(current), rules=rules,
                           results={key: results.get(key, {"status": "unverified", "note": ""}) for key in rules},
                           candidates=[x["id"] for x in row["versions"] if x["id"] != row["selected"]
                                       and x["review"] == "pending" and x["context_sha256"] == fingerprint],
                           job=row.get("job", {}).get("prompt_id")))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    check = sub.add_parser("checklist", help="Read page rules, selected versions and visual findings as JSON")
    check.add_argument("--page", type=int)
    check.add_argument("--version")
    imp = sub.add_parser("import")
    imp.add_argument("--page", type=int, required=True)
    imp.add_argument("--file", type=pathlib.Path, required=True)
    imp.add_argument("--backend", default="manual")
    for name in ("approve", "reject", "versions", "rollback", "forget-job"):
        p = sub.add_parser(name)
        p.add_argument("--page", required=True, type=int)
        if name in ("approve", "reject"):
            p.add_argument("--note", required=True)
            p.add_argument("--checks-file", type=pathlib.Path)
            p.add_argument("--version")
        if name == "approve":
            p.add_argument("--select", action="store_true", help="Select the reviewed archive version for the reader")
        if name == "rollback":
            p.add_argument("--version", required=True)
        if name == "forget-job":
            p.add_argument("--note", required=True, help="Confirm server job is no longer running")
    args = parser.parse_args()
    story = load_story(args.slug, complete=False)
    if args.command == "status":
        data = manifest(story)
        for p in story["pages"]:
            status, v = state(story, p, data)
            print(f"{p['no']:02d} {p['title']}: {status} {v['id'] if v else ''}")
    elif args.command == "checklist":
        if args.version and args.page is None:
            parser.error("--version requires --page")
        pages = story["pages"] if args.page is None else [get_page(story, args.page)]
        print(json.dumps(checklist(story, pages, args.version), ensure_ascii=False, indent=2))
    elif args.command == "import":
        v = ingest(story, args.page, args.file.read_bytes(), args.backend,
                   {"source_file": args.file.name})
        print(v["id"])
    elif args.command in ("approve", "reject"):
        results = read_json(args.checks_file) if args.checks_file else None
        review(story, args.page, "approved" if args.command == "approve" else "rejected", args.note,
               results, args.version, getattr(args, "select", False))
    else:
        get_page(story, args.page)
        with locked(story):
            data = manifest(story)
            row = entry(data, args.page)
            if args.command == "versions":
                for v in row["versions"]:
                    print(v["id"], v["created"], v["backend"], v["review"],
                          "(selected)" if row["selected"] == v["id"] else "")
            elif args.command == "forget-job":
                if not row.get("job"):
                    raise ValueError("No saved job to forget")
                row.setdefault("abandoned_jobs", []).append(dict(row.pop("job"), reason=args.note, abandoned=now()))
                save(story, data)
            else:
                v = find_version(row, args.version)
                if not v:
                    raise ValueError("Version not found")
                select(story, data, args.page, v)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc))
