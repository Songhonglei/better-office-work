"""Behavioral regression tests; fake Comfy HTTP + real FFmpeg media failures."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from comfy_assets import ComfyClient, api_graph, generate
from production_common import digest, file_hash, probe, read_json, run, segments, write_json
from quality_check import check, covered
from release_receipt import validate
from render_mixed import render
from subtitle_track import burn, cues_for
import tts

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class ValidationTests(unittest.TestCase):
    def test_duplicate_and_path_ids_fail_before_generation(self):
        for ids in [('x', 'x'), ('../bad', 'x')]:
            with self.assertRaises(ValueError):
                segments({'segments': [{'id': i, 'text': 'hello'} for i in ids]})

    def test_overlapping_cues_do_not_inflate_coverage(self):
        self.assertEqual(covered((0, 10), [(0, 3), (1, 4)]), 4)

    def test_subtitles_cover_narration_and_preserve_text(self):
        tl = {'clips': [{'id': 's1', 'start': .6, 'audio_dur': 9,
                         'text': '这是一段长一点的中文旁白，用来检查字幕是否完整，以及结尾有没有漏字。'}]}
        cues = cues_for(tl)
        self.assertEqual(''.join(c['text'] for c in cues), tl['clips'][0]['text'])
        self.assertAlmostEqual(cues[-1]['end'], 9.6)


class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.posts, self.ready = 0, True
        self.uploads = []
        outer = self
        # A real decodable PNG fixture.
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=64x64',
             '-frames:v', '1', self.project / 'image.png'])
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                if self.path == '/object_info':
                    self.send({'SaveImage': {'input': {}}})
                elif self.path.startswith('/history/'):
                    ident = self.path.split('/')[-1]
                    self.send({ident: {'status': {'completed': True}, 'outputs': {
                        '1': {'images': [{'filename': 'out.png', 'type': 'output'}]}}}} if outer.ready else {})
                elif self.path.startswith('/view?'):
                    self.send_response(200); self.end_headers()
                    self.wfile.write((outer.project / 'image.png').read_bytes())
                else:
                    self.send({})
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                if self.path == '/upload/image':
                    import re
                    name = re.search(rb'filename="([^"]+)"', raw)[1].decode()
                    outer.uploads.append(raw)
                    self.send({'name': name, 'subfolder': ''})
                    return
                payload = json.loads(raw)
                outer.posts += 1
                self.send({'prompt_id': payload['prompt_id']})
            def send(self, data):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:%d' % self.server.server_port
        write_json(self.project / 'workflow.json', {'1': {'class_type': 'SaveImage', 'inputs': {}}})
        write_json(self.project / 'config.json', {'url': self.url})
        write_json(self.project / 'voice_script.json', {'segments': [{'id': 's1', 'text': '测试',
            'visual': {'type': 'image', 'generate': {'workflow': 'workflow.json', 'output_node': '1'}}}]})

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def generate(self, **kw):
        return generate(self.project, self.project / 'config.json', **kw)

    def test_generation_cache_and_corrupt_file_redownload_without_resubmit(self):
        first = self.generate()
        self.generate()
        self.assertEqual(self.posts, 1)
        Path(first['assets']['s1']['path']).write_bytes(b'corrupt')
        self.generate()
        self.assertEqual(self.posts, 1)

    def test_timeout_resumes_same_prompt(self):
        self.ready = False
        with self.assertRaises(TimeoutError):
            self.generate(timeout=0)
        self.ready = True
        self.generate()
        self.assertEqual(self.posts, 1)

    def test_video_request_cannot_silently_use_an_image(self):
        d = read_json(self.project / 'voice_script.json')
        d['segments'][0]['visual']['type'] = 'video'
        write_json(self.project / 'voice_script.json', d)
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(self.posts, 0)

    def test_ui_json_is_not_submitted(self):
        write_json(self.project / 'workflow.json', {'nodes': []})
        with self.assertRaises(ValueError):
            self.generate()
        self.assertEqual(self.posts, 0)

    def test_cloud_nodes_rejected(self):
        with patch.object(ComfyClient, 'request', return_value={'Paid': {'api_node': True, 'input': {}}}):
            with self.assertRaises(ValueError):
                ComfyClient().check_graph({'1': {'class_type': 'Paid', 'inputs': {}}})

    def test_reference_upload_is_content_addressed_and_cached(self):
        write_json(self.project / 'workflow.json', {'1': {'class_type': 'SaveImage', 'inputs': {'image': ''}}})
        d = read_json(self.project / 'voice_script.json')
        d['segments'][0]['visual']['generate'].update(
            bindings={'reference': ['1', 'image']}, upload_images={'reference': 'image.png'})
        write_json(self.project / 'voice_script.json', d)
        self.generate(); self.generate()
        self.assertEqual(len(self.uploads), 1)
        self.assertIn((self.project / 'image.png').read_bytes(), self.uploads[0])
        self.assertEqual(self.posts, 1)


class TTSCacheTests(unittest.TestCase):
    def test_unchanged_segment_is_not_billed_again(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            script = p / 'voice_script.json'
            data = {'segments': [{'id': 's1', 'text': '第一段'}, {'id': 's2', 'text': '第二段'}]}
            write_json(script, data)
            calls = []
            def synth(*args):
                calls.append(args[1]); return 'https://example.test/audio'
            def download(url, target):
                Path(target).write_bytes(b'audio')
            argv = ['tts.py', '--script', str(script), '--out-dir', str(p / 'voice')]
            with patch.object(sys, 'argv', argv), patch.object(tts, 'synth', side_effect=synth), \
                 patch.object(tts, 'find_key', return_value='test-only'), \
                 patch.object(tts.urllib.request, 'urlretrieve', side_effect=download), \
                 patch.object(tts, 'probe_duration', return_value=2):
                tts.main(); tts.main()
                self.assertEqual(len(calls), 2)
                data['segments'][1]['text'] = '改过的第二段'
                write_json(script, data)
                tts.main()
                self.assertEqual(calls, ['第一段', '第二段', '改过的第二段'])


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg needed')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / 'voice').mkdir(); (cls.root / 'assets').mkdir()
        for ident, freq in [('s1', 440), ('s2', 660)]:
            run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=%d:duration=1.2' % freq,
                 '-c:a', 'libmp3lame', cls.root / 'voice' / (ident + '.mp3')])
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=180x320',
             '-frames:v', '1', cls.root / 'assets/card_01.png'])
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=180x320:r=24:d=0.6',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', cls.root / 'assets/motion.mp4'])
        cls.data = {'segments': [{'id': 's1', 'text': '第一段字幕。'}, {'id': 's2', 'text': '第二段字幕。',
                     'visual': {'type': 'video', 'source': 'assets/motion.mp4', 'short': 'loop'}}]}
        write_json(cls.root / 'voice_script.json', cls.data)
        render(cls.root, width=180, height=320, fps=24, pre=.2, gap=.2, tail=.3)
        run([sys.executable, SCRIPTS / 'mix_audio.py', '--timeline', cls.root / 'timeline.json',
             '--silent', cls.root / 'out/silent.mp4', '--out', cls.root / 'out/final.mp4'])
        burn(cls.root / 'out/final.mp4', cls.root / 'timeline.json')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.p = Path(self.work.name) / 'project'
        shutil.copytree(self.root, self.p)
        # Receipts and timelines intentionally use absolute file references.
        tl = read_json(self.p / 'timeline.json')
        for c in tl['clips']:
            c['audio_file'] = str(self.p / 'voice' / (c['id'] + '.mp3'))
        write_json(self.p / 'timeline.json', tl)
        receipt_path = self.p / 'out/subtitles/render_receipt.json'
        receipt = read_json(receipt_path)
        receipt['timeline_sha256'] = file_hash(self.p / 'timeline.json')
        write_json(receipt_path, receipt)

    def tearDown(self):
        self.work.cleanup()

    def qa(self, **kw):
        return check(self.p / 'out/final.mp4', self.p / 'timeline.json', self.p / 'out/quality_report.json', **kw)

    def test_mixed_render_passes_all_gates(self):
        report = self.qa()
        self.assertTrue(report['passed'], report['blockers'])
        validate(self.p / 'out/final.mp4')

    def test_target_duration_failure(self):
        self.assertIn('target_duration_mismatch', self.qa(target=99)['blockers'])

    def test_black_video_detected(self):
        duration = probe(self.p / 'out/final.mp4')['duration']
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=black:s=180x320:r=24',
             '-f', 'lavfi', '-i', 'sine=duration=10', '-t', duration, '-c:v', 'libx264',
             '-c:a', 'aac', self.p / 'out/final.mp4'])
        self.assertIn('black_frames', self.qa()['blockers'])

    def test_silent_narration_caught_even_with_final_audio(self):
        run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=44100:cl=mono',
             '-t', '1.253878', self.p / 'voice/s1.mp3'])
        self.assertIn('silent_or_changed_narration_source:s1', self.qa()['blockers'])

    def test_missing_burn_detected_even_if_receipt_video_hash_is_updated(self):
        receipt_path = self.p / 'out/subtitles/render_receipt.json'
        receipt = read_json(receipt_path)
        shutil.copy2(receipt['clean_video'], self.p / 'out/final.mp4')
        receipt['video_sha256'] = file_hash(self.p / 'out/final.mp4')
        write_json(receipt_path, receipt)
        self.assertTrue(any('subtitle_not_visibly_rendered' in s for s in self.qa()['blockers']))

    def test_subtitle_gap_and_wrong_text_detected(self):
        receipt_path = self.p / 'out/subtitles/render_receipt.json'
        receipt = read_json(receipt_path)
        receipt['cues'][0]['end'] -= .5
        receipt['cues'][0]['text'] = '错误文案'
        write_json(receipt_path, receipt)
        self.assertIn('subtitle_coverage:s1', self.qa()['blockers'])

    def test_release_rejects_changed_video(self):
        self.qa()
        with (self.p / 'out/final.mp4').open('ab') as f:
            f.write(b'changed')
        with self.assertRaises(ValueError):
            validate(self.p / 'out/final.mp4')

    def test_release_rejects_changed_script(self):
        self.qa()
        d = read_json(self.p / 'voice_script.json')
        d['segments'][0]['text'] = '新版本文案'
        write_json(self.p / 'voice_script.json', d)
        with self.assertRaises(ValueError):
            validate(self.p / 'out/final.mp4')
        self.assertIn('script_timeline_mismatch', self.qa()['blockers'])

    def test_release_blocks_failed_production_with_old_valid_output(self):
        self.qa()
        write_json(self.p / 'production.json', {'stages': {'render': {'status': 'failed'}}})
        with self.assertRaises(ValueError):
            validate(self.p / 'out/final.mp4')

    def test_release_shell_blocks_before_opening_browser(self):
        self.qa()
        write_json(self.p / 'production.json', {'stages': {'render': {'status': 'failed'}}})
        env = dict(os.environ, VIDEO=str(self.p / 'out/final.mp4'), TITLE='test', MODE='stage',
                   PLATFORMS='xhs,channels,douyin')
        p = subprocess.run(['bash', str(SCRIPTS / 'release.sh')], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 10, p.stdout + p.stderr)
        self.assertIn('E_QUALITY_GATE', p.stdout)

    def test_release_shell_keeps_standalone_video_compatibility(self):
        (self.p / 'out/quality_report.json').unlink(missing_ok=True)
        env = dict(os.environ, VIDEO=str(self.p / 'out/final.mp4'), TITLE='', MODE='stage')
        p = subprocess.run(['bash', str(SCRIPTS / 'release.sh')], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 10, p.stdout + p.stderr)
        self.assertIn('E_PARAM_TITLE', p.stdout)
        self.assertNotIn('E_QUALITY_GATE', p.stdout)

    def test_freeze_extends_short_video_and_error_policy_refuses(self):
        d = read_json(self.p / 'voice_script.json')
        d['segments'][1]['visual']['short'] = 'freeze'
        write_json(self.p / 'voice_script.json', d)
        timeline = render(self.p, width=180, height=320, fps=24)
        self.assertAlmostEqual(probe(self.p / 'out/silent.mp4')['duration'], timeline['total'], delta=.12)
        d['segments'][1]['visual']['short'] = 'error'
        write_json(self.p / 'voice_script.json', d)
        with self.assertRaises(ValueError):
            render(self.p, width=180, height=320, fps=24)

    def test_single_row_contact_sheet_runs(self):
        run([sys.executable, SCRIPTS / 'verify_sync.py', '--timeline', self.p / 'timeline.json',
             '--video', self.p / 'out/final.mp4', '--out-dir', self.p / 'sync-test', '--cols', '1'])
        self.assertTrue((self.p / 'sync-test/contact_sheet.png').is_file())


if __name__ == '__main__':
    unittest.main()
