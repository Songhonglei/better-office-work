#!/usr/bin/env python3
"""Revise a bounded part of a page with local Qwen, then archive a review candidate."""
import argparse
import io
import json
import pathlib
import uuid

from PIL import Image, ImageChops, ImageOps

from common import ROOT, atomic_bytes, atomic_json, file_sha, get_page, load_story, read_json, sha, visual_checks
from comfyui import Client, finish_job, receive_image, submit_job
from progress import book_dir, context, entry, find_version, manifest, now, version_dir


def png(image):
    with io.BytesIO() as stream:
        image.save(stream, format="PNG")
        return stream.getvalue()


def read_image(path, mode):
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert(mode)


def source_image(story, no, row, version_id):
    source = find_version(row, version_id)
    if source is None:
        raise ValueError("Choose an archived source version")
    path = version_dir(story, no, source) / "original.image"
    if not path.is_file() or file_sha(path) != source["raw_sha256"]:
        raise ValueError("The archived source image is missing or changed")
    return read_image(path, "RGB"), source


def edit_area(base, mask, padding, size, crop=None):
    if mask.size != base.size or not mask.getbbox():
        raise ValueError("Use a nonempty mask matching the archived original dimensions")
    left, top, right, bottom = mask.getbbox()
    box = (max(0, left - padding), max(0, top - padding),
           min(base.width, right + padding), min(base.height, bottom + padding))
    if crop is not None:
        x1, y1, x2, y2 = crop
        if not (0 <= x1 <= left < right <= x2 <= base.width and 0 <= y1 <= top < bottom <= y2 <= base.height):
            raise ValueError("Crop must be inside the original and contain the entire nonzero mask")
        box = tuple(crop)
    w, h = box[2] - box[0], box[3] - box[1]
    dimensions = tuple(max(128, round(length * size / max(w, h) / 32) * 32) for length in (w, h))
    return box, dimensions


def edit_workflow(args):
    count = 2 if args.reference else 1
    workflow = read_json(ROOT / "workflows" / f"{args.preset}-{count}ref.api.json")
    workflow["5"]["inputs"]["image"] = "source-crop.png"
    if args.reference:
        workflow["10"]["inputs"]["image"] = "detail-reference.png"
    workflow["4"]["inputs"].update(prompt=args.instruction, negative_prompt="", resolution=args.size)
    workflow["9"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}}
    workflow["12"] = {"class_type": "LoadImageMask", "inputs": {"image": "crop-mask.png", "channel": "red"}}
    workflow["13"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["9", 0], "mask": ["12", 0]}}
    workflow["6"]["inputs"].update(latent_image=["13", 0], seed=args.seed, steps=args.steps, denoise=args.denoise)
    workflow["8"]["inputs"]["filename_prefix"] = f"lianhuanhua/{args.slug}/{args.page:03d}-edit"
    return workflow


