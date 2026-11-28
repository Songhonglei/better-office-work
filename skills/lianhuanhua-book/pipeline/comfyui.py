#!/usr/bin/env python3
"""Run an exported ComfyUI API workflow on the local server, one page at a time."""
import argparse
import json
import pathlib
import re
import time
import uuid
from urllib import request, parse, error

from common import ROOT, generation_settings, get_page, identifier, load_story, output_settings, read_json, sha
from progress import _ingest, book_dir, context, entry, locked, manifest, now, save, state

TOKEN = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")

class Client:
    def __init__(self, base):
        url = parse.urlsplit(base)
        if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.path not in ("", "/") or url.query or url.fragment or url.username:
            raise ValueError("Use a local ComfyUI URL, e.g. http://127.0.0.1:8188")
        self.base = base.rstrip("/")
        self.opener = request.build_opener(request.ProxyHandler({}))

    def call(self, route, body=None, headers=None, binary=False):
        req = request.Request(self.base + route, data=body, headers=headers or {})
        try:
            with self.opener.open(req, timeout=30) as response:
                data = response.read()
        except error.HTTPError as e:
            raise RuntimeError(f"ComfyUI HTTP {e.code}: {e.read(4000).decode(errors='replace')}") from e
        except OSError as e:
            raise RuntimeError(f"Cannot reach local ComfyUI at {self.base}: {e}") from e
        return data if binary else json.loads(data)

    def upload(self, path):
        boundary = uuid.uuid4().hex
        filename = sha(path.read_bytes())[:20] + path.suffix.lower()
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                + path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode())
        result = self.call("/upload/image", data, {"Content-Type": "multipart/form-data; boundary=" + boundary})
        return "/".join(x for x in (result.get("subfolder"), result["name"]) if x)

    def submit(self, workflow, prompt_id):
        payload = json.dumps({"prompt": workflow, "client_id": uuid.uuid4().hex, "prompt_id": prompt_id}).encode()
        result = self.call("/prompt", payload, {"Content-Type": "application/json"})
        if result.get("node_errors") or not result.get("prompt_id"):
            raise RuntimeError("ComfyUI rejected workflow: " + json.dumps(result, ensure_ascii=False))
        return result["prompt_id"]

    def probe(self, workflow):
        """Read-only check of node classes, enum choices and numeric ranges."""
        schemas = {}
        for node in workflow.values():
            kind = node["class_type"]
            if kind not in schemas:
                info = self.call("/object_info/" + parse.quote(kind, safe=""))
                if kind not in info:
                    raise ValueError("ComfyUI node is missing: " + kind)
                schemas[kind] = info[kind]
            inputs = schemas[kind].get("input", {})
            fields = inputs.get("required", {}) | inputs.get("optional", {})
            for key, value in node["inputs"].items():
                field = fields.get(key, [])
                if not field or isinstance(value, list):
                    continue
                spec, options = field[0], field[1] if len(field) > 1 else {}
                label = f"{kind}.{key}"
                # References are still local paths at probe time and uploaded only before submission.
                if isinstance(spec, list) and not options.get("image_upload") and value not in spec:
                    raise ValueError(f"{label}: {value!r} is unavailable")
                if spec == "INT" and type(value) is not int:
                    raise ValueError(f"{label}: expected an integer")
                if spec == "FLOAT" and type(value) not in (int, float):
                    raise ValueError(f"{label}: expected a number")
                if spec in ("INT", "FLOAT") and not options.get("min", value) <= value <= options.get("max", value):
                    raise ValueError(f"{label}: {value!r} is outside the server's supported range")

    def wait(self, prompt_id, timeout, interval=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = self.call("/history/" + parse.quote(prompt_id, safe=""))
            if prompt_id in history:
                record = history[prompt_id]
                status = record.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI reported execution failure: " + json.dumps(status)[:4000])
                if status.get("completed") or record.get("outputs"):
                    return record
            time.sleep(interval)
        raise TimeoutError(f"Job {prompt_id} is still pending; rerun with --resume, do not submit again")

    def download(self, image):
        query = parse.urlencode({k: image[k] for k in ("filename", "subfolder", "type")})
        return self.call("/view?" + query, binary=True)


def prepare(template, values):
    if not isinstance(template, dict) or not template or not all(
        isinstance(n, dict) and "class_type" in n and isinstance(n.get("inputs"), dict)
        for n in template.values()
    ):
        raise ValueError("Export workflow in API format (node IDs mapped to class_type and inputs), not regular workflow JSON")
    used = set()
    def replace(obj):
        if isinstance(obj, str):
            m = TOKEN.fullmatch(obj)
            if m:
                key = m.group(1)
                if key not in values:
                    raise ValueError("Unavailable workflow placeholder: " + key)
                used.add(key)
                return values[key]
            if TOKEN.search(obj):
                raise ValueError("A placeholder must be the entire input value")
        elif isinstance(obj, dict):
            return {k: replace(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [replace(v) for v in obj]
        return obj
    result = replace(template)
    if "prompt" not in used:
        raise ValueError("Workflow needs a {{prompt}} input")
    return result, used


def make_values(story, page, seed):
    ctx, fingerprint = context(story, page)
    values = dict(prompt=ctx["prompt"], seed=seed, width=ctx["generation"]["width"],
                  height=ctx["generation"]["height"],
                  negative=story.get("negative", ""),
                  output_prefix=f"lianhuanhua/{story['slug']}/{page['no']:03d}")
    refs = {}
    for i, (name, ref) in enumerate(ctx["references"].items(), 1):
        key = f"reference_{i}"
        if ref["sha256"] is not None:
            refs[key] = book_dir(story) / "cast" / ref["file"]
            values[key] = str(refs[key])
    return values, refs, fingerprint


def submit_job(client, story, no, workflow, job):
    with locked(story):
        data = manifest(story)
        row = entry(data, no)
        if row.get("job"):
            raise ValueError(f"Page {no} already has job {row['job']['prompt_id']}; resume the existing job")
        row["job"] = job
        save(story, data)
        job["prompt_id"] = client.submit(workflow, job["prompt_id"])
        save(story, data)
    print(f"Page {no:02d} queued: {job['prompt_id']}", flush=True)


def receive_image(client, job, timeout):
    record = client.wait(job["prompt_id"], timeout)
    images = record.get("outputs", {}).get(job["output_node"], {}).get("images", [])
    if len(images) != 1:
        raise ValueError(f"Expected one image from node {job['output_node']}; received {len(images)}")
    events = {name: event["timestamp"] for name, event in record.get("status", {}).get("messages", [])
              if "timestamp" in event}
    server_prompt = record.get("prompt", [])
    extra = server_prompt[3] if len(server_prompt) > 3 and isinstance(server_prompt[3], dict) else {}
    timing = {"queued_ms": extra.get("create_time"), "started_ms": events.get("execution_start"),
              "finished_ms": events.get("execution_success")}
    if type(timing["queued_ms"]) is int and type(timing["started_ms"]) is int:
        timing["queue_seconds"] = (timing["started_ms"] - timing["queued_ms"]) / 1000
    if type(timing["started_ms"]) is int and type(timing["finished_ms"]) is int:
        timing["execution_seconds"] = (timing["finished_ms"] - timing["started_ms"]) / 1000
    return client.download(images[0]), dict(job, output_image=images[0], timing=timing)


def finish_job(story, no, job, raw, metadata):
    with locked(story):
        latest = load_story(story["slug"], complete=False)
        row = entry(manifest(latest), no)
        if row.get("job", {}).get("prompt_id") != job["prompt_id"]:
            already = next((v for v in row["versions"] if v["metadata"].get("prompt_id") == job["prompt_id"]), None)
            if already:
                return already
            raise ValueError("Saved job was changed or forgotten; image was not selected")
        if context(latest, get_page(latest, no))[1] != job["context_sha256"]:
            raise ValueError("Story changed during generation; original job retained")
        version = _ingest(latest, no, raw, "comfyui", metadata, not job.get("candidate", False))
        data = manifest(latest)
        entry(data, no).pop("job", None)
        save(latest, data)
    print(f"Page {no:02d}: saved {version['id']} (pending visual review)")
    return version


def run_page(args, story, page, client, template, workflow_hash):
    no = page["no"]
    data = manifest(story)
    row = entry(data, no)
    seed = args.seed + no
    values, refs, fingerprint = make_values(story, page, seed)
    feedback = getattr(args, "revision_note", None)
    task_id = getattr(args, "task_id", None)
    if feedback:
        values["prompt"] += f"\n\n本轮返工要求：{feedback}"
    rendered, used = prepare(template, values)
    if any(n["class_type"] == "TextEncodeQwenImage21" for n in template.values()):
        ctx, _ = context(story, page)
        subjects = [f"<image{i}> = {name}" for i, name in enumerate(ctx["references"], 1)
                    if f"reference_{i}" in used]
        if subjects:
            values["prompt"] += "\nReference characters: " + "; ".join(subjects) + ". Keep their identity and clothing, compose a new scene."
            rendered, used = prepare(template, values)
    if args.output_node not in rendered:
        raise ValueError("Output node ID does not exist")
    if args.dry_run:
        print(json.dumps(rendered, ensure_ascii=False, indent=2))
        return
    if getattr(args, "probe", False):
        client.probe(rendered)
        print(f"Page {no:02d}: server node, choice and range checks passed (no generation)")
        return
    job = row.get("job")
    if job and not args.resume:
        raise ValueError(f"Page {no} already has job {job['prompt_id']}; use --resume")
    if args.resume:
        if not job:
            raise ValueError(f"No saved job for page {no}")
        if job.get("mode", "generation") != "generation":
            raise ValueError("This job is a local revision; resume with comfyui_edit.py")
        if task_id and job.get("task_id") != task_id:
            raise ValueError("The in-flight job belongs to another task")
        if job["context_sha256"] != fingerprint or job["workflow_sha256"] != workflow_hash:
            raise ValueError("Story, reference or workflow changed since submission; restore the original inputs before resuming")
        if job["output_node"] != args.output_node or job["server"] != args.server:
            raise ValueError("Resume using the original server and output node")
    else:
        if isinstance(client, Client):
            client.probe(rendered)
        # Upload only the reference inputs actually consumed by this workflow.
        for key in used & refs.keys():
            values[key] = client.upload(refs[key])
        rendered, _ = prepare(template, values)
        prompt_id = str(uuid.uuid4())
        job = {"prompt_id": prompt_id, "context_sha256": fingerprint,
               "workflow_sha256": workflow_hash, "seed": seed,
               "output_node": args.output_node, "server": args.server,
               "reference_slots": sorted(used & refs.keys()),
               "rendered_prompt": values["prompt"], "submitted_at": now(),
               "candidate": getattr(args, "candidate", False), "mode": "generation"}
        if task_id:
            job["task_id"] = task_id
        models = [n["inputs"]["unet_name"] for n in rendered.values() if "unet_name" in n["inputs"]]
        if models:
            job["models"] = models
        submit_job(client, story, no, rendered, job)
    raw, metadata = receive_image(client, job, args.timeout)
    finish_job(story, no, job, raw, metadata)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--slug", required=True)
    workflow_selection = p.add_mutually_exclusive_group(required=True)
    workflow_selection.add_argument("--workflow", type=pathlib.Path)
    workflow_selection.add_argument("--preset", choices=("qwen-q4", "qwen-q6"),
                                    help="Select local Qwen 0–3 character reference workflows automatically")
    selection = p.add_mutually_exclusive_group(required=True)
    selection.add_argument("--page", type=int)
    selection.add_argument("--pages", type=int, nargs="+", help="Generate the requested missing pages in order")
    selection.add_argument("--samples", action="store_true", help="Generate only the story's declared missing samples")
    selection.add_argument("--all", action="store_true", help="Generate missing pages serially; skip existing or queued pages")
    p.add_argument("--output-node", help="Required for custom workflow, defaults to 8 for Qwen presets")
    p.add_argument("--server", default="http://127.0.0.1:8188")
    p.add_argument("--seed", type=int, default=1000)
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--candidate", action="store_true", help="Archive a proposed replacement without selecting it")
    p.add_argument("--task-id", help="Associate a single-page candidate or resumed job with a rework task")
    p.add_argument("--revision-note", help="Add this feedback to a single-page candidate prompt")
    preview = p.add_mutually_exclusive_group()
    preview.add_argument("--dry-run", action="store_true")
    preview.add_argument("--probe", action="store_true", help="Check server nodes, choices and numeric ranges without queueing")
    args = p.parse_args()
    if args.timeout <= 0 or args.seed < 0 or ((args.resume or args.candidate) and args.page is None):
        p.error("Positive timeout, nonnegative seed and --page for resume required")
    if args.task_id:
        identifier(args.task_id, "task ID")
        if args.page is None or not (args.candidate or args.resume):
            p.error("Task IDs apply to single-page candidates or resumed jobs")
    if args.revision_note and (args.resume or not args.candidate or not args.revision_note.strip() or len(args.revision_note) > 2000):
        p.error("Revision notes apply to new candidates and must be 1–2000 characters")
    story = load_story(args.slug, complete=False)
    if not args.preset and not args.output_node:
        p.error("Custom workflow requires --output-node")
    if args.preset and not args.output_node:
        args.output_node = "8"
    client = Client(args.server)
    numbers = ([args.page] if args.page is not None else story.get("samples", []) if args.samples else
               args.pages if args.pages else [p["no"] for p in story["pages"]])
    if not numbers or len(set(numbers)) != len(numbers):
        p.error("Choose one or more unique pages; --samples requires story.samples")
    for number in numbers:
        get_page(story, number)
    if not args.dry_run:
        client.call("/system_stats")
    for number in numbers:
        story = load_story(args.slug, complete=False)
        page = get_page(story, number)
        if args.page is None and state(story, page)[0] != "missing":
            print(f"Skip page {page['no']:02d}: existing or queued")
            continue
        workflow = args.workflow
        if args.preset:
            ctx, _ = context(story, page)
            count = len(ctx["references"])
            if count > 3 or any(v["sha256"] is None for v in ctx["references"].values()):
                raise ValueError("Qwen presets need 0–3 existing character references; use a custom workflow otherwise")
            workflow = ROOT / "workflows" / f"{args.preset}-{count}ref.api.json"
        template = read_json(workflow)
        workflow_hash = sha(workflow.read_bytes())
        if args.preset and output_settings(story).get("fit") == "strict":
            if any(value % 32 for value in generation_settings(story).values()):
                raise ValueError("Strict Qwen presets require generation width and height divisible by 32")
            if count:
                # Use the character image as visual guidance and sample on the story canvas.
                # The encoder's own latent size otherwise follows the first reference image.
                template["4"]["inputs"].pop("vae")
                template["100"] = {
                    "class_type": "EmptyLatentImage",
                    "inputs": {"width": "{{width}}", "height": "{{height}}", "batch_size": 1},
                }
                template["6"]["inputs"]["latent_image"] = ["100", 0]
                workflow_hash = sha(json.dumps(template, sort_keys=True).encode())
        run_page(args, story, page, client, template, workflow_hash)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, TimeoutError, OSError) as exc:
        raise SystemExit(str(exc))
