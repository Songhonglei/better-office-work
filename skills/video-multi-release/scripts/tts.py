#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分段配音生成 —— 阿里云百炼 Qwen-Audio-TTS。

走 MaaS Token Plan 端点（跟 token-plan 的 key 同域），不需要单独开百炼账号。
模型只有 qwen-audio-3.0-tts-plus 可用，3.1 系列在该端点返回 404。

用法:
  python3 tts.py --script voice_script.json --preset female --out-dir voice

注：输出目录用 voice/（rebuild.sh 硬要求这个名字），不要写成 audio/female。

关键经验（血泪）:
  rate < 1.0 再叠加 instruction 里写"语速偏慢"，时长会膨胀 25% 以上。
  30 字的句子能从 7.7 秒拖到 10.3 秒。默认 rate 1.12 + 让指令只说语气不说快慢。
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from production_common import digest, file_hash, read_json, segments, write_json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ENDPOINT = ('https://token-plan.cn-beijing.maas.aliyuncs.com'
            '/api/v1/services/audio/tts/SpeechSynthesizer')
MODEL = 'qwen-audio-3.0-tts-plus'

# 音色预设。voice 参数必须属于 3.0-tts-plus 支持的基础音色，
# 跨模型混用会报 [cosyvoice:]Engine error [411]。
PRESETS = {
    'female': {
        'voice': 'qwen-audio-3.0-tts-plus-longdieshuangluan',
        'label': '龙蝶霜鸾 40岁 电台质感音',
        'instruction': ('用成熟女性的声音朗读，像经历过很多事的人在夜里回想往事。'
                        '语气克制、有书卷气，句尾自然下沉。'
                        '不要甜美，不要播音腔，不要刻意煽情。'),
    },
    'female-warm': {
        'voice': 'qwen-audio-3.0-tts-plus-longxinzhenghe',
        'label': '龙昕筝荷 42岁 温柔坚韧音',
        'instruction': ('用成熟女性的声音朗读，温和而坚定，像在说自己走过的路。'
                        '不要播音腔，不要刻意煽情。'),
    },
    'male': {
        'voice': 'qwen-audio-3.0-tts-plus-longlanglianyue',
        'label': '龙朗涟玥 55岁 浑厚沉稳音',
        'instruction': ('用成熟男性的声音朗读，低沉稳重，像有阅历的人在平静讲述自己的事。'
                        '语速自然，句尾落下。不要激昂，不要播音腔，不要煽情。'),
    },
    'male-narrative': {
        'voice': 'qwen-audio-3.0-tts-plus-longhesongrui',
        'label': '龙荷松蕊 44岁 叙事沉浸音',
        'instruction': ('用成熟男性的声音朗读，像在讲故事。语速自然，句尾落下。'
                        '不要电台腔，不要刻意煽情。'),
    },
}