def compose(base, mask, box, patch, dimensions):
    if patch.size != tuple(dimensions):
        raise ValueError("ComfyUI returned an unexpected revision size")
    adjusted = patch.convert("RGB").resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
    result = base.copy()
    result.paste(adjusted, box[:2], mask.crop(box))
    difference = ImageChops.difference(base, result)
    if not difference.getbbox():
        raise ValueError("Local edit did not change pixels in the mask; inspect the output before retrying")
    outside = mask.point(lambda level: 255 if level == 0 else 0).convert("RGB")
    if ImageChops.multiply(difference, outside).getbbox():
        raise ValueError("Image changed outside the approved editing area")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--page", type=int, required=True)
    parser.add_argument("--preset", choices=("qwen-q4", "qwen-q6"), default="qwen-q4")
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--from-version", help="Defaults to the selected version")
    parser.add_argument("--mask", type=pathlib.Path, help="Full-size grayscale mask. White edits, black preserves")
    parser.add_argument("--instruction", help="Describe the requested visual change in the selected area")
    parser.add_argument("--check", action="append", default=[], help="Include a tracked visual rule in the edit instruction")
    parser.add_argument("--reference", type=pathlib.Path, help="Optional close detail reference for a matching shape")
    parser.add_argument("--padding", type=int, default=64, help="Context around the mask, in original pixels")
    parser.add_argument("--crop", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"), help="Override the automatic crop")
    parser.add_argument("--size", type=int, default=512, help="Longest side of the working image")
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--steps", type=int, default=18)
    parser.add_argument("--denoise", type=float, default=0.87)
    parser.add_argument("--timeout", type=int, default=900)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or args.padding < 0 or not 256 <= args.size <= 1024 or args.size % 32:
        parser.error("Use positive timeout, nonnegative padding and size of 256–1024 divisible by 32")
    if args.resume and (args.mask or args.instruction or args.reference or args.from_version or args.check or args.crop):
        parser.error("Resume uses the saved source, mask and rendering instructions")
    if not args.resume and (not args.mask or not (args.instruction or "").strip()):
        parser.error("Use --mask and --instruction for a new revision")

    story = load_story(args.slug, complete=False)
    page = get_page(story, args.page)
    rules = visual_checks(story, page)
    if set(args.check) - rules.keys() or len(set(args.check)) != len(args.check):
        parser.error("--check must match unique checklist IDs on this page")
    if args.check:
        args.instruction += "\n" + "\n".join(rules[key] for key in args.check)
    _, expected_context = context(story, page)
    row = entry(manifest(story), args.page)
    client = Client(args.server)
    directory = book_dir(story)
    if args.resume:
        job = row.get("job") or {}
        if (job.get("mode") != "local_edit" or job.get("server") != args.server
                or job.get("context_sha256") != expected_context):
            raise ValueError("No matching local revision to resume for this page and context")
        folder = directory / job["edit_inputs"]
        base, source = source_image(story, args.page, row, job["source_version"])
        mask_path = folder / "mask.png"
        if file_sha(mask_path) != job["mask_sha256"] or source["raw_sha256"] != job["source_raw_sha256"]:
            raise ValueError("Saved edit mask or original has changed")
        mask = read_image(mask_path, "L")
        box, dimensions = job["crop"], job["working_size"]
    else:
        if row.get("job") and not (args.dry_run or args.probe):
            raise ValueError("Page already has an in-flight job; resume it before submitting another")
        base, source = source_image(story, args.page, row, args.from_version)
        mask = read_image(args.mask, "L")
        box, dimensions = edit_area(base, mask, args.padding, args.size, args.crop)
        workflow = edit_workflow(args)
        if args.dry_run:
            print(json.dumps({"source": source["id"], "crop": box, "size": dimensions, "workflow": workflow}, indent=2, ensure_ascii=False))
            return
        client.probe(workflow)
        if args.probe:
            print(f"Page {args.page:02d}: edit workflow matches local server, working size {dimensions}")
            return
        jid = str(uuid.uuid4())
        folder = directory / "edit-inputs" / jid
        mask_path = folder / "mask.png"
        atomic_bytes(mask_path, png(mask))
        crop_path, crop_mask = folder / "source-crop.png", folder / "crop-mask.png"
        atomic_bytes(crop_path, png(base.crop(box).resize(dimensions, Image.Resampling.LANCZOS)))
        atomic_bytes(crop_mask, png(mask.crop(box).resize(dimensions, Image.Resampling.BILINEAR)))
        workflow["5"]["inputs"]["image"] = client.upload(crop_path)
        workflow["12"]["inputs"]["image"] = client.upload(crop_mask)
        if args.reference:
            ref_path = folder / "detail-reference.png"
            atomic_bytes(ref_path, png(read_image(args.reference, "RGB")))
            workflow["10"]["inputs"]["image"] = client.upload(ref_path)
        workflow_path = folder / "workflow.api.json"
        atomic_json(workflow_path, workflow)
        job = dict(prompt_id=jid, mode="local_edit", server=args.server, candidate=True, output_node="8",
                   models=[workflow["1"]["inputs"]["unet_name"]], submitted_at=now(), context_sha256=expected_context,
                   source_version=source["id"], source_raw_sha256=source["raw_sha256"], mask_sha256=file_sha(mask_path),
                   workflow_sha256=file_sha(workflow_path), rendered_prompt=args.instruction, crop=box,
                   working_size=dimensions, edit_inputs=str(folder.relative_to(directory)), checks_addressed=args.check)
        if args.reference:
            job["detail_reference_sha256"] = file_sha(ref_path)
        submit_job(client, story, args.page, workflow, job)
    model_bytes, meta = receive_image(client, job, args.timeout)
    atomic_bytes(folder / "model-output.png", model_bytes)
    with Image.open(io.BytesIO(model_bytes)) as patch:
        result = compose(base, mask, box, patch, dimensions)
    finish_job(story, args.page, job, png(result), dict(meta, model_output_sha256=sha(model_bytes), outside_mask_unchanged=True))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
        raise SystemExit(str(exc))
