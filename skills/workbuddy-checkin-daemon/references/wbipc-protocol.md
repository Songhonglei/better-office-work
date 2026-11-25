# wbipc 守护进程协议参考（逆向自 WorkBuddy 客户端 v5.4.x）

本文件记录 WorkBuddy 桌面客户端内置 IPC 通道 **wbipc** 的完整协议。该通道由
WorkBuddy 主进程内的 broker（`packages/workbuddy-server/src/wbipc/`）提供服务，
用于 CLI / sidecar / 脚本与守护进程安全通信，**无需读取或解密本地登录态 token**。

## 1. 端点发现

文件：`~/.workbuddy/wbipc/endpoint.json`（Windows 下 `WORKBUDDY_CONFIG_DIR` 可覆盖）：

```json
{
  "endpoint": "\\\\.\\pipe\\wbipc-44c40dc267d55d38",
  "ticket": "<约 43 字符的 urlsafe base64 随机票据>"
}
```

- Windows：命名管道 `\\.\pipe\wbipc-<instanceId>`
- macOS / Linux：Unix domain socket `<runtimeDir>/wbipc/b-<instanceId>.sock`
- 每次客户端重启会重新生成 endpoint 与 ticket；客户端退出后管道失效。

## 2. 帧格式

换行分隔的 JSON（NDJSON）：每条消息 = `JSON.stringify(obj) + "\n"`（UTF-8），
单帧上限 1 MiB（`WBIPC_MAX_FRAME_BYTES = 1048576`）。

## 3. 握手（HMAC 挑战-应答）

协议版本 `protocol = 1`，超时 5 秒。

```
客户端 → {"type":"session_hello","protocol_min":1,"protocol_max":1,
          "client_nonce":"<随机串>","ticket_id":"<sha256(ticket) 前 16 位 hex>",
          "client":{"kind":"script","id":"...","version":"..."}}
服务端 → {"type":"session_challenge","protocol":1,
          "server_nonce":"<随机串>","server_proof":"<base64url>"}
客户端 → {"type":"session_prove","client_proof":"<base64url>"}
服务端 → {"type":"session_hello_ack","protocol":1,"connection_epoch":"ce-...",
          "max_inflight":N,"pipes":["wb.request", ...]}
```

proof 计算（base64url 无填充）：

```
server_proof = HMAC-SHA256(key=ticket, transcript(role="server"))
client_proof = HMAC-SHA256(key=ticket, transcript(role="client"))

transcript 编码（encodeTranscript）：依次写入 5 个 UTF-8 段，
每段前加 4 字节大端长度前缀：
  ["wbipc-c"|"wbipc-s", "1", endpoint, clientNonce, serverNonce]
  （客户端证明用 "wbipc-c"，服务端证明用 "wbipc-s"；
    endpoint 必须与 endpoint.json 中字符串完全一致）
```

`ticket_id = sha256(ticket).hexdigest()[:16]`。

## 4. RPC 调用（JSON-RPC 2.0）

握手完成后，所有帧为 JSON-RPC 2.0：

```json
{"jsonrpc":"2.0","id":1,"method":"broker/ListPipes"}
{"jsonrpc":"2.0","id":2,"method":"broker/GetPipe","params":{"pipe":"wb.request"}}
{"jsonrpc":"2.0","id":3,"method":"c:wb.request/http.fetch","mode":"call","params":{...}}
```

- `broker/GetPipe` 返回 `{"channel":"c:<name>","methods":["http.fetch"]}`，
  之后以 `<channel>/<method>` 作为 method 调用，必须带 `mode:"call"`（或 stream，需方法 kind 匹配）。
- 取消：`$/cancel`，`params.id` 为请求 id。
- 错误码：`E_TICKET_INVALID / E_REVOKED / E_PROTOCOL_MISMATCH / E_METHOD_UNKNOWN /
  E_METHOD_KIND_MISMATCH / E_BAD_REQUEST / E_NOT_CONNECTED / E_UPSTREAM / E_BUSY` 等。

## 5. wb.request 管道（http.fetch）

守护进程代为携带登录态向上游发起请求（headers 由服务端注入，客户端接触不到 token）。

请求 params：

| 字段 | 说明 |
|---|---|
| `method` | `GET/HEAD/POST/PUT/PATCH/DELETE` |
| `path` | 必须以 `/` 开头的相对路径；禁止 `//`、`?`、`#`、`..`、空白与控制字符 |
| `query` | 可选，`{k: string}` 键值对 |
| `headers` | 仅允许 `content-type`、`accept`（服务端 allowlist） |
| `body_b64` | 可选，标准 base64 请求体；GET/HEAD 禁止携带 |

响应 result：

```json
{"status":200,"headers":{"content-type":"..."},"body_b64":"<base64>"}
```

响应头仅回传 allowlist：`content-type / content-length / etag / last-modified /
retry-after / location / x-request-id`。响应体上限 640 KiB（超出报
`E_PAYLOAD_TOO_LARGE`，提示改用返回 3xx location 的接口）。上游超时 50 秒。

后端由守护进程 `resolveBackendAuth()` 决定（登录态 auth 域名）。实测以下端点均可通：
- `POST /v2/billing/meter/checkin-activity-status`（Buddy 加油站签到状态）
- `POST /v2/billing/meter/daily-checkin`（领取签到，幂等，已签返回 code=10001）
- `GET /activity/growth/buddy/travel/status`（派猫猫旅行状态，注意无 `/v2` 前缀）
- `POST /activity/growth/buddy/travel/claim`（领取旅行积分，仅 arrived）
- `GET /activity/growth/buddy/travel/config`（旅行地点配置，派遣前取 `data.locations[].id`）
- `POST /activity/growth/buddy/travel/depart`（派遣，body **必须**为 `{"location_id": N}`，
  空 body 或非法 id 返回 `code=400 location not available`；仅 idle 且未达每日上限可派遣）

## 6. 客户端实现要点

- Windows 打开命名管道：`CreateFileW(path, GENERIC_READ|GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL)`，
  读写用 `ReadFile`/`WriteFile`（注意 `ERROR_BROKEN_PIPE=109` 属正常关闭）。
- 纯 Python 标准库即可实现（`ctypes` + `hmac` + `hashlib` + `json` + `struct`），
  参考本技能 `scripts/wb_checkin_daemon.py`。
- 客户端断开后 broker 自动清理会话；单连接 max_inflight 默认 8。
- 会话在账号切换时会被 `revokeAll`，长驻脚本需处理 `E_REVOKED` 后重连。
