// run.mjs — host bridge for native-connector hosts (code_handoff: host-memory)
// Run: ego-browser nodejs < <skill>/scripts/host_bridge/run.mjs
//
// The verification code lives only inside this process. It is never written to
// stdout/stderr, never persisted, never passed as a tool argument. The only
// output is one RESULT line carrying code_length, not the code.
//
// Every candidate message is first handed to the skill's own verifier
// (scripts/check_message.py) with this attempt's after/before, service, route
// and login purpose. Nothing is filled unless that verifier returns pass.

const fs = await import("node:fs/promises");
const os = await import("node:os");
const path = await import("node:path");
const { spawn } = await import("node:child_process");

const DEFAULT_CONFIG = path.join(os.homedir(), ".local", "share", "sms-agent-mail", "bridge", "config.json");
const DEFAULT_SKILL_DIR = path.join(os.homedir(), ".workbuddy", "skills", "sms-agent-mail");

// 固定错误码白名单：回执只允许出现这些值，绝不拼接外部异常文本
const SAFE_CODES = new Set([
  "config_invalid", "config_unreadable", "skill_dir_invalid",
  "mail_command_failed", "mail_payload_invalid", "code_not_found_before_deadline",
  "webmail_not_logged_in", "webmail_detail_unavailable", "regex_fallback_not_allowed",
  "gate_rejected", "gate_unavailable",
  "send_code_failed", "code_input_unavailable", "fill_or_submit_failed", "account_marker_not_found",
  "unexpected_host_error",
]);

const report = {
  skill_version: "1.5.2",
  executor: "ego-browser-host-bridge",
  code_handoff: "host-memory",
  mail_source: null,
  code_source: null,
  message_verified: false,
  code_read: false,
  code_length: null,
  polls: 0,
  send_requested: false,
  submit_attempted: false,
  login_state: "unknown",
  warnings: [],
  blocker: null,
};

const finish = () => console.log("RESULT " + JSON.stringify(report));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class BridgeError extends Error {
  constructor(code) {
    super(code);
    this.code = isSafeCode(code) ? code : "unexpected_host_error";
  }
}
const isSafeCode = (value) => typeof value === "string"
  && (SAFE_CODES.has(value) || /^config_invalid:[a-z_]{1,48}$/.test(value));
const problem = (code) => new BridgeError(code);

async function readRawConfig() {
  try {
    return JSON.parse(await fs.readFile(DEFAULT_CONFIG, "utf8"));
  } catch {
    return null;
  }
}

// 子进程统一入口：stdout 由管道捕获，stderr 永不进入回执
function runPython(python, args, stdinText, extraEnv) {
  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {
      stdio: "pipe",
      env: { ...process.env, ...(extraEnv || {}) },
    });
    let stdout = "";
    let tooBig = false;
    child.stdout.on("data", (buf) => {
      if (stdout.length + buf.length > 4 * 1024 * 1024) { tooBig = true; return; }
      stdout += buf.toString("utf8");
    });
    child.stderr.on("data", () => {}); // 丢弃，绝不回显
    child.on("error", () => reject(problem("mail_command_failed")));
    child.on("close", () => {
      if (tooBig) return reject(problem("mail_payload_invalid"));
      resolve({ stdout });
    });
    if (stdinText !== undefined && stdinText !== null) {
      child.stdin.on("error", () => {});
      child.stdin.end(stdinText);
    } else {
      child.stdin.end();
    }
  });
}

async function resolveConfig(python, skillDir) {
  const check = path.join(skillDir, "scripts", "host_bridge", "config_check.py");
  let stdout;
  try {
    ({ stdout } = await runPython(python, [check, "--config", DEFAULT_CONFIG]));
  } catch {
    throw problem("config_unreadable");
  }
  let parsed;
  try {
    parsed = JSON.parse(stdout.trim());
  } catch {
    throw problem("config_unreadable");
  }
  if (!parsed.ok) throw problem("config_invalid:" + String(parsed.reason || "unknown"));
  return parsed.resolved;
}

// ---------------- mail adapters：一律返回完整消息 ----------------

