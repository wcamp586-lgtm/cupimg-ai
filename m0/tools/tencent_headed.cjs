/**
 * 腾讯云控制台可见窗口登录守护。
 * - 用户本人在窗口内扫码/登录，密码与验证码绝不经过对话。
 * - 每 3s 轮询：只有出现真实认证 cookie + 回到控制台页 + 运行超过 8s 才算登录。
 * - 登录态仅落本机 m0/.secrets/（已 gitignore）；匿名快照单独存 out/ 便于诊断。
 * - 不做任何写操作：不点协议、不动安全组、不改 DNS、不点付费按钮。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const OUT = path.join(ROOT, "m0", "out", "tencent");
const STATE = path.join(ROOT, "m0", ".secrets", "tencent_state.json");
const SNAPSHOT = path.join(OUT, "state_snapshot.json");
const STATUS = path.join(OUT, "tencent_status.json");
const START_URL = "https://console.cloud.tencent.com/";
const TIMEOUT_MS = 60 * 60 * 1000;

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(path.dirname(STATE), { recursive: true });
for (const f of [STATE, SNAPSHOT, STATUS]) {
  try { if (fs.existsSync(f)) fs.unlinkSync(f); } catch (_) {}
}

function log(...a) { console.log(new Date().toISOString().slice(11, 19), ...a); }
function setStatus(o) {
  try { fs.writeFileSync(STATUS, JSON.stringify({ ...o, updated_at: new Date().toISOString() }, null, 2), "utf-8"); } catch (_) {}
}

const AUTH_NAMES = /^(uin|skey|qcloud_uid|qcloud_csrf|loginType|intl|p_skey|pt4_token)$/i;
function authLike(cookies) {
  return cookies.filter((c) => AUTH_NAMES.test(c.name)).map((c) => c.name);
}
function looksLoggedIn(urls, cookies, elapsedMs) {
  const onConsole = urls.some((u) => /console\.cloud\.tencent\.com/.test(u) && !/\/login/i.test(u));
  const names = authLike(cookies);
  const hasStrong = names.some((n) => /^(skey|qcloud_uid|uin)$/i.test(n));
  return onConsole && hasStrong && cookies.length >= 4 && elapsedMs > 8000;
}

/** 尽力把登录二维码单独截成大图，方便用户手机直接扫 */
async function captureQr(ctx, pages) {
  try {
    for (const p of pages) {
      for (const f of p.frames()) {
        const els = await f.locator("img, canvas, svg").all().catch(() => []);
        for (const el of els) {
          try {
            const box = await el.boundingBox();
            if (!box || box.width < 90 || box.width > 420 || box.height < 90) continue;
            const info = await el.evaluate((e) => ({
              tag: e.tagName,
              cls: String(e.className || "").slice(0, 80),
              src: (e.src || "").slice(0, 100),
              id: String(e.id || "").slice(0, 60),
            }));
            const hint = (info.cls + " " + info.src + " " + info.id).toLowerCase();
            if (!/qr|code|barcode|wechat|wx/.test(hint)) continue;
            await el.screenshot({ path: path.join(OUT, "qr_raw.png"), timeout: 5000 });
            fs.writeFileSync(path.join(OUT, "qr_meta.json"), JSON.stringify({ ...info, box }, null, 2), "utf-8");
            return true;
          } catch (_) {}
        }
      }
    }
  } catch (_) {}
  return false;
}

(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: false,
      args: ["--no-sandbox", "--window-size=1500,1000", "--window-position=40,30"],
    });
    const ctx = await browser.newContext({
      viewport: { width: 1500, height: 940 },
      locale: "zh-CN",
    });
    const page = await ctx.newPage();
    await page.goto(START_URL, { waitUntil: "domcontentloaded", timeout: 60000 });
    try { await page.bringToFront(); } catch (_) {}
    log("headed window opened:", START_URL);
    setStatus({ phase: "waiting_for_user", note: "腾讯云控制台窗口已打开，请用户本人扫码/登录" });

    const started = Date.now();
    let done = false;
    let qrReady = false;
    while (Date.now() - started < TIMEOUT_MS) {
      await page.waitForTimeout(3000);
      try {
        const pages = ctx.pages();
        const urls = pages.map((p) => p.url());
        const cookies = await ctx.cookies();
        const elapsedMs = Date.now() - started;
        const names = authLike(cookies);

        if (!qrReady) qrReady = await captureQr(ctx, pages);
        if (Math.floor(elapsedMs / 3000) % 4 === 0) {
          await pages[pages.length - 1].screenshot({ path: path.join(OUT, "current.png"), timeout: 8000 }).catch(() => {});
        }
        // 匿名快照也留一份，超时仍能诊断（不写进 .secrets）
        await ctx.storageState({ path: SNAPSHOT }).catch(() => {});

        const ok = looksLoggedIn(urls, cookies, elapsedMs);
        setStatus({
          phase: ok ? "logged_in" : "waiting_for_user",
          elapsed_s: Math.round(elapsedMs / 1000),
          urls: urls.slice(-3),
          cookie_count: cookies.length,
          auth_cookie_names: [...new Set(names)],
          qr_ready: qrReady,
          note: ok ? "登录态已捕获" : "等待用户在可见窗口内扫码/登录（密码与验证码请本人在窗口输入）",
        });
        if (ok) {
          await page.waitForTimeout(2500);
          await ctx.storageState({ path: STATE });
          setStatus({
            phase: "logged_in",
            state: "m0/.secrets/tencent_state.json",
            elapsed_s: Math.round((Date.now() - started) / 1000),
            auth_cookie_names: [...new Set(names)],
            note: "登录成功，storageState 已保存到本机",
          });
          log("LOGIN OK, storageState saved");
          done = true;
          break;
        }
      } catch (e) {
        log("polling ignore:", String(e).slice(0, 120));
      }
    }
    if (!done) {
      await ctx.storageState({ path: SNAPSHOT }).catch(() => {});
      setStatus({ phase: "timeout", note: "60 分钟内未检测到登录态，窗口已关闭；可重新运行本脚本" });
      log("TIMEOUT");
    }
  } catch (e) {
    log("FATAL:", String(e).slice(0, 300));
    setStatus({ phase: "error", note: String(e).slice(0, 250) });
  } finally {
    try { if (browser) await browser.close(); } catch (_) {}
  }
})();
