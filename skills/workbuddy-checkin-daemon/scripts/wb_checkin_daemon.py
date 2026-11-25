# -*- coding: utf-8 -*-
"""
WorkBuddy 每日签到（守护进程代理版）
====================================
适用于新版 WorkBuddy（登录态 accessToken 为 $wbEncrypted 加密信封的版本）。

原理：不读取、不解密任何 token，而是通过 WorkBuddy 守护进程暴露的 wbipc
命名管道（~/.workbuddy/wbipc/endpoint.json），以 JSON-RPC + HMAC 握手认证，
调用 `wb.request/http.fetch` 让守护进程**代为携带登录态**发起官方接口请求。
token 全程只存在于守护进程内存中，本脚本接触不到。

只调用 3 个已验证端点（与官方签到技能一致）：
  POST /v2/billing/meter/checkin-activity-status   查询签到状态
  POST /v2/billing/meter/daily-checkin             领取签到（幂等，已签返回 code=10001）
  GET  /activity/growth/buddy/travel/status        查询派猫猫旅行状态
  POST /activity/growth/buddy/travel/claim         领取旅行积分（仅 arrived）
  POST /activity/growth/buddy/travel/depart        派遣 Buddy（仅 idle 且未达上限）

输出：单行 JSON 结果（绝不包含任何凭据）。退出码：成功 0 / 失败 1。
依赖：仅 Python 标准库。
"""
import base64
import hashlib
import hmac
import json
import os
import random
import secrets
import socket
import struct
import sys
import time

CONFIG_DIR = os.environ.get("WORKBUDDY_CONFIG_DIR") or os.path.join(
    os.path.expanduser("~"), ".workbuddy")
ENDPOINT_FILE = os.path.join(CONFIG_DIR, "wbipc", "endpoint.json")

PATH_STATUS = "/v2/billing/meter/checkin-activity-status"
PATH_CHECKIN = "/v2/billing/meter/daily-checkin"
PATH_TRAVEL_STATUS = "/activity/growth/buddy/travel/status"
PATH_TRAVEL_CONFIG = "/activity/growth/buddy/travel/config"
PATH_TRAVEL_CLAIM = "/activity/growth/buddy/travel/claim"
PATH_TRAVEL_DEPART = "/activity/growth/buddy/travel/depart"

TRAVEL_STATE_TEXT = {
    "idle": "空闲（可派遣）",
    "traveling": "旅行中",
    "arrived": "已到达，待领取",
}


# ---------------------------------------------------------------- wbipc 客户端