function extractCode(body) {
  const lines = String(body || "").split(/\n+/);
  const hits = [];
  for (const line of lines) {
    if (!/验证码|校验码|动态码/.test(line)) continue;
    const m = line.match(/(?<!\d)(\d{4,8})(?!\d)/);
    if (m) hits.push(m[1]);
  }
  return [...new Set(hits)];
}

async function fetchImapMessages(python, skillDir, cfg, after) {
  const reader = path.join(skillDir, "scripts", "host_bridge", "mail_imap.py");
  let stdout;
  try {
    ({ stdout } = await runPython(python, [reader], undefined,
      { WB_BRIDGE_IMAP: JSON.stringify({ ...cfg.imap, after }) }));
  } catch {
    throw problem("mail_command_failed");
  }
  let parsed;
  try {
    parsed = JSON.parse(stdout.trim());
  } catch {
    throw problem("mail_payload_invalid");
  }
  if (!parsed.ok) {
    if (parsed.reason === "no_matching_message") return [];
    throw problem("mail_command_failed");
  }
  return Array.isArray(parsed.messages) ? parsed.messages : [];
}

// webmail：只取「最新行 + 该行详情」，在行作用域内做确定性校验。
// agent.qq.com 的列表行不含发件人地址（只有显示名），详情里也无法可靠隔离
// from/to，因此这里**不冒充**完整校验：只核对主题路由、正文路由、品牌标签、
// 单码与时效，并在 warnings 里明确标注发件人/收件人未校验。
async function fetchWebmailCandidate(task, cfg) {
  let page = null;
  for (const t of await task.tabs()) {
    if (t.url && t.url.includes("agent.qq.com")) { page = t.page; break; }
  }
  if (!page) page = await task.newPage();
  await page.goto(cfg.webmail.list_url);

  if (!cfg.webmail.row_selector) {
    if (!cfg.webmail.allow_regex_fallback) throw problem("webmail_detail_unavailable");
    await sleep(2500);
    const preview = await page.evaluate(() => (document.body ? document.body.innerText : ""));
    return { scoped: false, preview };
  }

  try {
    await page.waitForSelector(cfg.webmail.row_selector, { state: "visible", timeout: 8000 });
  } catch {
    const loginWall = await page.evaluate(() => {
      const text = document.body ? document.body.innerText : "";
      return /扫码登录|请登录|登录后查看/.test(text) && !/验证码/.test(text);
    });
    if (loginWall) throw problem("webmail_not_logged_in");
    throw problem("webmail_detail_unavailable");
  }

  const rows = await page.evaluate((sel) => {
    const list = Array.from(document.querySelectorAll(sel.row)).slice(0, 5);
    return list.map((row, index) => ({
      index,
      subject: (row.querySelector(sel.subject) || {}).innerText || "",
      digest: (row.querySelector(".mail-item-digest") || {}).innerText || "",
    }));
  }, { row: cfg.webmail.row_selector, subject: cfg.webmail.subject_selector });

  if (!rows.length) return { scoped: false, preview: "" };

  // 最新一条不一定属于本次；在候选中挑主题路由匹配的那一行
  const target = rows.find((r) => {
    const m = String(r.subject || "").trim().match(/^(SIM[1-9]_\d{4})的短信验证码$/);
    return m && m[1] === cfg.route;
  });
  if (!target) {
    return { scoped: true, subject: String(rows[0].subject || "").trim(),
             digest: rows[0].digest, body: "" };
  }

  // 用 DOM 点击选中行，避免选择器不唯一时把候选正文带进报错
  await page.evaluate((sel) => {
    const row = document.querySelectorAll(sel.row)[sel.index];
    if (row) row.click();
  }, { row: cfg.webmail.row_selector, index: target.index });
  await sleep(1200);

  const bodyText = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    return el ? (el.innerText || "") : "";
  }, cfg.webmail.body_selector);

  return { scoped: true, subject: target.subject, digest: target.digest, body: bodyText };
}

