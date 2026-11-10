# 由 oss-pages-sync Skill 的 `run.py ci setup` 生成，请勿手工修改。
# 改域名 / bucket / 调度 / 站点清单请改本机 config.json 后执行 `run.py ci update`。
name: Sync static sites to Aliyun OSS

on:
  schedule:
    # cron 按 UTC；配置里的 timezone 仅用于展示，本行为 __CRON__
    - cron: '__CRON__'
  workflow_dispatch:
    inputs:
      site:
        description: '只同步某个站点（留空 = 全部）'
        required: false
        default: ''
  repository_dispatch:
    types: [sync-oss]

permissions:
  contents: read

jobs:
  sync:
    runs-on: ubuntu-latest
    concurrency:
      group: oss-pages-sync
      cancel-in-progress: false
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install oss2
        run: python -m pip install --quiet oss2
      - name: Sync to OSS
        id: sync
        env:
          OSS_ACCESS_KEY_ID: ${{ secrets.__SECRET_ID__ }}
          OSS_ACCESS_KEY_SECRET: ${{ secrets.__SECRET_KEY__ }}
          OSS_TARGET_DOMAIN: '__DOMAIN__'
          OSS_BUCKET: '__BUCKET__'
          OSS_ENDPOINT: '__ENDPOINT__'
          REQUIRE_UPLOAD: '1'
          ONLY_SITE: ${{ github.event.inputs.site || github.event.client_payload.site }}
        run: python __DIR__/ci_sync.py
      # 源站无变化：跳过上传与 L2，尽早结束（手动触发仍会强制校验一次）
      - name: No changes
        if: ${{ steps.sync.outputs.changed == 'false' && steps.sync.outputs.crawl_errors == 'false' && github.event_name != 'workflow_dispatch' }}
        run: echo "源站与 OSS 完全一致（0 变化、0 抓取失败），跳过 L2 校验。"
      - name: Verify (L2)
        if: ${{ steps.sync.outputs.changed == 'true' || steps.sync.outputs.crawl_errors == 'true' || github.event_name == 'workflow_dispatch' }}
        env:
          OSS_ACCESS_KEY_ID: ${{ secrets.__SECRET_ID__ }}
          OSS_ACCESS_KEY_SECRET: ${{ secrets.__SECRET_KEY__ }}
          OSS_TARGET_DOMAIN: '__DOMAIN__'
          OSS_BUCKET: '__BUCKET__'
          OSS_ENDPOINT: '__ENDPOINT__'
          ONLY_SITE: ${{ github.event.inputs.site || github.event.client_payload.site }}
        run: python __DIR__/verify.py --level 2
