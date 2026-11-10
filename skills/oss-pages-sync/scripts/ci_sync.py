#!/usr/bin/env python3
# CI 版同步：复用 sync.py 的「抓线上成品 → 改写链接 → 生成 main.html 副本」，
# 改用 oss2 直接上传（CI 里不装 ossutil）。无凭据时等价于 dry-run，只抓取不上传。
#
#   python3 ci_sync.py                # 本地无凭据 -> DRY-RUN
#   OSS_ACCESS_KEY_ID=xx OSS_ACCESS_KEY_SECRET=yy python3 ci_sync.py   # 真上传
#   ONLY_SITE=html-golive python3 ci_sync.py                            # 只同步一个站
#   SYNC_DRY_RUN=1 ... python3 ci_sync.py                               # 有凭据也只比对不写入
# 在 GitHub Actions 里会把 changed / crawl_errors 写入 $GITHUB_OUTPUT，
# 供 workflow 判断「本次无变化」时直接结束，不再跑 L2 校验。
import hashlib
import mimetypes
import os
import pathlib
import sys

import sync  # 同目录：crawl / STAGING / CONF / CLEAN_URLS / REWRITE_ABSOLUTE

HERE = pathlib.Path(__file__).parent
# 用 or 兜底：GitHub Actions 里未配置的 vars 会注入空字符串，不会走 get 的默认值
BUCKET = os.environ.get("OSS_BUCKET") or "YOUR_OSS_BUCKET_NAME"
ENDPOINT = os.environ.get("OSS_ENDPOINT") or "https://oss-cn-hangzhou.aliyuncs.com"
ONLY_SITE = (os.environ.get("ONLY_SITE") or "").strip()
DRY_RUN = os.environ.get("SYNC_DRY_RUN") == "1"


def emit(name, value):
    """把结论给 workflow：changed=false 时跳过 L2，省掉无意义的重复校验。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s=%s\n" % (name, value))
    except OSError as exc:
        # 写失败会让 workflow 拿不到 changed，进而静默跳过 L2；宁可整轮报红。
        raise RuntimeError("无法写入 GITHUB_OUTPUT（%s）：拒绝静默跳过校验" % exc)


def load_sites():
    # 复用 sync.py 的解析，确保 root=1 开关在本地与 CI 完全一致
    return sync.load_sites()


def content_type(key):
    ctype, _ = mimetypes.guess_type(key)
    if key.endswith((".html", ".htm")):
        return "text/html; charset=utf-8"
    if key.endswith(".css"):
        return "text/css; charset=utf-8"
    if key.endswith((".js", ".mjs")):
        # ES module 必须是合法 JS MIME，否则浏览器按严格 MIME 检查拒绝执行
        return "text/javascript; charset=utf-8"
    if key.endswith(".json"):
        return "application/json; charset=utf-8"
    if key.endswith(".svg"):
        return "image/svg+xml"
    if key.endswith(".txt"):
        return "text/plain; charset=utf-8"
    return ctype or "application/octet-stream"


def main():
    sites = [(r, u) for r, u in load_sites() if not ONLY_SITE or r == ONLY_SITE]
    if not sites:
        print("没有匹配的站点，检查 ONLY_SITE / sites.conf")
        return 1
    staged = []
    total_files = total_bytes = crawl_errors = source_404 = 0
    for repo, url in sites:
        print("=== %s  <-  %s ===" % (repo, url))
        files, failed = sync.crawl(repo, url)
        size = sum(s for _, s in files)
        total_files += len(files)
        total_bytes += size
        # 源站自己就没有的图标/资源（HTTP 404）不是镜像漏文件，不能算抓取故障，
        # 否则每次定时跑都会误判为「有异常」而强制跑 L2，短路逻辑永远不生效。
        real_failed = [f for f in failed if "404" not in f[1]]
        source_404 += len(failed) - len(real_failed)
        crawl_errors += len(real_failed)
        print("   抓取 %d 个文件, %.1f KB" % (len(files), size / 1024))
        if real_failed:
            print("   ⚠ 抓取失败: " + ", ".join("%s(%s)" % f for f in real_failed))
        if len(failed) != len(real_failed):
            print("   · 源站自身 404（忽略）: " +
                  ", ".join(f[0] for f in failed if "404" in f[1]))
        staged.append(repo)
    print("合计 %d 文件 / %.1f KB" % (total_files, total_bytes / 1024))

    kid, ksec = os.environ.get("OSS_ACCESS_KEY_ID"), os.environ.get("OSS_ACCESS_KEY_SECRET")
    if not (kid and ksec):
        # CI 里 REQUIRE_UPLOAD=1：缺凭据必须报红，避免定时任务「假绿」却什么都没同步
        if os.environ.get("REQUIRE_UPLOAD") == "1":
            print("错误: 缺少 OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET，拒绝以 DRY-RUN 假成功")
            return 1
        print("模式: DRY-RUN（未设置 OSS 凭据，未上传任何对象）")
        return 0

    import oss2
    auth = oss2.Auth(kid, ksec)
    bucket = oss2.Bucket(auth, ENDPOINT, BUCKET)
    print("模式: 上传 -> %s / [%s]" % (BUCKET, ", ".join(staged)))

    # 按站点前缀拉远端 ETag，相同内容跳过，避免每次全量重传
    remote = {}
    for repo in staged:
        for obj in oss2.ObjectIterator(bucket, prefix=repo + "/"):
            remote[obj.key] = (obj.etag or "").strip('"')
    uploaded = skipped = uploaded_bytes = pending = 0
    for repo in staged:
        for f in sorted((sync.STAGING / repo).rglob("*")):
            if not f.is_file():
                continue
            key = repo + "/" + f.relative_to(sync.STAGING / repo).as_posix()
            data = f.read_bytes()
            md5 = hashlib.md5(data).hexdigest()
            etag = remote.get(key, "")
            if etag.lower() == md5.lower() and "-" not in etag:
                skipped += 1
                continue
            if DRY_RUN:
                pending += 1
                continue
            bucket.put_object(key, data, headers={"Content-Type": content_type(key)})
            uploaded += 1
            uploaded_bytes += len(data)
    changed = uploaded + pending
    if DRY_RUN:
        print("模式: SYNC_DRY_RUN（只比对，未写入 OSS）| 将更新 %d 个对象" % pending)
    print("上传 %d 个 / %.1f KB，跳过（内容未变）%d 个" % (uploaded, uploaded_bytes / 1024, skipped))
    emit("changed", "true" if changed else "false")
    emit("crawl_errors", "true" if crawl_errors else "false")
    emit("uploaded", str(uploaded))
    emit("source_404", str(source_404))
    if not changed and not crawl_errors:
        print("→ 源站与 OSS 内容完全一致（0 处变化），本次无需上传，可跳过后续 L2 校验。")
    for repo in staged:
        print("   %s/%s/" % (sync.TARGET_BASE, repo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
