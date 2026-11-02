// run.mjs — host bridge for native-connector hosts (code_handoff: host-memory)
// Run: ego-browser nodejs < <skill>/scripts/host_bridge/run.mjs
//
// The verification code lives only inside this process. It is never written to
// stdout/stderr, never persisted, never passed as a tool argument. The only
// output is one RESULT line carrying code_length, not the code.

const DEFAULT_SKILL_DIR = "/Users/songhonglei/.workbuddy/skills/sms-agent-mail";
const DEFAULT_CONFIG = "/Users/songhonglei/.local/share/sms-agent-mail/bridge/config.json";

const fs = await import("node:fs/promises");
const path = await import("node:path");
const { execFile } = await import("node:child_process");
const { promisify } = await import("node:util");
const execFileAsync = promisify(execFile);

const report = {
  skill_version: "1.5.0",
  executor: "ego-browser-host-bridge",
  code_handoff: "host-memory",
  identity_matched: false,
  mail_source: null,
  code_read: false,
  code_length: null,
  polls: 0,
  send_requested: false,
  submit_attempted: false,
  login_state: "unknown",
  blocker: null,
};

const finish = () => console.log("RESULT " + JSON.stringify(report));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function rawConfig(configPath) {
  try {
    return JSON.parse(await fs.readFile(configPath, "utf8"));
  } catch {
    return null;
  }
}

async function resolveConfig(configPath, python) {
  const check = path.join(DEFAULT_SKILL_DIR, "scripts", "host_bridge", "config_check.py");
  const { stdout } = await execFileAsync(python, [check, "--config", configPath], {
    timeout: 20000, maxBuffer: 512 * 1024,
  });
  const parsed = JSON.parse(stdout.trim());
  if (!parsed.ok) throw new Error("config_invalid:" + parsed.reason);
  return parsed.resolved;
}

// ---------------- mail adapters ----------------

async function readFromImap(cfg, python) {
  const reader = path.join(DEFAULT_SKILL_DIR, "scripts", "host_bridge", "mail_imap.py");
  const { stdout } = await execFileAsync(python, [reader], {
    timeout: 30000,
    maxBuffer: 512 * 1024,
    env: { ...process.env, WB_BRIDGE_IMAP: JSON.stringify(cfg.imap) },
  });
  const parsed = JSON.parse(stdout.trim());
  if (!parsed.ok) throw new Error("imap_" + (parsed.reason || "unknown"));
  return { code: parsed.code, length: parsed.code_length, meta: { has_body_time: parsed.has_body_time } };
}

async function readFromWebmail(task, cfg) {
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

  const found = await page.evaluate(() => {
    const text = document.body ? document.body.innerText : "";
    if (/扫码登录|请登录|登录后查看/.test(text) && !/验证码/.test(text)) {
      return { reason: "not_logged_in" };
    }
    const lines = text.split(/\n+/).filter((l) => l.trim());
    const hits = [];
    for (const line of lines) {
      if (!/验证码|校验码|动态码/.test(line)) continue;
      const m = line.match(/(?<!\d)(\d{4,8})(?!\d)/);
      if (m) hits.push(m[1]);
    }
    if (!hits.length) return { reason: "code_not_found" };
    const uniq = [...new Set(hits)];
    if (uniq.length !== 1) return { reason: "multiple_candidates" };
    return { code: uniq[0], length: uniq[0].length };
  });

  if (!found.code) throw new Error("webmail_" + (found.reason || "unknown"));
  return { code: found.code, length: found.length, meta: {} };
}

async function waitForCode(task, cfg, python) {
  const deadline = Date.now() + cfg.code_wait_seconds * 1000;
  const interval = cfg.poll_interval_seconds * 1000;
  let lastReason = "no_attempt";
  while (Date.now() < deadline) {
    report.polls += 1;
    try {
      return cfg.mail_source === "webmail"
        ? await readFromWebmail(task, cfg)
        : await readFromImap(cfg, python);
    } catch (err) {
      lastReason = String(err.message || err);
      if (lastReason.includes("not_logged_in")) throw err; // 登录态问题，重试无用
    }
    await sleep(Math.min(interval, Math.max(0, deadline - Date.now())));
  }
  throw new Error("code_not_found_before_deadline:" + lastReason.slice(0, 40));
}

// ---------------- page actions ----------------

async function requestCode(task, cfg) {
  const page = await task.newPage();
  await page.goto(cfg.target.url);
  await page.waitForSelector(cfg.target.phone_selector, { state: "visible", timeout: 15000 });
  await page.fill(cfg.target.phone_selector, cfg.target.phone);
  if (cfg.target.agree_selector) await page.click(cfg.target.agree_selector);
  report.send_requested = true;                // 点击可能已到站，先记事实
  await page.click(cfg.target.send_selector);  // 本任务唯一一次发码
  await page.waitForSelector(cfg.target.code_selector, { state: "visible", timeout: 15000 });
  return page;
}

async function submitCode(page, cfg, code) {
  await page.fill(cfg.target.code_selector, code);
  report.submit_attempted = true;
  await page.click(cfg.target.submit_selector);
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
  const raw = await rawConfig(DEFAULT_CONFIG);
  const python = (raw && raw.python) || "/usr/bin/python3";

  if (raw && raw.self_test) {
    const task = await taskSpace(raw.task_space || "host bridge self test");
    await selfTest(task);
  } else {
    const cfg = await resolveConfig(DEFAULT_CONFIG, python);
    report.mail_source = cfg.mail_source;
    const task = await taskSpace(cfg.task_space);

    if (raw && raw.mail_only) {
      const picked = await waitForCode(task, cfg, python);
      report.code_read = true;
      report.code_length = picked.length;
      Object.assign(report, picked.meta || {});
      report.login_state = "not_attempted";
      picked.code = null;
    } else {
      const page = await requestCode(task, cfg);
      const picked = await waitForCode(task, cfg, python);
      report.code_read = true;
      report.code_length = picked.length;
      Object.assign(report, picked.meta || {});
      await submitCode(page, cfg, picked.code);
      picked.code = null;
    }
  }
} catch (err) {
  report.blocker = String(err.message || err).slice(0, 100);
  report.login_state = "blocked";
}

finish();
