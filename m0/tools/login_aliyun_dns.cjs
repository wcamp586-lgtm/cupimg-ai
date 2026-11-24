/**
 * 阿里云「持有主域名的账号」扫码登录守护。
 * 与百炼登录态分开保存（aliyun_dns_state.json），不覆盖 .secrets/aliyun_state.json。
 * 二维码自动刷新并放大贴出；只有出现真实认证 cookie + 二维码消失 + 运行 > 5s 才算成功。
 * 只读：不点协议、不买域名、不修改任何解析记录。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "out", "aliyun_dns_login");
const QR_BIG = path.join(OUT, "qr_big.png");
const STATUS = path.join(OUT, "status.json");
const STATE = path.join(ROOT, ".secrets", "aliyun_dns_state.json");
const TIMEOUT_MS = 30 * 60 * 1000;
const START = "https://dns.console.aliyun.com/";

fs.mkdirSync(OUT, { recursive: true });
for (const f of [STATUS, STATE]) { try { if (fs.existsSync(f)) fs.unlinkSync(f); } catch (_) {} }

function setStatus(o) {
  fs.writeFileSync(STATUS, JSON.stringify({ ...o, ts: new Date().toISOString() }, null, 2), "utf-8");
}
function log(...a) { console.log("[dns-login]", ...a); }
const AUTH_COOKIE = /^(login_aliyunid|aliyun_choice|havana_lgc_token|havana_lgc_exp|havana_sdk_sso)$/i;

(async () => {
  let browser;
  try {
    browser = await chromium.launch({
      headless: false,
      args: ["--no-sandbox", "--window-size=1400,950", "--window-position=50,30"],
    });
    const ctx = await browser.newContext({
      viewport: { width: 1360, height: 900 }, locale: "zh-CN", deviceScaleFactor: 3,
    });
    const page = await ctx.newPage();
    setStatus({ phase: "opening", note: "正在打开阿里云登录页（请用持有主域名的账号扫码）" });
    await page.goto(START, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(3000);

    // 有些入口直接展示二维码，有些需要先点「登录」
    let qr = null;
    for (let i = 0; i < 24; i++) {
      for (const f of page.frames()) {
        const loc = f.locator("img.alipay-qrcode, img[class*='qrcode'], canvas[class*='qrcode']");
        if (await loc.count().catch(() => 0)) { qr = loc.first(); break; }
      }
      if (qr) break;
      if (i === 4) {
        await page.getByText("登录", { exact: true }).first().click({ timeout: 5000 }).catch(() => {});
      }
      await page.waitForTimeout(600);
    }
    if (!qr) throw new Error("未找到二维码元素（登录页结构可能变化）");

    let lastSrc = "", version = 0;
    async function refreshQr() {
      const src = await qr.getAttribute("src").catch(() => null);
      if (src && src !== lastSrc) lastSrc = src;
      else if (version > 0) return false;
      await qr.screenshot({ path: QR_BIG, timeout: 8000 }).catch(() => {});
      version++;
      return true;
    }
    await refreshQr();
    setStatus({ phase: "waiting_for_scan", qr: QR_BIG, qr_version: version,
                note: "请用【持有主域名的那个阿里云账号】扫码并在手机确认" });
    log("QR ready, version=", version);

    const started = Date.now();
    let ok = false;
    while (Date.now() - started < TIMEOUT_MS) {
      await page.waitForTimeout(2000);
      try {
        if (await refreshQr()) log("QR refreshed v" + version);
        const cookies = await ctx.cookies().catch(() => []);
        const names = cookies.map(c => c.name);
        const hasAuth = names.some(n => AUTH_COOKIE.test(n));
        const qrGone = (await qr.count().catch(() => 0)) === 0;
        const elapsed = Date.now() - started;
        setStatus({ phase: "waiting_for_scan", qr: QR_BIG, qr_version: version,
                    has_auth_cookie: hasAuth, elapsed_s: Math.round(elapsed / 1000),
                    note: "请用【持有主域名的那个阿里云账号】扫码并在手机确认" });
        if (elapsed > 5000 && hasAuth && qrGone) {
          await page.waitForTimeout(2500);
          await ctx.storageState({ path: STATE });
          ok = true;
          setStatus({ phase: "logged_in", state: STATE, url: page.url(),
                      elapsed_s: Math.round(elapsed / 1000),
                      note: "登录成功，登录态已保存到本机（独立于百炼账号）" });
          log("LOGIN OK");
          break;
        }
      } catch (e) { log("poll ignore:", String(e).slice(0, 100)); }
    }
    if (!ok) setStatus({ phase: "timeout", note: "30 分钟内未完成登录，可重新运行生成新二维码" });
  } catch (e) {
    setStatus({ phase: "error", note: String(e).slice(0, 300) });
    log("ERROR:", String(e).slice(0, 300));
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
})();
