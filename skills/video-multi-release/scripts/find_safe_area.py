#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动留白检测：给一张背景图，找出最适合叠字的「暗且平」的区域。

用途：AI 生成的历史插画主体常落在画面中部，而文字默认也居中，容易压住人物头部。
本脚本把图缩成 90x120 的灰度小图，用与文字块等高的滑动窗口扫全图，
只评估文字真正会覆盖的水平区（排除左右暗角），按亮度/方差/结构梯度打分，
返回给 card_generator.py 的 --text-y-ratio。

不引入任何第三方依赖，只用 ffmpeg（本来就是本 skill 的依赖）+ Python 标准库。

★★ 能力边界（2026-11-10 全检 18 张后确认）★★
亮度/方差/梯度只是「主体」的代理量。整幅都是暗调的图里，
暗色人脸和暗背景几乎不可分（实测 img_01 最优窗口 53.5 vs 次优 53.6，差 0.1 分），
这时算法其实没有信号，只是险胜。所以：
  1) 输出 confidence；low 时 gen_cards.py 会打警告，必须人工复核；
  2) 段级 text_pos 优先级永远高于本检测结果；
  3) 最根本的解法是在生图提示词里强制「主体置于下三分之一、上方纯暗留白」；
  4) 生成后必须全检所有卡片，不要抽样。

用法:
  python3 find_safe_area.py --image images/img_06.png
  python3 find_safe_area.py --image images/img_06.png --axis both --json
  from find_safe_area import analyze_image   # gen_cards.py 内部调用
