/**
 * 打开 OrcaTerm 免密登录会话，展示微信 MFA 二维码，等待用户扫码。
 * 浏览器保持存活并开启 CDP 9222，扫码成功后由后续脚本复用同一会话执行命令。
 * 本脚本只做：打开页面、截二维码、轮询 MFA 状态；不输入任何命令、不修改实例配置。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const OUT = path.join(ROOT, "m0", "out", "orcaterm");
const STATE = path.join(ROOT, "m0", ".secrets", "tencent_state.json");
const SESSION = path.join(ROOT, "m0", ".secrets", "orcaterm_state.json");
const STATUS = path.join(OUT, "status.json");
const DETAIL = "https://console.cloud.tencent.com/lighthouse/instance/detail?rid=18&id=lhins-4er2ovz2";
const TIMEOUT_MS = 30 * 60 * 1000;

fs.mkdirSync(OUT, { recursive: true });
function setStatus(o) {
  fs.writeFileSync(STATUS, JSON.stringify({ ...o, ts: new Date().toISOString() }, null, 2), "utf-8");
}
function log(...a) { console.log(new Date().toISOString().slice(11, 19), ...a); }

(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: false,
      args: ["--no-sandbox", "--window-size=1500,1000", "--window-position=40,30",
             "--remote-debugging-port=9222", "--remote-allow-origins=*"],
    });
    const ctx = await browser.newContext({ storageState: STATE,
      viewport: { width: 1500, height: 940 }, locale: "zh-CN" });
    const page = await ctx.newPage();
    await page.goto(DETAIL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(7000);
    await page.getByText("登录", { exact: true }).first().click({ timeout: 10000 });
    await page.waitForTimeout(7000);
    const pages = ctx.pages();
    const term = pages[pages.length - 1];
    log("orcaterm url:", term.url());
    if (!/orcaterm/.test(term.url())) throw new Error("未打开 OrcaTerm");

    // 优先切换成普通二维码（比小程序码更好扫）
    const switcher = term.getByText("切换成普通二维码", { exact: false }).first();
    if (await switcher.count().catch(() => 0)) {
      await switcher.click({ timeout: 5000 }).catch(() => {});
      await term.waitForTimeout(2500);
      log("switched to normal QR");
    }

    // 定位二维码元素并截图
    let saved = false;
    for (const f of term.frames()) {
      const els = await f.locator("img, canvas, svg").all().catch(() => []);
      for (const el of els) {
        try {
          const box = await el.boundingBox();
          if (!box || box.width < 110 || box.width > 380 || box.height < 110) continue;
          const info = await el.evaluate((e) => ({ tag: e.tagName,
            cls: String(e.className || "").slice(0, 60), src: (e.src || "").slice(0, 90) }));
          await el.screenshot({ path: path.join(OUT, "mfa_qr_raw.png"), timeout: 6000 });
          fs.writeFileSync(path.join(OUT, "mfa_qr_meta.json"), JSON.stringify({ ...info, box }, null, 2));
          saved = true;
          log("MFA QR captured:", JSON.stringify(info));
          break;
        } catch (_) {}
      }
      if (saved) break;
    }
    await term.screenshot({ path: path.join(OUT, "orcaterm_full.png") });
    setStatus({ phase: "waiting_mfa", qr_captured: saved,
                note: "请用微信扫 MFA 二维码完成身份验证（这是最后一次扫码）" });

    const started = Date.now();
    let passed = false;
    while (Date.now() - started < TIMEOUT_MS) {
      await term.waitForTimeout(3000);
      try {
        const body = ((await term.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
        const mfaGone = !/扫码验证身份|身份验证|MFA 是什么/.test(body);
        const connected = /已连接|Connected|ubuntu@|Welcome to Ubuntu|root@/i.test(body);
        const elapsed = Date.now() - started;
        if (Math.floor(elapsed / 3000) % 4 === 0) {
          await term.screenshot({ path: path.join(OUT, "current.png") }).catch(() => {});
        }
        setStatus({ phase: passed ? "mfa_ok" : "waiting_mfa",
                    elapsed_s: Math.round(elapsed / 1000), mfa_gone: mfaGone,
                    connected: connected, qr_captured: saved,
                    note: passed ? "MFA 已通过，浏览器保持存活等待 CDP 操作" : "等待微信扫码 MFA" });
        if (!passed && mfaGone && elapsed > 12000) {
          passed = true;
          await ctx.storageState({ path: SESSION }).catch(() => {});
          log("MFA PASSED, keeping browser alive for CDP");
          setStatus({ phase: "mfa_ok", elapsed_s: Math.round(elapsed / 1000),
                      note: "MFA 已通过，浏览器/CDP 9222 保持存活，可执行部署命令" });
        }
        // MFA 通过后继续保活 8 分钟，供后续脚本连入
        if (passed && elapsed > 8 * 60 * 1000) break;
      } catch (e) { log("poll ignore", String(e).slice(0, 90)); }
    }
    if (!passed) setStatus({ phase: "timeout", note: "30 分钟内未完成 MFA，会话已关闭" });
  } catch (e) {
    log("FATAL:", String(e).slice(0, 250));
    setStatus({ phase: "error", note: String(e).slice(0, 250) });
  } finally {
    // 保持浏览器存活由 while 循环控制；异常时才关闭
    if (browser) await browser.close().catch(() => {});
  }
})();