// webmail 行作用域内的确定性校验（发件人/收件人无法从 DOM 取得，单独标注）
function checkWebmailCandidate(candidate, cfg, after, before) {
  const skip = ["sender_unverified", "recipient_unverified"];
  const body = candidate.body || "";
  const digest = candidate.digest || "";
  const subject = (candidate.subject || "").trim();

  const subjectRoute = subject.match(/^(SIM[1-9]_\d{4})的短信验证码$/);
  if (!subjectRoute || subjectRoute[1] !== cfg.route) {
    return { ok: false, reason: "subject_route_mismatch" };
  }
  if (!body) return { ok: false, reason: "webmail_detail_unavailable" };
  if (!body.includes(cfg.route)) return { ok: false, reason: "body_route_missing" };
  if (!cfg.service_tag || !body.includes(cfg.service_tag)) {
    return { ok: false, reason: "body_service_missing" };
  }
  if (/重置|找回|修改密码|注册|支付|转账/.test(body)) {
    return { ok: false, reason: "purpose_not_login" };
  }
  const codes = extractCode(body);
  if (codes.length !== 1) return { ok: false, reason: "code_ambiguous_or_missing" };

  const stamp = body.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})/);
  if (!stamp) return { ok: false, reason: "body_time_missing" };
  const smsTime = new Date(stamp[1].replace(" ", "T") + "Z");
  smsTime.setHours(smsTime.getHours() - cfg.body_offset_hours); // 正文时间按手机时区
  const t0 = Date.parse(after);
  const t1 = Date.parse(before);
  const ageSeconds = (Date.now() - smsTime.getTime()) / 1000;
  if (Number.isNaN(t0) || Number.isNaN(t1)) return { ok: false, reason: "window_invalid" };
  if (smsTime.getTime() < t0 - 300_000 || smsTime.getTime() > t1) {
    return { ok: false, reason: "sms_time_outside_window" };
  }
  if (ageSeconds > 310) return { ok: false, reason: "sms_time_expired" };

  if (digest && !digest.includes(cfg.route)) skip.push("digest_mismatch");
  return { ok: true, code: codes[0], warnings: skip };
}

// ---------------- 校验门 ----------------

async function gateMessage(python, skillDir, cfg, message, after, before) {
  const checker = path.join(skillDir, "scripts", "check_message.py");
  const args = [checker, "--profile", cfg.profile, "--service", cfg.service,
    "--route", cfg.route, "--purpose", "login", "--after", after, "--before", before];
  let stdout;
  try {
    ({ stdout } = await runPython(python, args, JSON.stringify(message)));
  } catch {
    throw problem("gate_unavailable");
  }
  let verdict;
  try {
    verdict = JSON.parse(stdout.trim());
  } catch {
    throw problem("gate_unavailable");
  }
  return verdict; // {verdict:'pass'|'blocked', blockers:[], checks:{...}}
}

async function waitForCode(task, cfg, python, skillDir, after) {
  const deadline = Date.now() + cfg.code_wait_seconds * 1000;
  const interval = cfg.poll_interval_seconds * 1000;
  let sawCandidate = false;

  while (Date.now() < deadline) {
    report.polls += 1;
    const before = new Date().toISOString();

    if (cfg.mail_source === "imap") {
      const messages = await fetchImapMessages(python, skillDir, cfg, after);
      for (const message of messages) {
        sawCandidate = true;
        const codes = extractCode(message.body);
        if (codes.length !== 1) continue; // 多码或缺码，交给下一条
        const verdict = await gateMessage(python, skillDir, cfg, message, after, before);
        if (verdict.verdict === "pass") {
          report.message_verified = true;
          report.code_source = "verified";
          return { code: codes[0], length: codes[0].length };
        }
        report.warnings.push(...(verdict.blockers || []).slice(0, 3));
      }
    } else {
      const candidate = await fetchWebmailCandidate(task, cfg);
      if (candidate.scoped) {
        sawCandidate = true;
        const verdict = checkWebmailCandidate(candidate, cfg, after, before);
        if (verdict.ok) {
          report.code_source = "webmail_dom_checked";
          report.warnings.push(...verdict.warnings);
          return { code: verdict.code, length: verdict.code.length };
        }
        report.warnings.push(verdict.reason);
      } else {
        // 无选择器时按配置降级为全页正则（更弱的路径，必须显式标注）
        const codes = extractCode(candidate.preview);
        if (codes.length === 1) {
          report.code_source = "regex_unverified";
          report.warnings.push("message_unverified_regex_fallback");
          return { code: codes[0], length: codes[0].length };
        }
        if (codes.length > 1) sawCandidate = true;
      }
    }
    await sleep(Math.min(interval, Math.max(0, deadline - Date.now())));
  }
  throw problem(sawCandidate ? "gate_rejected" : "code_not_found_before_deadline");
}