"""

import argparse
import json
import math
import subprocess
import sys

W, H = 90, 120
# 窗口高度必须对齐文字块实际高度：两行大字约 320px / 1440px ≈ 22% → 120*0.22 ≈ 27 行。
# 旧值 40 行（33%）比文字块大一半，窗口里空的部分会替有脸的部分「背书」。
WIN_H = 28
STEP = 6
# 文字水平居中、宽度约 78%，只评估它真正覆盖的区域，别让左右暗角拉低分数。
X0, X1 = int(W * 0.10), int(W * 0.90)
Y_MIN, Y_MAX = 0.24, 0.76   # 文字中心允许的相对高度，太贴边会被生成器 clamp


def read_gray(path):
    cmd = ['ffmpeg', '-v', 'error', '-i', path,
           '-vf', 'scale=%d:%d,format=gray' % (W, H),
           '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError('ffmpeg 读取失败: %s' % p.stderr.decode('utf-8', 'ignore')[-200:])
    if len(p.stdout) != W * H:
        raise RuntimeError('灰度数据长度异常: %d（期望 %d）' % (len(p.stdout), W * H))
    return p.stdout


def stats(vals):
    n = len(vals)
    if not n:
        return 0.0, 0.0
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    return mean, math.sqrt(var)


def structural_density(rows, y0, win_h, x0=X0, x1=X1):
    """相邻像素梯度均值，近似「画面里有没有轮廓/结构」。

    暗色人物跟纯黑空背景的亮度和方差可能接近，但人物有轮廓、边缘梯度明显更高。
    只在文字实际覆盖的水平区间里算，避免左右暗角稀释掉五官的边缘信号。
    """
    total, n = 0, 0
    for y in range(y0, min(y0 + win_h, H) - 1):
        row, nxt = rows[y], rows[y + 1]
        for x in range(x0, min(x1, W) - 1):
            total += abs(row[x + 1] - row[x]) + abs(nxt[x] - row[x])
            n += 2
    return total / n if n else 0.0


def analyze_image(path, axis='vertical'):
    """返回 {'y_ratio','x_ratio','anchor','band','side','scores'}。

    axis='vertical'：只选上下带，水平保持居中（默认，节奏最稳）。
    axis='both'    ：再选更空的左/右半，靠边排版。
    """
    buf = read_gray(path)
    rows = [buf[y * W:(y + 1) * W] for y in range(H)]

    scored = []
    for y0 in range(0, H - WIN_H + 1, STEP):
        vals = [v for row in rows[y0:y0 + WIN_H] for v in row[X0:X1]]
        mean, sd = stats(vals)
        edge = structural_density(rows, y0, WIN_H)
        center = (y0 + WIN_H / 2) / H
        ratio = max(Y_MIN, min(Y_MAX, round(center, 3)))
        # 暗 + 平 + 无轮廓 = 适合叠字。
        # 结构梯度权重从 6 提到 8：暗调图里亮度差异只有几个灰阶，边缘是更可靠的信号。
        # ratio<0.30 加一点惩罚：顶部紧挨标签(y=130)，18 张全挤在最上面节奏太单调。
        score = mean + 1.0 * sd + 8.0 * edge + 10.0 * abs(ratio - 0.5)
        if ratio < 0.30:
            score += 5.0
        scored.append({'y0': y0, 'y_ratio': ratio, 'mean': round(mean, 1),
                       'sd': round(sd, 1), 'edge': round(edge, 2),
                       'score': round(score, 1)})

    ordered = sorted(scored, key=lambda x: x['score'])
    best = ordered[0]
    # 最优与次优差距太小 = 算法没有可靠信号（img_01 实测差 0.1 分），必须人工复核。
    gap = round(ordered[1]['score'] - best['score'], 1) if len(ordered) > 1 else 99.0
    confidence = 'low' if gap < 3.0 else ('medium' if gap < 10.0 else 'high')
    band = 'top' if best['y_ratio'] < 0.42 else ('bottom' if best['y_ratio'] > 0.62 else 'mid')
    out = {
        'y_ratio': best['y_ratio'],
        'x_ratio': 0.5,
        'anchor': 'middle',
        'band': band,
        'side': 'center',
        'confidence': confidence,
        'gap': gap,
        'scores': scored,
    }

    if axis == 'both':
        y0 = best['y0']
        left, right = [], []
        for row in rows[y0:y0 + WIN_H]:
            # 与 vertical 评分同口径：只评文字覆盖区，别把左右暗角算进来
            left.extend(row[X0:W // 2])
            right.extend(row[W // 2:X1])
        lm, ls = stats(left)
        rm, rs = stats(right)
        lscore = lm + 1.6 * ls
        rscore = rm + 1.6 * rs
        if lscore < rscore:
            out.update({'x_ratio': 0.08, 'anchor': 'start', 'side': 'left'})
        else:
            out.update({'x_ratio': 0.92, 'anchor': 'end', 'side': 'right'})
        out['side_scores'] = {'left': round(lscore, 1), 'right': round(rscore, 1)}

    return out


def main():
    ap = argparse.ArgumentParser(description='检测背景图最适合叠字的暗部留白区')
    ap.add_argument('--image', required=True)
    ap.add_argument('--axis', choices=['vertical', 'both'], default='vertical')
    ap.add_argument('--json', action='store_true', help='只输出 JSON')
    a = ap.parse_args()
    try:
        r = analyze_image(a.image, a.axis)
    except (OSError, RuntimeError) as e:
        sys.exit('留白检测失败: %s' % e)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print('选中: %s 带%s  文字中心 y=%.2f  x=%.2f  对齐=%s  置信=%s(差 %.1f)'
              % (r['band'], ('/' + r['side']) if r['side'] != 'center' else '',
                 r['y_ratio'], r['x_ratio'], r['anchor'],
                 r['confidence'], r['gap']))
        if r['confidence'] == 'low':
            print('  ⚠ 最优与次优几乎同分，算法没有可靠信号，必须人工复核并写段级 text_pos')
        for s in r['scores']:
            print('  窗口 y=%3d → y_ratio %.2f  亮度 %5.1f  起伏 %5.1f  轮廓 %4.2f  得分 %6.1f'
                  % (s['y0'], s['y_ratio'], s['mean'], s['sd'], s['edge'], s['score']))


if __name__ == '__main__':
    main()