def find_key():
    """按优先级取 API Key：环境变量 > 数据目录 .env（兼容旧位置 skill 根目录）。

    不内置任何密钥。密钥属运行时数据，放 skill 目录之外：
    $WB_SKILLS_DATA/video-multi-release/.env（默认 ~/space/skills-data），
    这样 skill 升级/镜像全量覆盖不会清掉密钥，多个 agent 也共用一份。
    首次使用请跑 onboard.sh 写入。
    """
    env = os.environ.get('DASHSCOPE_API_KEY', '').strip()
    if env:
        return env

    data_root = os.environ.get('WB_SKILLS_DATA') or os.path.join(
        os.path.expanduser('~'), 'space', 'skills-data')
    env_file = os.path.join(data_root, 'video-multi-release', '.env')
    if not os.path.exists(env_file):
        # 兼容旧位置（数据外置之前密钥写在 skill 根目录）
        legacy = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
        if os.path.exists(legacy):
            env_file = legacy
    if os.path.exists(env_file):
        try:
            with open(env_file, encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DASHSCOPE_API_KEY'):
                        _, _, val = line.partition('=')
                        val = val.strip().strip('"').strip("'")
                        if val:
                            return val
        except OSError as e:
            sys.stderr.write('读取 .env 失败: %s\n' % e)

    sys.exit(
        '缺少 DASHSCOPE_API_KEY。\n'
        '  方式一（推荐）: bash scripts/onboard.sh\n'
        '  方式二: export DASHSCOPE_API_KEY=sk-xxxx\n'
        '  方式三: 在 %s 建 .env，内容为 DASHSCOPE_API_KEY=sk-xxxx\n'
        '  Key 在阿里云百炼控制台 → API-KEY 管理创建。' % env_file
    )


def synth(key, text, voice, instruction, rate, retries=3):
    body = json.dumps({
        'model': MODEL,
        'input': {
            'text': text,
            'voice': voice,
            'format': 'mp3',
            'sample_rate': 48000,
            'rate': rate,
            'instruction': instruction,
        },
    }, ensure_ascii=False).encode('utf-8')

    last = None
    for attempt in range(retries):
        req = urllib.request.Request(ENDPOINT, data=body, headers={
            'Authorization': 'Bearer ' + key,
            'Content-Type': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.loads(r.read())
            return data['output']['audio']['url']
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'ignore')[:200]
            last = '%s %s' % (e.code, detail)
            if e.code in (400, 401, 404):
                break          # 参数或鉴权错，重试无意义
        except Exception as e:
            last = str(e)
        time.sleep(2 * (attempt + 1))
    sys.exit('TTS 失败: ' + str(last))


def probe_duration(path):
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'csv=p=0', path,
        ]).decode().strip()
    except FileNotFoundError:
        sys.exit('找不到 ffprobe，请先安装 ffmpeg')
    except subprocess.CalledProcessError as e:
        sys.exit('ffprobe 读取失败: %s' % path)
    return float(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--script', required=True, help='文案 JSON（含 segments 数组）')
    ap.add_argument('--preset', default='female', choices=sorted(PRESETS))
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--rate', type=float, default=1.12,
                    help='语速，默认 1.12。低于 1.0 会显著拉长总时长')
    ap.add_argument('--voice', help='直接指定 voice 参数，覆盖 preset')
    ap.add_argument('--allow-slow', action='store_true',
                    help='允许单段超过 8 秒不报错')
    ap.add_argument('--target', type=float, default=None,
                    help='目标成片时长（秒），用于 TTS 之前打印预估')
    ap.add_argument('--force', action='store_true', help='重新合成所有段落，忽略内容缓存')
    ap.add_argument('--segment-id', help='只处理指定段落；其余段落文件不变')
    a = ap.parse_args()

    try:
        with open(a.script, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        sys.exit('文案文件不存在: %s' % a.script)
    except json.JSONDecodeError as e:
        sys.exit('文案 JSON 解析失败: %s' % e)
    segs = segments(data)
    if a.segment_id:
        segs = [s for s in segs if s['id'] == a.segment_id]
        if not segs:
            sys.exit('未知 segment-id')

    # TTS 之前先估一次，避免配完音才发现超时（只能砍字，调 rate 救不了）
    try:
        from estimate import estimate_script, print_report
        print('── 时长预估（TTS 之前）──')
        print_report(estimate_script(a.script, target=a.target))
        print('')
    except Exception as e:
        print('（时长预估失败: %s）\n' % e)
        # 预估失败时 --target 会完全失效，不能一声不吭继续配音
        if a.target:
            sys.exit('传了 --target 但时长预估失败，无法判断是否达标；'
                     '先修正文案数据或修复 estimate.py')

    preset = PRESETS[a.preset]
    voice = a.voice or preset['voice']
    instruction = preset['instruction']
    key = None  # Fully cached runs do not require or read a credential.

    os.makedirs(a.out_dir, exist_ok=True)
    cache_path = os.path.join(a.out_dir, '.tts-cache.json')
    cache = read_json(cache_path, {})
    print('音色: %s' % preset['label'])
    print('模型: %s  rate=%.2f' % (MODEL, a.rate))

    total = 0.0
    rows = []
    for seg in segs:
        out = os.path.join(a.out_dir, seg['id'] + '.mp3')
        fingerprint = digest({'endpoint': ENDPOINT, 'model': MODEL, 'text': seg['text'],
                              'voice': voice, 'instruction': instruction, 'rate': a.rate,
                              'format': 'mp3', 'sample_rate': 48000})
        previous = cache.get(seg['id'], {})
        cached = (not a.force and previous.get('key') == fingerprint and os.path.isfile(out)
                  and previous.get('sha256') == file_hash(out))
        if cached:
            print('  CACHE ' + seg['id'])
        else:
            key = key or find_key()
            url = synth(key, seg['text'], voice, instruction, a.rate)
            temp = out + '.part.mp3'
            urllib.request.urlretrieve(url, temp)
            probe_duration(temp)
            os.replace(temp, out)
            cache[seg['id']] = {'key': fingerprint, 'sha256': file_hash(out)}
            write_json(cache_path, cache)

        dur = probe_duration(out)
        total += dur
        chars = len(seg['text'].replace('，', '').replace('。', ''))
        cps = chars / dur if dur else 0
        flag = ''
        if dur > 10:
            flag = '  ⚠ >10s 卡片停留偏久，建议拆段'
        elif dur < 5:
            flag = '  ⚠ <5s 切换偏急，建议与相邻段合并'
        elif dur > 8 and not a.allow_slow:
            flag = '  ⚠ 超过 8 秒，建议精简或提高 rate'
        rows.append((seg['id'], chars, dur, cps, flag))
        print('  %-6s %2d字 %5.2fs %4.1f字/秒%s' % (seg['id'], chars, dur, cps, flag))

    print('纯语音合计 %.2fs（%d 段）' % (total, len(segs)))
    slow = [r for r in rows if r[4]]
    if slow:
        print('有 %d 段节奏不均（>10s 或 <5s），建议拆段 / 合并；'
              '想整体缩短只能砍文案，不要靠压 rate。' % len(slow))
    print('音频已写入 %s' % os.path.abspath(a.out_dir))


if __name__ == '__main__':
    main()