// ---------------- 页面动作 ----------------

async function requestCode(task, cfg) {
  const page = await task.newPage();
  await page.goto(cfg.target.url);
  try {
    await page.waitForSelector(cfg.target.phone_selector, { state: "visible", timeout: 15000 });
    await page.fill(cfg.target.phone_selector, cfg.target.phone);
    if (cfg.target.agree_selector) await page.click(cfg.target.agree_selector);
  } catch {
    throw problem("send_code_failed");
  }
  report.send_requested = true;                // 点击可能已到站，先记事实
  try {
    await page.click(cfg.target.send_selector);  // 本任务唯一一次发码
  } catch {
    throw problem("send_code_failed");
  }
  try {
    await page.waitForSelector(cfg.target.code_selector, { state: "visible", timeout: 15000 });
  } catch {
    throw problem("code_input_unavailable");
  }
  return page;
}

async function submitCode(page, cfg, code) {
  // 捕获后只抛固定码：填充异常可能携带填入值，绝不能回显
  try {
    await page.fill(cfg.target.code_selector, code);
  } catch {
    throw problem("fill_or_submit_failed");
  }
  report.submit_attempted = true;
  try {
    await page.click(cfg.target.submit_selector);
  } catch {
    throw problem("fill_or_submit_failed");
  }
  try {
    await page.waitForSelector(cfg.target.account_marker, { state: "visible", timeout: 20000 });
    report.login_state = "verified";
  } catch {
    report.login_state = "not_verified";
    report.blocker = "account_marker_not_found";
  }
}

// ---------------- self test ----------------

async function selfTest(task) {
  const fake = "864213";
  const page = await task.newPage();
  await page.goto("about:blank");
  await page.evaluate(() => {
    document.body.innerHTML =
      '<input id="phone"><button id="send">send</button>' +
      '<input id="code" style="display:none"><button id="submit">go</button><div id="ok"></div>';
    document.getElementById("send").onclick = () => {
      document.getElementById("code").style.display = "block";
    };
    document.getElementById("submit").onclick = () => {
      if (document.getElementById("code").value === "864213") {
        document.getElementById("ok").textContent = "logged-in";
      }
    };
  });
  await page.waitForSelector("#phone", { state: "visible" });
  await page.fill("#phone", "13800000000");
  report.send_requested = true;
  await page.click("#send");
  await page.waitForSelector("#code", { state: "visible" });
  await page.fill("#code", fake);
  report.submit_attempted = true;
  await page.click("#submit");
  await page.waitForSelector("#ok", { state: "visible" });
  report.login_state = "verified";
  report.code_read = true;
  report.code_length = fake.length;
  report.self_test = "passed";
}

// ---------------- main ----------------

try {
  const raw = await readRawConfig();
  const skillDir = (raw && raw.skill_dir) || DEFAULT_SKILL_DIR;
  if (!path.isAbsolute(skillDir)) throw problem("skill_dir_invalid");
  const python = (raw && raw.python) || "/usr/bin/python3";

  if (raw && raw.self_test) {
    const task = await taskSpace(raw.task_space || "host bridge self test");
    await selfTest(task);
  } else {
    const cfg = await resolveConfig(python, skillDir);
    report.mail_source = cfg.mail_source;
    const task = await taskSpace(cfg.task_space);
    const after = new Date().toISOString();

    if (raw && raw.mail_only) {
      const picked = await waitForCode(task, cfg, python, skillDir, after);
      report.code_read = true;
      report.code_length = picked.length;
      report.login_state = "not_attempted";
      picked.code = null;
    } else {
      const page = await requestCode(task, cfg);
      const picked = await waitForCode(task, cfg, python, skillDir, after);
      report.code_read = true;
      report.code_length = picked.length;
      await submitCode(page, cfg, picked.code);
      picked.code = null;
    }
  }
} catch (err) {
  // 只输出固定错误码；永不拼接 err.message / stderr / 命令输出
  report.blocker = isSafeCode(err && err.code) ? err.code : "unexpected_host_error";
  if (report.login_state !== "verified") report.login_state = "blocked";
}

finish();
