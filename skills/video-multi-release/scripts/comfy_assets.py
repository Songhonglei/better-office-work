#!/usr/bin/env python3
"""Inspect local ComfyUI; generate assets with durable, resumable job receipts."""
import argparse
import copy
import json
import mimetypes
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from production_common import (digest, file_hash, local_config, probe, read_json,
                               segments, write_json)

MODEL_EXTS = {'.gguf', '.safetensors', '.ckpt', '.pt', '.pth', '.bin'}


class ComfyClient:
    def __init__(self, url='http://127.0.0.1:8188'):
        self.url = url.rstrip('/')
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
            raise ValueError('ComfyUI URL must be http(s), without embedded credentials')

    def request(self, route, data=None, binary=False, timeout=30):
        req = urllib.request.Request(self.url + route,
            data=None if data is None else json.dumps(data).encode(),
            headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            return raw if binary else json.loads(raw)
        except urllib.error.HTTPError as e:
            raise RuntimeError('ComfyUI HTTP %s: %s' % (e.code, e.read().decode()[:1500])) from e

    def check_graph(self, graph):
        info = self.request('/object_info')
        problems = []
        for ident, node in graph.items():
            name = node['class_type']
            spec = info.get(name)
            if spec is None:
                problems.append('Missing node: ' + name)
                continue
            # This local workflow never opts into billed Partner Nodes.
            if spec.get('api_node') or name.startswith(('API_', 'Api')):
                problems.append('Cloud/API node is not allowed in local generation: ' + name)
            for group in ('required', 'optional'):
                for key, rule in spec.get('input', {}).get(group, {}).items():
                    value = node.get('inputs', {}).get(key)
                    if value is None:
                        continue
                    if isinstance(rule, list) and rule and isinstance(rule[0], list):
                        if not isinstance(value, list) and value not in rule[0]:
                            problems.append('%s.%s unavailable: %r' % (ident, key, value))
        if problems:
            raise ValueError('; '.join(problems))

    def upload_image(self, path):
        path = Path(path)
        name = 'vmr_' + file_hash(path) + path.suffix.lower()
        boundary = 'vmr-' + uuid.uuid4().hex
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        body = (('--' + boundary + '\r\nContent-Disposition: form-data; name="image"; filename="' + name +
                 '"\r\nContent-Type: ' + mime + '\r\n\r\n').encode() + path.read_bytes() +
                ('\r\n--' + boundary + '\r\nContent-Disposition: form-data; name="overwrite"\r\n\r\ntrue' +
                 '\r\n--' + boundary + '--\r\n').encode())
        req = urllib.request.Request(self.url + '/upload/image', data=body,
                                      headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read())
        if result.get('name') != name or result.get('subfolder'):
            raise ValueError('ComfyUI changed uploaded image name; workflow reference would be ambiguous')
        return name


def api_graph(path):
    data = read_json(path)
    if not isinstance(data, dict):
        raise ValueError('Workflow file missing or not JSON: ' + str(path))
    if 'nodes' in data:
        raise ValueError('UI workflow JSON is not an API prompt; export API format: ' + str(path))
    graph = data.get('prompt', data)
    if not graph or any(not isinstance(n, dict) or 'class_type' not in n or
                        'inputs' not in n for n in graph.values()):
        raise ValueError('Invalid API workflow: ' + str(path))
    return graph


def inspect(root, workflow_dirs, url):
    root = Path(root).expanduser().resolve()
    models = []
    for p in sorted((root / 'models').rglob('*')):
        if p.is_file() and p.suffix.lower() in MODEL_EXTS:
            models.append({'name': str(p.relative_to(root / 'models')),
                           'bytes': p.stat().st_size, 'path': str(p.resolve())})
    workflows, visited = [], set()
    for folder in [root / 'user', *map(Path, workflow_dirs)]:
        for p in sorted(folder.expanduser().rglob('*.json')):
            if p in visited:
                continue
            visited.add(p)
            try:
                d = read_json(p)
                if not isinstance(d, dict):
                    continue
                if 'nodes' in d:
                    types = sorted({n.get('type', '') for n in d['nodes']})
                    kind = 'ui'
                else:
                    graph = api_graph(p)
                    types = sorted({n['class_type'] for n in graph.values()})
                    kind = 'api'
                workflows.append({'path': str(p.resolve()), 'format': kind, 'nodes': types})
            except (ValueError, TypeError, KeyError):
                continue
    try:
        client = ComfyClient(url)
        stats = client.request('/system_stats', timeout=3)
        node_info = client.request('/object_info')
        for w in workflows:
            w['missing_nodes'] = sorted(set(w['nodes']) - node_info.keys())
        runtime = {'online': True, 'stats': stats, 'node_count': len(node_info)}
    except (OSError, ValueError, RuntimeError) as e:
        runtime = {'online': False, 'error': str(e)}
    return {'comfy_root': str(root), 'url': url, 'models': models,
            'workflows': workflows, 'runtime': runtime,
            'note': 'Files and node availability do not establish model quality or hardware fit.'}


def patch_graph(profile, recipe, project):
    workflow = Path(profile['workflow']).expanduser()
    if not workflow.is_absolute():
        workflow = project / workflow
    graph = copy.deepcopy(api_graph(workflow))
    bindings = dict(profile.get('bindings', {}), **recipe.get('bindings', {}))
    values = dict(profile.get('values', {}), **recipe.get('values', {}))
    for name, image in recipe.get('upload_images', {}).items():
        path = Path(image).expanduser()
        if not path.is_absolute():
            path = project / path
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError('upload_images requires a supported image file')
        values[name] = 'vmr_' + file_hash(path) + path.suffix.lower()
    for name in bindings:
        if name in recipe:
            values[name] = recipe[name]
    if 'seed' in bindings and 'seed' not in values:
        values['seed'] = int(digest(recipe)[:12], 16)
    for name, value in values.items():
        if name not in bindings:
            raise ValueError('No explicit workflow binding for ' + name)
        binding = bindings[name]
        if not isinstance(binding, list) or len(binding) != 2:
            raise ValueError('Binding must be [node_id, input_name]: ' + name)
        node, field = map(str, binding)
        if node not in graph or field not in graph[node]['inputs']:
            raise ValueError('Unknown workflow input: %s.%s' % (node, field))
        graph[node]['inputs'][field] = value
    output_node = str(recipe.get('output_node', profile.get('output_node', '')))
    if output_node not in graph:
        raise ValueError('An existing output_node is required')
    # Model identity is part of the receipt/cache key (names + sizes + mtimes).
    return graph, output_node, str(workflow.resolve())


def output_files(history, output_node, kind):
    output = history.get('outputs', {}).get(output_node, {})
    allowed = {'.png', '.jpg', '.jpeg', '.webp'} if kind == 'image' else {'.mp4', '.mov', '.webm', '.mkv'}
    rows = []
    for field in ('images', 'videos', 'gifs'):
        for item in output.get(field, []):
            if Path(item.get('filename', '')).suffix.lower() in allowed:
                rows.append(item)
    if len(rows) != 1:
        raise ValueError('Expected exactly one %s output at node %s, found %d' %
                         (kind, output_node, len(rows)))
    return rows[0]


def generate(project, config, timeout=1800, poll=2, resubmit=False):
    project = Path(project).resolve()
    data = read_json(project / 'voice_script.json')
    cfg = read_json(config, {})
    client = ComfyClient(cfg.get('url', 'http://127.0.0.1:8188'))
    manifest_path = project / 'asset_manifest.json'
    manifest = read_json(manifest_path, {'version': 1, 'assets': {}})
    cache = project / '.cache/comfy'
    cache.mkdir(parents=True, exist_ok=True)
    active_ids = {s['id'] for s in segments(data)}
    manifest['assets'] = {k: v for k, v in manifest['assets'].items() if k in active_ids}
    for seg in data['segments']:
        visual = seg.get('visual', {})
        recipe = visual.get('generate')
        if not recipe:
            # Remove an old generated asset if the segment now uses explicit input.
            manifest['assets'].pop(seg['id'], None)
            continue
        profile = cfg.get('profiles', {}).get(recipe.get('profile'), {})
        profile = dict(profile, **{k: v for k, v in recipe.items()
                                  if k in ('workflow', 'bindings', 'values', 'output_node', 'output_kind')})
        if 'workflow' not in profile:
            raise ValueError('Missing ComfyUI profile/workflow: ' + seg['id'])
        graph, output_node, workflow = patch_graph(profile, recipe, project)
        kind = recipe.get('output_kind', profile.get('output_kind', 'image'))
        if kind not in ('image', 'video'):
            raise ValueError('output_kind must be image or video')
        if visual.get('type') == 'video' and kind != 'video':
            raise ValueError('A video scene requires video output; no silent still-image downgrade')
        dependency_stats = []
        model_root = Path(cfg.get('comfy_root', '')) / 'models'
        for node in graph.values():
            for key, val in node['inputs'].items():
                if isinstance(val, str) and Path(val).suffix in MODEL_EXTS:
                    matches = list(model_root.rglob(Path(val).name)) if model_root.is_dir() else []
                    dependency_stats += [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in matches]
        key = digest({'graph': graph, 'url': client.url, 'node': output_node,
                      'kind': kind, 'models': dependency_stats})
        receipt_path = cache / (key + '.json')
        job = read_json(receipt_path, {})
        if job.get('status') == 'completed':
            path = Path(job['path'])
            if path.exists() and file_hash(path) == job['sha256']:
                manifest['assets'][seg['id']] = job
                write_json(manifest_path, manifest)
                print('CACHE ' + seg['id'], flush=True)
                continue
            # Recover/download the existing server job instead of regenerating.
            job['status'] = 'submitted'
        if job and job.get('status') in ('failed', 'submission_unknown') and resubmit:
            write_json(cache / (key + '.previous-' + str(time.time_ns()) + '.json'), job)
            job = {}
        if not job:
            for image in recipe.get('upload_images', {}).values():
                path = Path(image).expanduser()
                client.upload_image(path if path.is_absolute() else project / path)
            client.check_graph(graph)
            # Persist before POST. Never automatically repeat a potentially accepted request.
            job = {'status': 'submission_unknown', 'prompt_id': str(uuid.uuid4()),
                   'cache_key': key, 'url': client.url, 'workflow': workflow,
                   'workflow_sha256': file_hash(workflow), 'output_node': output_node,
                   'kind': kind, 'parameters': recipe, 'submitted_at': time.time()}
            write_json(receipt_path, job)
            try:
                response = client.request('/prompt', {'prompt': graph,
                    'prompt_id': job['prompt_id'], 'client_id': job['prompt_id'],
                    'extra_data': {'video_multi_release': key}})
            except Exception:
                raise RuntimeError('Submission result unknown; receipt retained at %s. '
                                   'Check ComfyUI history/queue before --resubmit.' % receipt_path)
            if not response.get('prompt_id'):
                raise RuntimeError('No prompt_id returned; do not resubmit blindly')
            job.update(status='submitted', prompt_id=response['prompt_id'])
            write_json(receipt_path, job)
        if job.get('status') == 'failed':
            raise RuntimeError('Previous ComfyUI job failed; fix workflow then explicitly --resubmit: ' + str(receipt_path))
        print('WAIT %s prompt_id=%s' % (seg['id'], job['prompt_id']), flush=True)
        deadline = time.monotonic() + timeout
        while True:
            history = client.request('/history/' + job['prompt_id']).get(job['prompt_id'])
            if history:
                status = history.get('status', {})
                if status.get('status_str') == 'error':
                    job.update(status='failed', error=status.get('messages'))
                    write_json(receipt_path, job)
                    raise RuntimeError('ComfyUI execution failed; see ' + str(receipt_path))
                if status.get('completed') or (not status and history.get('outputs')):
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError('ComfyUI still pending or submission unconfirmed; rerun to resume: ' + job['prompt_id'])
            time.sleep(poll)
        item = output_files(history, output_node, kind)
        raw = client.request('/view?' + urllib.parse.urlencode({
            'filename': item['filename'], 'subfolder': item.get('subfolder', ''),
            'type': item.get('type', 'output')}), binary=True)
        dest = project / 'assets/generated' / (key + Path(item['filename']).suffix.lower())
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_suffix(dest.suffix + '.part')
        temp.write_bytes(raw)
        media = probe(temp)
        if not any(s.get('codec_type') == 'video' for s in media['streams']):
            raise ValueError('ComfyUI result is not decodable visual media')
        temp.replace(dest)
        job.update(status='completed', path=str(dest), sha256=file_hash(dest),
                   completed_at=time.time(), elapsed_seconds=time.time()-job['submitted_at'],
                   cost_usd=0.0, cost_basis='local compute; hardware/electricity not priced')
        write_json(receipt_path, job)
        manifest['assets'][seg['id']] = job
        write_json(manifest_path, manifest)
        print('DONE %s %s' % (seg['id'], dest), flush=True)
    write_json(manifest_path, manifest)
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('inspect')
    scan.add_argument('--root', required=True)
    scan.add_argument('--workflows', action='append', default=[])
    scan.add_argument('--url', default='http://127.0.0.1:8188')
    scan.add_argument('--out', required=True)
    gen = sub.add_parser('generate')
    gen.add_argument('--project', default='.')
    gen.add_argument('--config', default=str(local_config()))
    gen.add_argument('--timeout', type=float, default=1800)
    gen.add_argument('--resubmit', action='store_true', help='Explicitly retry a failed/unknown job after checking server history')
    a = ap.parse_args()
    if a.command == 'inspect':
        report = inspect(a.root, a.workflows, a.url)
        write_json(a.out, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        from production_common import project_lock
        with project_lock(a.project):
            generate(a.project, a.config, a.timeout, resubmit=a.resubmit)


if __name__ == '__main__':
    main()
