#!/usr/bin/env node
/**
 * 有头可见窗口：由用户本人在窗口里完成 BytePlus 注册/登录（密码、验证码不经聊天）。
 * 脚本只轮询登录态，成功后把 storageState 存到本机 .secrets/。
 * 绝不代填密码、绝不代勾协议、绝不代填支付信息。
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "out", "byteplus");
const STATE = path.join(ROOT, ".secrets", "byteplus_state.json");
const STATUS = path.join(OUT, "byteplus_status.json");
const TIMEOUT_MS = 60 * 60 * 1000;
const START_URL = "https://console.byteplus.com/auth/signup?redirectURI=https%3A%2F%2Fconsole.byteplus.com%2Fhome";

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.dirname(STATE), { recursive: true });

function setStatus(obj) {
  fs.writeFileSync(STATUS, JSON.stringify({ ...obj, ts: new Date().toISOString() }, null, 2), "utf8");
}
const log = (...a) => console.log("[byteplus]", ...a);

function looksLoggedIn(urls, cookies, bodies, initialNames) {
  // 注意：未登录也能打开 console.byteplus.com/ark/... 概览页，所以单看 URL 会假阳性
  const onConsole = urls.some((u) => /console\.byteplus\.com/.test(u) && !/\/auth\//.test(u));
  const stillHasLogin = bodies.some((b) => /\bLog in\b|\bSign up\b/i.test(b));
  const newCookies = cookies.filter((c) => !initialNames.has(c.name));
  const authish = newCookies.filter((c) => /session|token|sid|auth|login|passport|uid|sso/i.test(c.name));
  return onConsole && !stillHasLogin && newCookies.length >= 2 && authish.length >= 1;
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: false,
      args: ["--no-sandbox", "--start-maximized", "--window-position=40,30"],
    });
    const ctx = await browser.newContext({ viewport: null, locale: "en-US" });
    const page = await ctx.newPage();
    await page.goto(START_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(3500);
    // 关掉挡住注册表单的 Cookie 同意弹窗（非敏感普通按钮）
    const reject = page.getByRole("button", { name: /^Reject all$/ }).first();
    if (await reject.count().catch(() => 0)) {
      await reject.click({ timeout: 5000 }).catch(() => {});
      log("cookie banner dismissed");
    }
    await page.bringToFront().catch(() => {});
    const initialNames = new Set((await ctx.cookies()).map((c) => c.name));
    setStatus({ phase: "waiting_for_user", note: "可见窗口已打开并置顶，Cookie 弹窗已关闭，请用户本人在窗口内注册/登录" });
    log("headed window opened:", START_URL);

    const started = Date.now();
    let done = false;
    while (Date.now() - started < TIMEOUT_MS) {
      await page.waitForTimeout(3000);
      try {
        const pages = ctx.pages();
        const urls = pages.map((p) => p.url());
        const cookies = (await ctx.cookies()).map((c) => ({ name: c.name, domain: c.domain }));
        const bodies = [];
        for (const q of pages) {
          bodies.push(((await q.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 500));
        }
        // 兜底：每轮都落盘登录态与进度图，即使判定超时也能拿最后状态实测，
        // 不会像第一版那样超时后两眼一抹黑（图片只存本地，不贴出）
        await ctx.storageState({ path: STATE }).catch(() => {});
        await pages[pages.length - 1].screenshot({ path: path.join(OUT, "current.png") }).catch(() => {});
        const ok = looksLoggedIn(urls, cookies, bodies, initialNames);
        setStatus({
          phase: ok ? "logged_in" : "waiting_for_user",
          on_console: urls.some((u) => /console\.byteplus\.com/.test(u)),
          auth_cookie: ok,
          cookie_count: cookies.length,
          new_cookie_count: cookies.filter((c) => !initialNames.has(c.name)).length,
          urls: urls.slice(-4),
          elapsed_s: Math.round((Date.now() - started) / 1000),
          note: ok ? "登录态已捕获" : "等待用户在可见窗口内完成注册/登录（密码与验证码请本人在窗口输入）",
        });
        if (ok && Date.now() - started > 8000) {
          await page.waitForTimeout(2500);
          await ctx.storageState({ path: STATE });
          setStatus({ phase: "logged_in", state: "m0/.secrets/byteplus_state.json", note: "登录成功，storageState 已保存" });
          log("LOGIN OK, storageState saved");
          done = true;
          break;
        }
      } catch (e) {
        log("poll ignore:", String(e).slice(0, 120));
      }
    }
    if (!done) {
      setStatus({ phase: "timeout", note: "60 分钟内未检测到登录态；登录态快照仍保存在 .secrets/byteplus_state.json，可实测核验" });
      log("TIMEOUT");
    }
    await browser.close();
  } catch (e) {
    setStatus({ phase: "error", note: String(e).slice(0, 240) });
    log("FATAL:", String(e).slice(0, 240));
    if (browser) await browser.close().catch(() => {});
    process.exit(1);
  }
})();
