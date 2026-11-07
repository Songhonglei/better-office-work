#!/bin/bash
# 一键重建：时间轴 → 内联 gsap → 渲染 → 混音。
#
# 用法:
#   bash rebuild.sh [项目目录]          # 默认当前目录
#
# 项目目录约定（与 build_composition.py 的产出一致）:
#   voice_script.json   文案（含 segments）
#   voice/*.mp3         tts.py 生成的分段配音
#   assets/card_*.png   gen_cards.py 生成的卡片
#   out/                成片输出目录（自动创建）
#
# 可用环境变量:
#   BGM=/path/to.mp3      背景音乐（默认数据目录的 Frost Waltz.mp3，找不到则报错提示先下载）
#   PRE / GAP / TAIL      时间轴留白，默认 0.6 / 0.45 / 1.5
#   RATE                  已在 tts 阶段生效，此处不涉及
#
# 典型流程:
#   tts.py → gen_cards.py → 本脚本 → release.sh

set -e

PROJECT_DIR="${1:-$PWD}"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

# ── 前置检查 ─────────────────────────────────────────────
for f in voice_script.json index.html; do
  [ "$f" = "index.html" ] && continue
  [ -f "$f" ] || { echo "✗ 缺少 $f（在 $PROJECT_DIR）"; exit 10; }
done
[ -d voice ] || { echo "✗ 缺少 voice/ 目录，请先跑 tts.py 生成配音"; exit 10; }
ls assets/card_*.png >/dev/null 2>&1 || { echo "✗ 缺少 assets/card_*.png，请先跑 gen_cards.py 生成卡片"; exit 10; }

PRE="${PRE:-0.6}"; GAP="${GAP:-0.45}"; TAIL="${TAIL:-1.5}"

# ── 1) 时间轴（卡片时长由配音真实时长驱动） ────────────────
echo "── 1/4 时间轴 ──"
python3 "$SKILL_DIR/scripts/build_composition.py" \
  --script voice_script.json --voice-dir voice \
  --pre "$PRE" --gap "$GAP" --tail "$TAIL"

# ── 2) 内联 gsap（外链脚本在 hyperframes 里有时序 bug，必须内联） ──
echo "── 2/4 内联 gsap ──"
python3 - <<'EOF'
import os
if not os.path.exists('assets/vendor/gsap.min.js'):
    os.makedirs('assets/vendor', exist_ok=True)
    import urllib.request
    urllib.request.urlretrieve(
        'https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js',
        'assets/vendor/gsap.min.js')
    print('  gsap.min.js 已从 CDN 下载')
html = open('index.html', encoding='utf-8').read()
if 'assets/vendor/gsap.min.js' in html:
    gsap = open('assets/vendor/gsap.min.js', encoding='utf-8').read()
    html = html.replace('<script src="assets/vendor/gsap.min.js"></script>',
                        '<script>\n' + gsap + '\n</script>')
    open('index.html', 'w', encoding='utf-8').write(html)
    print('  inlined gsap OK')
else:
    print('  already inlined')
EOF

# ── 3) 渲染（优先本机 Chrome；chrome-headless-shell 下载经常失败） ──
echo "── 3/4 渲染 ──"
mkdir -p out
if [ -z "$HYPERFRAMES_BROWSER_PATH" ] && [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  export HYPERFRAMES_BROWSER_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
fi
npx -y hyperframes@0.9.1 render --output out/silent.mp4 2>&1 | tail -4

# ── 4) 混音（人声 + BGM） ────────────────────────────────
echo "── 4/4 混音 ──"
if [ -z "$BGM" ]; then
  # 曲库属运行时素材，放在 skill 目录之外（~/space/skills-data/video-multi-release/music）
  MUSIC_DIR="${WB_SKILLS_DATA:-$HOME/space/skills-data}/video-multi-release/music"
  DEFAULT_BGM="$MUSIC_DIR/Frost Waltz.mp3"
  if [ -f "$DEFAULT_BGM" ]; then
    BGM="$DEFAULT_BGM"
  else
    echo "✗ 未指定 BGM 且默认曲目不存在（$DEFAULT_BGM）。"
    echo "  先跑 assets/music/download.sh 下载曲库到 $MUSIC_DIR，或用 BGM=/path/to.mp3 指定。"
    exit 11
  fi
fi
[ -f "$BGM" ] || { echo "✗ BGM 文件不存在: $BGM"; exit 11; }

python3 "$SKILL_DIR/scripts/mix_audio.py" \
  --silent out/silent.mp4 --bgm "$BGM" --out out/final.mp4 2>&1 | tail -3

echo
ls -la out/final.mp4
echo "✓ 成片完成：$PROJECT_DIR/out/final.mp4"
