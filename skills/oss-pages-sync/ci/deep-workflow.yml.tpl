# 由 oss-pages-sync Skill 的 `run.py ci setup` 生成，请勿手工修改。
# 仅手动触发：真实浏览器录同源 404 + 源站/镜像 DOM 对比，等价于本地 --level 3。
name: Deep verify OSS mirrors (manual)

on:
  workflow_dispatch:
    inputs:
      site:
        description: '只验某个站点（留空 = 全部）'
        required: false
        default: ''

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        run: python -m pip install --quiet oss2 websocket-client
      - name: Chrome availability
        run: |
          for b in google-chrome google-chrome-stable chromium chromium-browser; do
            if command -v "$b" >/dev/null 2>&1; then echo "chrome=$b"; "$b" --version; exit 0; fi
          done
          echo "未找到 Chrome，L3 无法运行"; exit 1
      - name: Verify (L2 + L3)
        env:
          OSS_ACCESS_KEY_ID: ${{ secrets.__SECRET_ID__ }}
          OSS_ACCESS_KEY_SECRET: ${{ secrets.__SECRET_KEY__ }}
          OSS_TARGET_DOMAIN: '__DOMAIN__'
          OSS_BUCKET: '__BUCKET__'
          OSS_ENDPOINT: '__ENDPOINT__'
          ONLY_SITE: ${{ github.event.inputs.site }}
        run: python __DIR__/verify.py --level 3
