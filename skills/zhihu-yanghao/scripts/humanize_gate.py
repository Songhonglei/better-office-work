#!/usr/bin/env python3
"""zhihu-yanghao 发布前「去 AI 味」硬门禁（v1.5.0）。

流程：调用 text-humanize 的 preflight-check.py 检查中文正文，
      FAIL 全归零才写凭证；run_shift.js 发布前校验凭证，凭证不过就跳过发布。

用法：
  python3 scripts/humanize_gate.py /abs/answer.txt
  python3 scripts/humanize_gate.py /abs/answer.txt --tier short --strict
  python3 scripts/humanize_gate.py /abs/answer.txt --preflight /abs/preflight-check.py

输出：
  HUMANIZE_GATE_OK ...            → 凭证已写入 /tmp/zhihu_humanize_pass.json
  HUMANIZE_GATE_FAIL ...          → 未通过（旧凭证会被删除），退出码 1

凭证与正文按 sha256 绑定：正文改动一个字都需重跑本脚本，防止「检查 A 稿、发布 B 稿」。
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_GATE_FILE = "/tmp/zhihu_humanize_pass.json"


def find_preflight(explicit):
    if explicit:
        p = Path(os.path.expanduser(explicit)).resolve()
        return p if p.is_file() else None
    # 默认即用户级 skill 的标准路径；环境变量只是可选覆盖
    env = os.getenv("TEXT_HUMANIZE_PREFLIGHT", "~/.workbuddy/skills/text-humanize/scripts/preflight-check.py")
    candidates = [Path(os.path.expanduser(env))]
    # 与 zhihu-yanghao 同级的 skill 目录（项目级安装）
    candidates.append(Path(__file__).resolve().parents[2] / "text-humanize/scripts/preflight-check.py")
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None


def parse_json_output(raw):
    """preflight --json 输出为纯 JSON；兼容前面夹带日志行的情况。"""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        if start >= 0:
            try:
                return json.loads(raw[start:])
            except json.JSONDecodeError:
                pass
    return None


def main():
    ap = argparse.ArgumentParser(description="发布前去 AI 味硬门禁（text-humanize preflight）")
    ap.add_argument("content_file", help="回答正文文件绝对路径")
    ap.add_argument("--tier", default="long", choices=["short", "long", "literary"],
                    help="text-humanize 体裁档位，知乎回答默认 long（最保守，不注入错别字）")
    ap.add_argument("--preflight", default=None, help="preflight-check.py 路径（默认自动定位）")
    ap.add_argument("--gate-file", default=DEFAULT_GATE_FILE, help="凭证输出路径")
    ap.add_argument("--strict", action="store_true", help="WARN 也计入阻断（默认只拦 FAIL）")
    ap.add_argument("--max-age-hours", type=float, default=6.0,
                    help="凭证有效期（小时），写入凭证供 run_shift.js 核对")
    args = ap.parse_args()

    gate_path = Path(args.gate_file)
    content_path = Path(os.path.expanduser(args.content_file)).resolve()
    if not content_path.is_file():
        print("HUMANIZE_GATE_FAIL: 正文文件不存在 " + str(content_path))
        sys.exit(1)

    try:
        text = content_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print("HUMANIZE_GATE_FAIL: 正文不是 UTF-8，禁止发布（中文乱码事故红线）")
        sys.exit(1)
    if not text.strip():
        print("HUMANIZE_GATE_FAIL: 正文为空")
        sys.exit(1)

    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    preflight = find_preflight(args.preflight)
    if not preflight:
        print("HUMANIZE_GATE_FAIL: 找不到 text-humanize 的 preflight-check.py；"
              "先安装 text-humanize skill，或用 --preflight / TEXT_HUMANIZE_PREFLIGHT 指定路径")
        sys.exit(1)

    cmd = [sys.executable, str(preflight), "--tier", args.tier, "--lang", "zh",
           "--json", str(content_path)]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as e:
        print("HUMANIZE_GATE_FAIL: preflight 执行异常 " + str(e))
        sys.exit(1)

    data = parse_json_output(cp.stdout)
    if data is None:
        print("HUMANIZE_GATE_FAIL: preflight 输出无法解析（stdout 前 300 字）= " +
              cp.stdout[:300].replace("\n", " "))
        if cp.stderr:
            print("  stderr=" + cp.stderr[:300].replace("\n", " "))
        sys.exit(1)

    fail = int(data.get("fail", -1) or 0)
    warn = int(data.get("warn", 0) or 0)
    blocked = fail > 0 or (args.strict and warn > 0) or cp.returncode != 0
    if blocked:
        # 失败时删除旧凭证，避免上一稿的凭证被复用
        try:
            gate_path.unlink(missing_ok=True)
        except OSError:
            pass
        bad = [r.get("name", "?") for r in data.get("rows", [])
               if r.get("level") in ("FAIL", "WARN") and r.get("mark") not in ("OK", "-")]
        print("HUMANIZE_GATE_FAIL: fail=%d warn=%d exit=%d strict=%s 未通过项=%s"
              % (fail, warn, cp.returncode, args.strict, "、".join(bad[:8]) or "（见 preflight 明细）"))
        print("HUMANIZE_GATE_HINT: 加载 text-humanize skill 中文模式改写正文，复测归零后再跑本脚本；禁止绕过门禁直接发布")
        sys.exit(1)

    gate = {
        "ok": True,
        "contentFile": str(content_path),
        "sha256": sha,
        "length": len(text),
        "tier": args.tier,
        "fail": fail,
        "warn": warn,
        "strict": bool(args.strict),
        "maxAgeHours": args.max_age_hours,
        "checkedAt": int(time.time()),
        "checkedAtISO": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        "preflight": str(preflight),
    }
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HUMANIZE_GATE_OK: tier=%s fail=0 warn=%d len=%d sha256=%s gate=%s"
          % (args.tier, warn, len(text), sha[:12], str(gate_path)))
    print("HUMANIZE_GATE_NOTE: 凭证与正文 sha256 绑定；正文再改一个字都要重跑本脚本")


if __name__ == "__main__":
    main()
