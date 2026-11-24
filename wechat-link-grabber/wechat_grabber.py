#!/usr/bin/env python3
"""
微信文件传输助手 - 公众号链接采集器
通过 AppleScript 操控 Mac 微信窗口，提取最近消息中的公众号链接。
"""

import argparse
import html
import subprocess
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

# --- 配置 ---
TARGET_CHAT = "文件传输助手"
MESSAGE_COUNT = 200
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_FILE = OUTPUT_DIR / f"links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

# 公众号链接正则
LINK_PATTERNS = [
    re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE),
]


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def run_applescript(script: str) -> tuple[bool, str]:
    """执行 AppleScript，返回 (成功, 输出/错误)"""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "AppleScript 执行超时"
    except FileNotFoundError:
        return False, "osascript 不可用，请确认在 macOS 上运行"


def is_wechat_running() -> bool:
    ok, value = run_applescript(
        'tell application "System Events" to (name of processes) contains "WeChat"'
    )
    return ok and value.lower() == "true"


def activate_wechat() -> bool:
    log("激活微信窗口...")
    ok, err = run_applescript('tell application "WeChat" to activate')
    if not ok:
        log(f"无法激活微信: {err}")
        return False
    time.sleep(0.8)
    return True


def open_chat(target: str) -> bool:
    """通过 Cmd+F 搜索并打开指定聊天"""
    log(f"搜索聊天: {target}...")

    script = f'''
    tell application "System Events"
        tell process "WeChat"
            set frontmost to true
            delay 0.3
            keystroke "f" using command down
            delay 0.5
            keystroke "{target}"
            delay 0.8
            keystroke return
            delay 0.8
        end tell
    end tell
    '''

    ok, err = run_applescript(script)
    if not ok:
        log(f"搜索聊天失败: {err}")
        return False

    log(f"已打开聊天: {target}")
    return True


def scroll_and_load_history(count: int) -> bool:
    """向上滚动加载历史消息"""
    scroll_times = max(count // 15, 10)

    log(f"滚动加载聊天记录 (约 {scroll_times} 次)...")

    for i in range(scroll_times):
        # Page Up 键模拟向上滚动
        script = '''
        tell application "System Events"
            tell process "WeChat"
                set frontmost to true
                key code 116
                delay 0.15
            end tell
        end tell
        '''

        ok, err = run_applescript(script)
        if not ok:
            log(f"滚动异常: {err}")
            return False

        if (i + 1) % 5 == 0:
            log(f"   滚动中... {i + 1}/{scroll_times}")

    log("历史消息加载完成")
    return True


def select_all_and_copy() -> bool:
    """全选并复制聊天内容"""
    log("正在选中并复制消息...")

    # 先点击聊天区域确保焦点正确
    click_script = '''
    tell application "System Events"
        tell process "WeChat"
            set frontmost to true
            delay 0.3
            set winSize to size of front window
            set clickX to (item 1 of winSize) / 2
            set clickY to (item 2 of winSize) / 2
            click at {clickX, clickY}
            delay 0.5
        end tell
    end tell
    '''
    run_applescript(click_script)

    # Cmd+A 全选
    ok, err = run_applescript('''
    tell application "System Events"
        tell process "WeChat"
            set frontmost to true
            delay 0.3
            keystroke "a" using command down
            delay 0.5
        end tell
    end tell
    ''')
    if not ok:
        log(f"全选可能失败: {err}")

    # Cmd+C 复制
    ok, err = run_applescript('''
    tell application "System Events"
        tell process "WeChat"
            set frontmost to true
            keystroke "c" using command down
            delay 0.8
        end tell
    end tell
    ''')
    if not ok:
        log(f"复制失败: {err}")
        return False

    log("消息已复制到剪贴板")
    return True


def get_clipboard_text() -> str:
    """获取剪贴板文本内容"""
    try:
        import pyperclip
        return pyperclip.paste()
    except ImportError:
        pass

    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout
    except Exception:
        return ""


def extract_links(text: str) -> list[str]:
    """从文本中提取公众号链接"""
    links = []
    for pattern in LINK_PATTERNS:
        matches = pattern.findall(text)
        links.extend(matches)

    unique_links = []
    seen = set()
    for raw_link in links:
        link = html.unescape(raw_link.rstrip(".,;:!?，。；：！？)）】"))
        try:
            url = urlsplit(link)
            if (url.hostname != "mp.weixin.qq.com" or url.username or url.password
                or url.port not in (None, 80, 443)
                or not (url.path == "/s" and url.query or re.fullmatch(r"/s/[A-Za-z0-9_-]+", url.path))):
                continue
            normalized = url._replace(scheme="https", netloc="mp.weixin.qq.com", fragment="").geturl()
        except ValueError:
            continue
        if normalized not in seen:
            seen.add(normalized)
            unique_links.append(normalized)
    return unique_links


def save_links(links: list[str], filepath: Path) -> None:
    """保存链接到文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for link in links:
            f.write(link + "\n")
    log(f"已保存 {len(links)} 个链接 -> {filepath}")


def copy_wechat_messages() -> str:
    """Read the File Transfer Assistant after the user explicitly requests GUI capture."""
    if not is_wechat_running():
        raise RuntimeError("请先打开微信，并核对终端的辅助功能权限")
    before = get_clipboard_text()
    if not (activate_wechat() and open_chat(TARGET_CHAT)
            and scroll_and_load_history(MESSAGE_COUNT) and select_all_and_copy()):
        raise RuntimeError("微信窗口读取失败，可手动复制消息后用 --clipboard")
    text = get_clipboard_text()
    if not text or text == before:
        raise RuntimeError("没有检测到新复制的文本，可用 --clipboard 读取手动复制的消息")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description="从本地文本中提取微信公众号文章链接")
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--input", type=Path, help="读取 UTF-8 文本文件")
    sources.add_argument("--clipboard", action="store_true", help="读取已复制的文本")
    sources.add_argument("--wechat", action="store_true", help="尝试自动读取微信文件传输助手")
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE, help="写入结果文件")
    args = parser.parse_args()

    try:
        if args.input is not None:
            text = args.input.read_text(encoding="utf-8-sig")
        elif args.clipboard:
            text = get_clipboard_text()
        elif args.wechat:
            text = copy_wechat_messages()
        elif not sys.stdin.isatty():
            text = sys.stdin.read()
        else:
            parser.print_help()
            return 2
        links = extract_links(text)
        if not links:
            log("未找到公众号文章链接")
            return 1
        save_links(links, args.output)
        return 0
    except (OSError, RuntimeError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
