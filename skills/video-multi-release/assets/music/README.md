# BGM 曲库（历史 / 心理类口播）

来源：[incompetech](https://incompetech.com) — Kevin MacLeod
许可：**CC-BY 4.0**（可商用、可修改，但**必须在视频简介/文案中署名**）

署名模板（复制到视频简介末尾）：

```
音乐: <曲名> - Kevin MacLeod (incompetech.com)
Licensed under Creative Commons: By Attribution 4.0
https://creativecommons.org/licenses/by/4.0/
```

## 曲目清单

### 历史 / 文化叙事（雨夜心灯）

| 文件 | 时长 | 调性 |
|---|---|---|
| Sovereign.mp3 | 6:12 | 庄严弦乐，宏大历史叙事 |
| Crossing the Divide.mp3 | 3:13 | 电影感，时代跨越 |
| Impact Lento.mp3 | 3:31 | 缓慢厚重，历史压迫感 |
| Frost Waltz.mp3 | 2:15 | 古典华尔兹，近代史/优雅叙事 |
| Ossuary 1 - A Beginning.mp3 | 3:08 | 阴郁人声合唱，战乱/悲怆题材 |

### 心理 / 内省

| 文件 | 时长 | 调性 |
|---|---|---|
| Floating Cities.mp3 | 3:04 | 孤独漂浮感钢琴，心理独白首选 |
| Heartbreaking.mp3 | 1:36 | 忧伤钢琴，情感故事 |
| Meditation Impromptu 02.mp3 | 4:09 | 冥想氛围，治愈向 |
| Reawakening.mp3 | 3:34 | 缓慢苏醒，成长/希望收尾 |
| Long Note Two.mp3 | 7:42 | 长时氛围铺底，长文口播 |

## 使用

```bash
python3 scripts/mix_audio.py --silent /tmp/silent.mp4 \
  --bgm "assets/music/Floating Cities.mp3" --out out/final.mp4
```

混音逻辑（mix_audio.py 内置）：BGM 压低 -14dB 铺在人声下，开头 2s 淡入、结尾 2.5s 淡出。

## 换机恢复

mp3 不入 git（体积 ~87MB），新机器一键重下：

```bash
cd "$(dirname "$0")"
for t in "Sovereign" "Crossing the Divide" "Impact Lento" "Frost Waltz" \
         "Ossuary 1 - A Beginning" "Floating Cities" "Heartbreaking" \
         "Meditation Impromptu 02" "Reawakening" "Long Note Two"; do
  curl -s -o "$t.mp3" "https://incompetech.com/music/royalty-free/mp3-royaltyfree/$(echo "$t" | sed 's/ /%20/g').mp3"
done
```
