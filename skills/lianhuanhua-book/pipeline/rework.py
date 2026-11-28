#!/usr/bin/env python3
"""Persistent single-page ComfyUI rework tasks created from version annotations."""
import argparse
import fcntl
import json
import subprocess
import sys
import uuid
from contextlib import contextmanager

from common import ROOT, atomic_json, get_page, load_story, read_json
from progress import book_dir, context, entry, find_version, locked, manifest, now


ACTIVE = {"running", "paused"}


def queue_path(story):
    return book_dir(story) / "rework.json"


def queue_data(story):
    path = queue_path(story)
    return read_json(path) if path.is_file() else {"schema": 1, "tasks": []}


def priority(value):
    if type(value) is not int or not 1 <= value <= 5:
        raise ValueError("优先级需为 1 到 5，5 最先执行")
    return value


def enqueue(story, number, version, note_id, rank=3, preset="qwen-q4"):
    page = get_page(story, number)
    rank = priority(rank)
    if preset not in ("qwen-q4", "qwen-q6"):
        raise ValueError("请选择本机 Q4 或 Q6 工作流")
    with locked(story):
        row = entry(manifest(story), number)
        if not isinstance(version, str) or not find_version(row, version):
            raise ValueError("批注对应的图片版本不存在")
        notes_file = book_dir(story) / "workbench.json"
        notes = read_json(notes_file).get("notes", {}).get(str(number), []) if notes_file.is_file() else []
        note = next((item for item in notes if item["id"] == note_id and item["version"] == version), None)
        if not note:
            raise ValueError("找不到这个版本的批注")
        data = queue_data(story)
        existing = next((task for task in data["tasks"] if task["annotation"] == note_id and task["status"] != "cancelled"), None)
        if existing:
            return existing
        tid = uuid.uuid4().hex
        task = dict(id=tid, page=number, source_version=version, annotation=note_id, instruction=note["text"],
                    detail=note.get("detail"), status="queued", priority=rank, preset=preset,
                    seed=int(tid[:8], 16), context_sha256=context(story, page)[1], created=now(), runs=0)
        data["tasks"].append(task)
        atomic_json(queue_path(story), data)
        return task


def change_task(story, task_id, *, rank=None, cancel=False):
    with locked(story):
        data = queue_data(story)
        task = next((item for item in data["tasks"] if item["id"] == task_id), None)
        if not task or task["status"] != "queued":
            raise ValueError("只能调整或撤回尚未开始的任务")
        if cancel:
            task["status"] = "cancelled"
        else:
            task["priority"] = priority(rank)
        task["updated"] = now()
        atomic_json(queue_path(story), data)


def worker_path(story):
    return book_dir(story) / ".rework-worker.lock"


@contextmanager
def worker(story):
    path = worker_path(story)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True


def worker_active(story):
    path = worker_path(story)
    if not path.exists():
        return False
    with path.open("r") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def task_order(task):
    status = task["status"]
    phase = 0 if status in ACTIVE else 1 if status == "queued" else 2
    return phase, -task["priority"], task["created"], task["id"]


def inspect_job(ledger, task):
    row = entry(ledger, task["page"])
    job = row.get("job")
    version = next((v for v in reversed(row["versions"]) if v.get("metadata", {}).get("task_id") == task["id"]), None)
    return job, version


def queue_view(story):
    ledger = manifest(story)
    running = worker_active(story)
    tasks = []
    for task in queue_data(story)["tasks"]:
        view = dict(task)
        job, version = inspect_job(ledger, task)
        if version:
            view.update(status="candidate_ready", candidate=version["id"], prompt_id=version["metadata"]["prompt_id"], review=version["review"])
        elif job and job.get("task_id") == task["id"] and task["status"] in ACTIVE:
            view.update(status="running" if running else "paused", prompt_id=job["prompt_id"])
        elif task["status"] == "running" and not running:
            view["status"] = "paused"
        tasks.append(view)
    return {"worker_active": running, "tasks": sorted(tasks, key=task_order)}


def claim(story, server):
    with locked(story):
        data = queue_data(story)
        ledger = manifest(story)
        for task in sorted(data["tasks"], key=task_order):
            if task["status"] not in ACTIVE | {"queued"}:
                continue
            job, version = inspect_job(ledger, task)
            if version:
                task.update(status="candidate_ready", candidate=version["id"], prompt_id=version["metadata"]["prompt_id"])
            elif task["context_sha256"] != context(story, get_page(story, task["page"]))[1]:
                task.update(status="stale", error="分镜或细节规则已变更，请对照当前版新建返工任务。")
            elif job and job.get("task_id") != task["id"]:
                task.update(status="queued", error="该页有另一项生成进行中，等待归档后可再运行。")
            elif job and job["server"] != server:
                task.update(status="paused", prompt_id=job["prompt_id"], error="续跑需要使用最初提交的 ComfyUI 地址。")
                atomic_json(queue_path(story), data)
                return None
            else:
                task.update(status="running", runs=task["runs"] + 1, updated=now())
                task.pop("error", None)
                if job:
                    task["prompt_id"] = job["prompt_id"]
                atomic_json(queue_path(story), data)
                return task, bool(job)
            task["updated"] = now()
        atomic_json(queue_path(story), data)
        return None


def settle(story, claimed, process):
    with locked(story):
        data = queue_data(story)
        task = next(item for item in data["tasks"] if item["id"] == claimed["id"])
        job, version = inspect_job(manifest(story), task)
        summary = "\n".join(x for x in (process.stdout.strip(), process.stderr.strip()) if x)
        task.update(updated=now(), output=summary[-3000:])
        if version:
            task.update(status="candidate_ready", candidate=version["id"], prompt_id=version["metadata"]["prompt_id"])
            task.pop("error", None)
        elif job and job.get("task_id") == task["id"]:
            task.update(status="failed" if "reported execution failure" in summary else "paused", prompt_id=job["prompt_id"],
                        error="任务仍可按原编号续跑。" if "still pending" in summary else summary[-900:])
        else:
            task.update(status="failed", error=summary[-900:] or "没有找到任务的候选稿。")
        atomic_json(queue_path(story), data)
        return task


def run_one(story, server, timeout):
    with worker(story) as acquired:
        if not acquired:
            return {"status": "busy"}
        claimed = claim(story, server)
        if claimed is None:
            return {"status": "idle"}
        task, resume = claimed
        command = [sys.executable, "-B", str(ROOT / "pipeline/comfyui.py"), "--slug", story["slug"], "--page", str(task["page"]),
                   "--preset", task["preset"], "--server", server, "--seed", str(task["seed"]), "--timeout", str(timeout),
                   "--task-id", task["id"]]
        command += ["--resume"] if resume else ["--candidate", "--revision-note", task["instruction"]]
        process = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        return settle(story, task, process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8188")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("action", choices=("status", "run"))
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("Timeout must be positive")
    story = load_story(args.slug, complete=False)
    result = queue_view(story) if args.action == "status" else run_one(story, args.server, args.timeout)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("status") == "failed" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
