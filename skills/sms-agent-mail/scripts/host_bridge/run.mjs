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
  skill_version: "1.5.1",
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

// webmail：优先取详情；取不到时按配置决定是否降级为正则兜底
async function fetchWebmailMessages(task, cfg) {
  let page = null;
  for (const t of await task.tabs()) {
    if (t.url && t.url.includes("agent.qq.com")) { page = t.page; break; }
  }
  if (!page) page = await task.newPage();
  await page.goto(cfg.webmail.list_url);

  if (cfg.webmail.row_selector) {
    await page.waitForSelector(cfg.webmail.row_selector, { state: "visible", timeout: 8000 });
  } else {
    await sleep(2500);
  }

  const view = await page.evaluate((selector) => {
    const text = document.body ? document.body.innerText : "";
    if (/扫码登录|请登录|登录后查看/.test(text) && !/验证码/.test(text)) {
      return { state: "not_logged_in" };
    }
    if (selector) {
      const row = document.querySelector(selector);
      if (row) {
        const detail = document.querySelector("[data-mail-body]");
        if (detail) {
          return {
            state: "detail",
            message: {
              from: (row.getAttribute("data-from") || ""),
              to: (row.getAttribute("data-to") || ""),
              subject: (row.getAttribute("data-subject") || ""),
              body: detail.innerText || "",
              body_format: "text",
              created_at: row.getAttribute("data-created-at") || null,
            },
          };
        }
        return { state: "list_only", preview: row.innerText || "" };
      }
    }
    return { state: "list_only", preview: text };
  }, cfg.webmail.row_selector || null);

  if (view.state === "not_logged_in") throw problem("webmail_not_logged_in");
  if (view.state === "detail" && view.message && view.message.from && view.message.body) {
    return { verifiedSource: true, messages: [view.message] };
  }
  if (!cfg.webmail.allow_regex_fallback) throw problem("webmail_detail_unavailable");
  return { verifiedSource: false, preview: view.preview || "" };
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
      const found = await fetchWebmailMessages(task, cfg);
      if (found.verifiedSource) {
        const message = found.messages[0];
        const codes = extractCode(message.body);
        if (codes.length === 1) {
          const verdict = await gateMessage(python, skillDir, cfg, message, after, before);
          if (verdict.verdict === "pass") {
            report.message_verified = true;
            report.code_source = "verified";
            return { code: codes[0], length: codes[0].length };
          }
          report.warnings.push(...(verdict.blockers || []).slice(0, 3));
        }
      } else {
        const codes = extractCode(found.preview);
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