def read_endpoint():
    with open(ENDPOINT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["endpoint"], data["ticket"]


def encode_transcript(role, protocol, endpoint, client_nonce, server_nonce):
    parts = ["wbipc-s" if role == "server" else "wbipc-c",
             str(protocol), endpoint, client_nonce, server_nonce]
    chunks = []
    for p in parts:
        b = p.encode("utf-8")
        chunks.append(struct.pack(">I", len(b)))
        chunks.append(b)
    return b"".join(chunks)


def compute_proof(ticket, role, protocol, endpoint, client_nonce, server_nonce):
    msg = encode_transcript(role, protocol, endpoint, client_nonce, server_nonce)
    digest = hmac.new(ticket.encode("utf-8"), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def ticket_id(ticket):
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:16]


class PipeFile:
    """Windows 命名管道读写（ReadFile/WriteFile）。"""

    def __init__(self, path):
        import ctypes
        self.kernel32 = ctypes.windll.kernel32
        self.handle = self.kernel32.CreateFileW(
            path, 0xC0000000, 0, None, 3, 0, None)  # GENERIC_READ|WRITE, OPEN_EXISTING
        if self.handle == -1 or self.handle == 0xFFFFFFFFFFFFFFFF:
            raise OSError("cannot open pipe %s (winerr=%d)"
                          % (path, self.kernel32.GetLastError()))
        self.buf = b""

    def _read_raw(self, n=65536):
        import ctypes
        buf = ctypes.create_string_buffer(n)
        read = ctypes.c_uint32(0)
        ok = self.kernel32.ReadFile(self.handle, buf, n, ctypes.byref(read), None)
        if not ok and self.kernel32.GetLastError() not in (109, 232):
            raise OSError("ReadFile failed: %d" % self.kernel32.GetLastError())
        return buf.raw[:read.value]

    def write(self, data):
        import ctypes
        written = ctypes.c_uint32(0)
        total = 0
        while total < len(data):
            chunk = data[total:total + 65536]
            ok = self.kernel32.WriteFile(self.handle, chunk, len(chunk),
                                         ctypes.byref(written), None)
            if not ok:
                raise OSError("WriteFile failed")
            total += written.value

    def readline(self, timeout=15):
        deadline = time.time() + timeout
        while b"\n" not in self.buf:
            if time.time() > deadline:
                raise TimeoutError("wbipc frame timeout")
            chunk = self._read_raw()
            if not chunk:
                raise ConnectionError("wbipc pipe closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def close(self):
        import ctypes
        try:
            ctypes.windll.kernel32.CloseHandle(self.handle)
        except Exception:
            pass


class UnixSock:
    def __init__(self, path):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)
        self.buf = b""

    def _read_raw(self, n=65536):
        self.s.settimeout(15)
        return self.s.recv(n)

    def write(self, data):
        self.s.sendall(data)

    def readline(self, timeout=15):
        import time as _t
        self.s.settimeout(timeout)
        deadline = _t.time() + timeout
        while b"\n" not in self.buf:
            if _t.time() > deadline:
                raise TimeoutError("wbipc frame timeout")
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("wbipc socket closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


class WbipcClient:
    def __init__(self):
        self.endpoint, self.ticket = read_endpoint()
        if self.endpoint.startswith("\\\\.\\pipe\\"):
            self.conn = PipeFile(self.endpoint)
        else:
            self.conn = UnixSock(self.endpoint)
        self.next_id = 1

    def _send(self, obj):
        self.conn.write((json.dumps(obj, separators=(",", ":")) + "\n").encode("utf-8"))

    def _recv(self, timeout=15):
        return json.loads(self.conn.readline(timeout).decode("utf-8"))

    def handshake(self):
        client_nonce = secrets.token_urlsafe(24)
        self._send({
            "type": "session_hello",
            "protocol_min": 1,
            "protocol_max": 1,
            "client_nonce": client_nonce,
            "ticket_id": ticket_id(self.ticket),
            "client": {"kind": "script", "id": "wb-checkin-daemon", "version": "1.0"},
        })
        challenge = self._recv()
        if challenge.get("type") != "session_challenge":
            raise RuntimeError("wbipc unexpected frame: %s" % challenge)
        proof = compute_proof(self.ticket, "client", 1, self.endpoint,
                              client_nonce, challenge["server_nonce"])
        self._send({"type": "session_prove", "client_proof": proof})
        ack = self._recv()
        if ack.get("type") != "session_hello_ack":
            raise RuntimeError("wbipc handshake failed: %s" % ack)
        return ack

    def rpc(self, method, params=None, mode=None, timeout=60):
        rid = self.next_id
        self.next_id += 1
        frame = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            frame["params"] = params
        if mode:
            frame["mode"] = mode
        self._send(frame)
        deadline = time.time() + timeout
        while True:
            resp = self._recv(max(1, deadline - time.time()))
            if resp.get("id") != rid:
                continue
            if "error" in resp:
                raise RuntimeError("wbipc rpc error: %s" % json.dumps(resp["error"]))
            return resp.get("result")

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------- 签到主流程

def _api(client, channel, method, path, body=None):
    params = {"method": method, "path": path}
    headers = {}
    if body is not None:
        params["body_b64"] = base64.b64encode(body).decode()
        headers["content-type"] = "application/json"
    if headers:
        params["headers"] = headers
    result = client.rpc("%s/http.fetch" % channel, params, mode="call", timeout=60)
    status = result.get("status")
    raw = base64.b64decode(result.get("body_b64", ""))
    try:
        body_obj = json.loads(raw.decode("utf-8"))
    except Exception:
        body_obj = {"raw": raw.decode("utf-8", "replace")}
    return status, body_obj


def _pick_location(client, channel):
    """读取旅行地点配置，随机挑一个可用地点。

    服务端 travel/depart 要求 body 带 location_id（缺省/非法值返回
    code=400 location not available），故派遣前先取配置。
    返回 (location_id, name)；取不到则 (None, None)。
    """
    try:
        http_status, body = _api(client, channel, "GET", PATH_TRAVEL_CONFIG)
        if http_status != 200 or body.get("code") != 0:
            return None, None
        locs = [l for l in ((body.get("data") or {}).get("locations") or [])
                if isinstance(l, dict) and isinstance(l.get("id"), int)]
        if not locs:
            return None, None
        locs.sort(key=lambda x: x.get("sort") or 0)
        pick = random.choice(locs)
        return pick["id"], pick.get("name")
    except Exception:
        return None, None


def _extract_balance(*bodies):
    for body in bodies:
        if not isinstance(body, dict):
            continue
        candidates = [body.get("data") or {}] + (
            body["data"] if isinstance(body.get("data"), list) else [])
        for node in candidates:
            if not isinstance(node, dict):
                continue
            for key in ("total_credits", "balance", "points_balance",
                        "credit_balance", "total_credit"):
                if isinstance(node.get(key), (int, float)):
                    return int(node[key])
    return None


def run(no_travel=False):
    result = {
        "status": "ok",
        "action": None,
        "msg": "",
        "checked_in": None,
        "streak_days": None,
        "credit_gained": 0,
        "balance": None,
        "travel": None,
    }
    client = WbipcClient()
    try:
        ack = client.handshake()
        pipes = []
        for p in ack.get("pipes", []):
            pipes.append(p if isinstance(p, str) else (p or {}).get("name"))
        if "wb.request" not in pipes:
            raise RuntimeError("wb.request pipe 不可见（WorkBuddy 未登录或会话不可用）")
        gp = client.rpc("broker/GetPipe", {"pipe": "wb.request"}, timeout=15)
        channel = gp["channel"]

        # 1. 查签到状态
        http_status, body = _api(client, channel, "POST", PATH_STATUS, b"{}")
        if http_status != 200 or body.get("code") != 0:
            raise RuntimeError("签到状态查询失败: HTTP %s %s"
                               % (http_status, json.dumps(body, ensure_ascii=False)[:200]))
        data = body.get("data") or {}
        result["balance"] = _extract_balance(body)
        result["streak_days"] = data.get("streak_days")

        if data.get("today_checked_in"):
            result["action"] = "skip_already_signed"
            result["msg"] = "今日已签到，无需重复操作"
        else:
            # 2. 领取签到
            http_status, claim = _api(client, channel, "POST", PATH_CHECKIN, b"{}")
            if http_status == 200 and claim.get("code") == 0:
                cdata = claim.get("data") or {}
                gained = cdata.get("credit") or cdata.get("daily_credit") or 100
                result["action"] = "clicked"
                result["credit_gained"] = gained
                result["streak_days"] = cdata.get("streak_days", result["streak_days"])
                result["balance"] = _extract_balance(claim) or result["balance"]
                result["msg"] = "签到成功，领取 %s 积分" % gained
            elif claim.get("code") == 10001 or "已签到" in str(claim.get("msg", "")):
                result["action"] = "skip_already_signed"
                result["msg"] = "今日已签到（服务端幂等返回）"
            else:
                raise RuntimeError("签到失败: HTTP %s %s"
                                   % (http_status, json.dumps(claim, ensure_ascii=False)[:200]))

        # 3. 派猫猫旅行（失败不影响签到结论）
        if not no_travel:
            travel = {"available": True, "state": None, "state_text": None,
                      "location_name": None, "reward_credit": 0,
                      "daily_limit_reached": None, "auto_log": []}
            try:
                http_status, tbody = _api(client, channel, "GET", PATH_TRAVEL_STATUS)
                if http_status == 200 and tbody.get("code") == 0:
                    tdata = tbody.get("data") or {}
                    travel["state"] = tdata.get("state")
                    travel["state_text"] = TRAVEL_STATE_TEXT.get(tdata.get("state"))
                    travel["daily_limit_reached"] = tdata.get("daily_limit_reached")
                    loc = tdata.get("location") or {}
                    travel["location_name"] = loc.get("name")
                    travel["reward_credit"] = tdata.get("reward_credit") or 0
                    arrive_at = tdata.get("arrive_at")
                    if tdata.get("state") == "traveling" and arrive_at:
                        remain_min = max(0, int((arrive_at - tdata.get("server_now",
                                                 time.time())) / 60))
                        travel["remaining_text"] = "约 %d 分钟" % remain_min
                    if tdata.get("state") == "arrived":
                        http_status, cbody = _api(client, channel, "POST",
                                                  PATH_TRAVEL_CLAIM, b"{}")
                        if http_status == 200 and cbody.get("code") == 0:
                            got = (cbody.get("data") or {}).get("credit") or \
                                  travel["reward_credit"]
                            travel["auto_log"].append("已领取旅行积分 %s" % got)
                        else:
                            travel["auto_log"].append("领取旅行积分失败: %s"
                                                      % json.dumps(cbody, ensure_ascii=False)[:120])
                    if tdata.get("state") == "idle" and not tdata.get("daily_limit_reached"):
                        loc_id, loc_name = _pick_location(client, channel)
                        payload = (json.dumps({"location_id": loc_id}).encode()
                                   if loc_id is not None else b"{}")
                        http_status, dbody = _api(client, channel, "POST",
                                                  PATH_TRAVEL_DEPART, payload)
                        if http_status == 200 and dbody.get("code") == 0:
                            ddata = dbody.get("data") or {}
                            dloc = ddata.get("location") or {}
                            travel["state"] = ddata.get("state") or "traveling"
                            travel["state_text"] = TRAVEL_STATE_TEXT.get(
                                travel["state"], "旅行中")
                            travel["location_name"] = dloc.get("name") or loc_name \
                                or travel["location_name"]
                            hours = dloc.get("duration_hours")
                            travel["auto_log"].append(
                                "已派遣 Buddy 去 %s%s"
                                % (travel["location_name"],
                                   "（约 %s 小时）" % hours if hours else ""))
                            arrive_at = ddata.get("arrive_at")
                            if travel["state"] == "traveling" and arrive_at:
                                remain_min = max(0, int(
                                    (arrive_at - ddata.get("server_now",
                                                           time.time())) / 60))
                                travel["remaining_text"] = "约 %d 分钟" % remain_min
                        else:
                            travel["auto_log"].append("派遣失败: %s"
                                                      % json.dumps(dbody, ensure_ascii=False)[:120])
                    elif tdata.get("state") == "idle" and tdata.get("daily_limit_reached"):
                        travel["auto_log"].append("今日派遣次数已用完，跳过派遣（正常）")
                else:
                    travel["available"] = False
                    travel["auto_log"].append("旅行状态未能获取（HTTP %s）" % http_status)
            except Exception as t_err:
                travel["available"] = False
                travel["auto_log"].append("旅行流程异常: %s" % str(t_err)[:150])
            result["travel"] = travel
        if result["msg"] == "" and result["travel"]:
            result["msg"] = "签到状态: %s" % result.get("action")
        return result
    finally:
        client.close()


def main():
    no_travel = "--no-travel" in sys.argv
    try:
        result = run(no_travel=no_travel)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    except Exception as err:
        print(json.dumps({"status": "error", "action": None,
                          "msg": str(err)[:300]}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
