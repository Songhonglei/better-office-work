#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量生成口播视频卡片 —— 薄封装（引用外部生成器）。

自身不做任何渲染。读取 voice_script.json 的 segments，逐段调用
xhs-image-note-release skill 的 card_generator.py（Chrome headless CSS 渲染，
Songti SC 衬线字体栈），按数组顺序输出 card_01.png ~ card_NN.png，
命名与 build_composition.py 的读取约定严格对齐。

背景图与段落的对应关系，按优先级：
  1. segments[i].image      —— 段内显式写背景图路径（最稳，推荐）
  2. --mapping map.json     —— {"s1": "images/xxx.png", ...}
  3. --images <dir>         —— 目录内图片按文件修改时间排序对齐（打印映射表供核对）

用法:
  python3 gen_cards.py --script voice_script.json --mapping map.json --out-dir assets
  python3 gen_cards.py --script voice_script.json --images images/ --dry-run

段数与背景图数不一致时直接报错退出（防止视频卡片静默错位）。
生成完成后提示跑 build_composition.py 重建时间轴。

依赖:
  - xhs-image-note-release skill（card_generator.py）
  - Google Chrome（card_generator.py 用 headless 渲染）
"""

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from find_safe_area import analyze_image  # noqa: E402  自动留白检测（同目录）

DEFAULT_GENERATOR = os.path.expanduser(
    '~/.workbuddy/skills/xhs-image-note-release/references/card-generator/card_generator.py')

IMG_EXTS = ('.png', '.jpg', '.jpeg', '.webp')

# text_pos 枚举：段内写 "top-left" 之类即可精确定位，避开画面主体头部
TEXT_POS = {
    'top':         {'y': 0.28, 'x': 0.5,  'anchor': 'middle'},
    'center':      {'y': 0.5,  'x': 0.5,  'anchor': 'middle'},
    'bottom':      {'y': 0.72, 'x': 0.5,  'anchor': 'middle'},
    'left':        {'y': 0.5,  'x': 0.08, 'anchor': 'start'},
    'right':       {'y': 0.5,  'x': 0.92, 'anchor': 'end'},
    'top-left':    {'y': 0.28, 'x': 0.08, 'anchor': 'start'},
    'top-right':   {'y': 0.28, 'x': 0.92, 'anchor': 'end'},
    'bottom-left': {'y': 0.72, 'x': 0.08, 'anchor': 'start'},
    'bottom-right':{'y': 0.72, 'x': 0.92, 'anchor': 'end'},
}


def load_config():
    """读取运行时数据目录的默认值（不在 skill 目录里，升级不会被覆盖）。"""
    root = os.environ.get('WB_SKILLS_DATA') or os.path.join(
        os.path.expanduser('~'), 'space', 'skills-data')
    p = os.path.join(root, 'video-multi-release', 'config.json')
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def parse_text_pos(value):
    """段内 text_pos：枚举字符串，或 {"y":0.3,"x":0.1,"anchor":"start"}。"""
    if isinstance(value, str):
        key = value.strip().lower()
        if key not in TEXT_POS:
            sys.exit('text_pos 未知枚举: %s（可选: %s）'
                     % (value, ', '.join(sorted(TEXT_POS))))
        return dict(TEXT_POS[key])
    if isinstance(value, dict):
        y = float(value.get('y', 0.5))
        x = float(value.get('x', 0.5))
        anchor = value.get('anchor', 'middle')
        if anchor not in ('start', 'middle', 'end'):
            sys.exit('text_pos.anchor 只能是 start/middle/end')
        return {'y': max(0.0, min(1.0, y)),
                'x': max(0.0, min(1.0, x)), 'anchor': anchor}
    sys.exit('text_pos 只能是枚举字符串或坐标对象')


def split_quote(text):
    """把金句自动拆成上下两行：按第一个逗号切；无逗号则整句一行。

    想完全自定义分行，在 segment 里写 "lines": ["上句", "下句"]。
    """
    for sep in ('，', ','):
        idx = text.find(sep)
        if idx > 0:
            return [text[:idx], text[idx + 1:]]
    return [text]


def resolve_text_pos(seg, img_path, a, cfg, auto_on, warnings=None):
    """文字位置三级优先：段内 text_pos > 自动留白检测 > 全局 ratio > 居中。

    自动检测默认开启；--no-auto-safe-area 关闭后，全局 --text-y-ratio 才生效。
    """
    if seg.get('text_pos') is not None:
        return parse_text_pos(seg['text_pos']), 'segment'
    if auto_on:
        try:
            r = analyze_image(img_path, a.safe_axis)
            src = 'auto:' + r['band']
            conf = r.get('confidence', '?')
            if conf == 'low':
                # 最优与次优几乎同分 = 算法没有可靠信号，必须人工复核并固化 text_pos
                src += '[low]'
                if warnings is not None:
                    warnings.append((seg.get('id', '?'), r['band'], r['gap']))
            elif conf == 'medium':
                src += '[medium]'
            return ({'y': r['y_ratio'], 'x': r['x_ratio'], 'anchor': r['anchor']}, src)
        except (OSError, RuntimeError) as e:
            print('  ⚠ 留白检测失败(%s)，回退全局位置' % e)
    yr = a.text_y_ratio if a.text_y_ratio is not None else cfg.get('text_y_ratio')
    yr = 0.5 if yr is None else float(yr)
    return {'y': yr, 'x': a.text_x_ratio, 'anchor': a.text_anchor}, 'global'


def pos_args(pos):
    return ['--text-y-ratio', str(pos['y']),
            '--text-x-ratio', str(pos['x']),
            '--text-anchor', pos['anchor']]


def resolve_images(segs, args):
    """返回与 segments 等长的背景图路径列表。任一环节对不齐就退出。"""
    n = len(segs)

    # 1) 段内显式 image 字段
    if all('image' in s for s in segs):
        paths = [s['image'] for s in segs]
        for p in paths:
            if not os.path.exists(p):
                sys.exit('背景图不存在: %s' % p)
        return paths

    # 2) --mapping JSON
    if args.mapping:
        try:
            with open(args.mapping, encoding='utf-8') as f:
                m = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            sys.exit('mapping 文件读取失败: %s' % e)
        missing = [s['id'] for s in segs if s['id'] not in m]
        if missing:
            sys.exit('mapping 缺少段落: %s' % ', '.join(missing))
        paths = [m[s['id']] for s in segs]
        for p in paths:
            if not os.path.exists(p):
                sys.exit('背景图不存在: %s' % p)
        return paths

    # 3) --images 目录，按 mtime 排序
    if args.images:
        files = sorted(
            (os.path.join(args.images, f) for f in os.listdir(args.images)
             if f.lower().endswith(IMG_EXTS)),
            key=lambda p: os.path.getmtime(p))
        if len(files) != n:
            sys.exit('背景图数量(%d)与段落数(%d)不一致，请改用 image 字段或 --mapping 显式对齐'
                     % (len(files), n))
        return files

    sys.exit('未指定背景图来源：请在 segments 里写 image 字段，或传 --mapping / --images')


def main():
    ap = argparse.ArgumentParser(description='批量生成口播视频卡片（引用 xhs-image-note-release 生成器）')
    ap.add_argument('--script', required=True, help='voice_script.json 路径')
    ap.add_argument('--mapping', help='段落 id -> 背景图路径 的 JSON 文件')
    ap.add_argument('--images', help='背景图目录（按文件修改时间对齐段落顺序）')
    ap.add_argument('--out-dir', default='assets', help='卡片输出目录（默认 assets/）')
    ap.add_argument('--theme', default=None,
                    help='卡片主题。不传时：--content-type history → history 古风电影感，'
                         '否则取 config.theme（默认 journal）')
    ap.add_argument('--content-type', choices=['general', 'history'], default='general',
                    help='题材类型。history 时默认套用古风字体主题（历史故事优先古风字体）')
    ap.add_argument('--tag', default=None, help='顶部标签（默认取 config.tag）')
    ap.add_argument('--account', default=None, help='署名（默认取 config.account）')
    ap.add_argument('--font-main', default=None,
                    help='显式指定主文案字体（CSS font-family），优先级高于主题自带字体')
    ap.add_argument('--text-y-ratio', type=float, default=None,
                    help='全局文字垂直位置 0-1，默认 0.5。仅关闭自动留白检测后生效')
    ap.add_argument('--text-x-ratio', type=float, default=0.5, help='全局文字水平位置 0-1')
    ap.add_argument('--text-anchor', choices=['start', 'middle', 'end'], default='middle')
    ap.add_argument('--safe-axis', choices=['vertical', 'both'], default='vertical',
                    help='自动留白检测维度：vertical 只选上下带，both 还会靠左/右排版')
    ap.add_argument('--no-auto-safe-area', action='store_true',
                    help='关闭自动留白检测，改用 --text-y-ratio 全局位置')
    ap.add_argument('--strict-lines', action='store_true',
                    help='段落缺 lines 字段时直接报错（默认只警告并自动拆行）')
    ap.add_argument('--no-proof', action='store_true',
                    help='不自动生成卡片全检联系表（默认生成，强制逐张复核）')
    ap.add_argument('--width', type=int, default=1080)
    ap.add_argument('--height', type=int, default=1440,
                    help='卡片高度，默认 1440（build_composition 的 card_h）')
    ap.add_argument('--generator', default=DEFAULT_GENERATOR,
                    help='card_generator.py 路径（默认引用 xhs-image-note-release）')
    ap.add_argument('--scrim', type=float, default=None, help='背景遮罩强度 0-0.92')
    ap.add_argument('--blur', type=int, default=None, help='背景高斯模糊半径')
    ap.add_argument('--cover-h', action='store_true',
                    help='只生成横屏封面 card_01_h.png（1920x1080，用第一段金句），'
                         '供视频号/抖音横屏封面使用；不与竖版卡片一起跑')
    ap.add_argument('--cover-h-size', default='1920x1080',
                    help='横屏封面尺寸，默认 1920x1080')
    ap.add_argument('--dry-run', action='store_true', help='只打印将执行的命令，不实际生成')
    a = ap.parse_args()

    if not os.path.exists(a.generator):
        sys.exit('找不到卡片生成器: %s\n  它属于 xhs-image-note-release skill，'
                 '请先安装，或用 --generator 指定路径' % a.generator)

    try:
        with open(a.script, encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        sys.exit('文案 JSON 读取失败: %s' % e)
    segs = data.get('segments') or []
    if not segs:
        sys.exit('文案里没有 segments')

    cfg = load_config()
    # 历史题材默认走古风字体主题；--theme 显式指定始终最高
    theme = (a.theme or ('history' if a.content_type == 'history' else None)
             or cfg.get('theme') or 'journal')
    tag = a.tag if a.tag is not None else cfg.get('tag')
    account = a.account if a.account is not None else cfg.get('account')
    auto_on = not a.no_auto_safe_area
    low_conf = []          # 自动留白检测低置信度的段落，末尾汇总提醒人工复核

    paths = resolve_images(segs, a)
    n = len(segs)

    os.makedirs(a.out_dir, exist_ok=True)

    # ── 横屏封面模式：只用首段金句，出一张 16:9 ──
    if a.cover_h:
        try:
            cw, chh = [int(x) for x in a.cover_h_size.lower().split('x')]
        except ValueError:
            sys.exit('--cover-h-size 格式应为 宽x高，例如 1920x1080')
        seg0 = segs[0]
        lines0 = seg0.get('lines') or split_quote(seg0.get('quote') or seg0['text'])
        font0 = seg0.get('font_main') or a.font_main or cfg.get('font_main')
        pos0, src0 = resolve_text_pos(seg0, paths[0], a, cfg, auto_on, low_conf)
        out = os.path.join(a.out_dir, 'card_01_h.png')
        cmd = ['python3', a.generator,
               '--theme', theme,
               '--background', paths[0],
               '--lines', '\\n'.join(lines0),
               '--width', str(cw),
               '--height', str(chh),
               '--hide-page-number',
               '--output', out] + pos_args(pos0)
        if font0:
            cmd += ['--font-main', font0]
        if tag:
            cmd += ['--tag', tag]
        if account:
            cmd += ['--account', account]
        if a.scrim is not None:
            cmd += ['--scrim', str(a.scrim)]
        print('横屏封面 %dx%d <- %s | %s | 位置 %s(%.2f)'
              % (cw, chh, os.path.basename(paths[0]), ' / '.join(lines0),
                 src0, pos0['y']))
        if a.dry_run:
            print('    (dry-run) %s' % ' '.join(cmd))
            return
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            sys.exit('横屏封面生成异常: %s' % e)
        if r.returncode != 0 or not os.path.exists(out):
            sys.exit('横屏封面生成失败:\n%s\n%s' % (r.stdout[-400:], r.stderr[-400:]))
        print('已生成 %s。发布时 COVER_HORIZONTAL 留空即会自动探测该文件。' % out)
        return

    print('段落 %d 个，背景图 %d 张，主题 %s，留白检测 %s，输出 %s/'
          % (n, len(paths), theme, ('开/' + a.safe_axis) if auto_on else '关', a.out_dir))

    failures = 0
    for i, (seg, img) in enumerate(zip(segs, paths), 1):
        if not seg.get('lines'):
            msg = ('段 %s 未写 lines，将按第一个逗号自动拆行；'
                   '建议显式写两行保证金句分行可控' % seg['id'])
            if a.strict_lines:
                sys.exit('✗ ' + msg)
            print('  ⚠ ' + msg)
        lines = seg.get('lines') or split_quote(seg.get('quote') or seg['text'])
        # 字体优先级：段内 font_main > --font-main > config > 主题自带
        font = seg.get('font_main') or a.font_main or cfg.get('font_main')
        pos, src = resolve_text_pos(seg, img, a, cfg, auto_on, low_conf)
        out = os.path.join(a.out_dir, 'card_%02d.png' % i)
        cmd = ['python3', a.generator,
               '--theme', theme,
               '--background', img,
               '--lines', '\\n'.join(lines),
               '--page-number', str(i),
               '--total-pages', str(n),
               '--width', str(a.width),
               '--height', str(a.height),
               '--output', out] + pos_args(pos)
        if font:
            cmd += ['--font-main', font]
        if tag:
            cmd += ['--tag', tag]
        if account:
            cmd += ['--account', account]
        if a.scrim is not None:
            cmd += ['--scrim', str(a.scrim)]
        if a.blur is not None:
            cmd += ['--blur', str(a.blur)]

        print('  card_%02d <- %s | %s | 位置 %s y=%.2f x=%.2f/%s'
              % (i, os.path.basename(img), ' / '.join(lines), src,
                 pos['y'], pos['x'], pos['anchor']))
        if a.dry_run:
            print('    (dry-run) %s' % ' '.join(cmd))
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            failures += 1
            print('    ✗ 生成异常: %s' % e)
            continue
        if r.returncode != 0 or not os.path.exists(out):
            failures += 1
            print('    ✗ 生成失败:\n%s\n%s' % (r.stdout[-400:], r.stderr[-400:]))
        else:
            time.sleep(0.2)

    if a.dry_run:
        print('dry-run 完成，未写入任何文件')
        return
    if failures:
        sys.exit('%d 张卡片生成失败，请检查上方错误' % failures)

    # 生成完自动出全检联系表：视觉质量不能抽样（曾抽 6 张漏掉压脸的第 01 张）
    if not a.no_proof:
        proof = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'cards_contact_sheet.py')
        r_ok = False
        try:
            r = subprocess.run(['python3', proof, '--assets', a.out_dir,
                                '--out-dir', os.path.join(a.out_dir, '_check')],
                               capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                print('  ✗ 全检联系表生成失败:\n%s\n%s'
                      % (r.stdout[-800:], r.stderr[-800:]))
            else:
                print('全检联系表: %s/_check/（group_*.png 逐组看，all.png 看整体）'
                      % a.out_dir)
                r_ok = True
        except (OSError, subprocess.SubprocessError) as e:
            detail = (getattr(e, 'stderr', None) or getattr(e, 'stdout', None)
                       or str(e))
            print('  ✗ 全检联系表生成失败: %s' % detail)
        # 全检是铁律：联系表出不来就等于没做视觉复核，不能静默当成功收尾。
        if not r_ok:
            sys.exit('全检联系表失败，卡片尚未通过强制全检；修复后重跑，'
                     '或显式传 --no-proof 跳过（不建议）')

    if low_conf:
        print('⚠ %d 张自动定位低置信（最优/次优几乎同分，算法无可靠信号），'
              '务必在联系表里逐张确认，必要时写 text_pos：' % len(low_conf))
        for sid, band, gap in low_conf:
            print('    %-6s %s  差值 %.1f' % (sid, band, gap))

    print('已生成 %d 张卡片到 %s/。下一步：跑 build_composition.py 重建时间轴后渲染。'
          % (n, a.out_dir))


if __name__ == '__main__':
    main()
