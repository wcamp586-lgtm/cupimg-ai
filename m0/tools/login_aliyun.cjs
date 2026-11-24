/**
 * 百炼扫码登录守护脚本（本机运行，会话不过早关闭）
 *
 *   node m0/tools/login_aliyun.cjs
 *
 * 1) 打开百炼控制台 → 点登录 → 定位 img.alipay-qrcode
 * 2) 把二维码放大截图到 out/login/aliyun_qr_big.png 供用户手机扫
 * 3) 保持浏览器会话存活，轮询登录态（最多 6 分钟）
 * 4) 登录成功后把 storageState 存到 .secrets/aliyun_state.json 供后续脚本复用
 *
 * 安全：只在本机保存登录态；不打印 cookie 内容；不接收账号密码。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "out", "login");
const QR_BIG = path.join(OUT, "aliyun_qr_big.png");
const QR_RAW = path.join(OUT, "aliyun_qr_raw.png");
const STATUS = path.join(OUT, "aliyun_status.json");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const TIMEOUT_MS = 6 * 60 * 1000;

function setStatus(obj) {
  fs.writeFileSync(STATUS, JSON.stringify({ ...obj, ts: new Date().toISOString() }, null, 2), "utf-8");
}
function log(...a) { console.log("[login]", ...a); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(path.dirname(STATE), { recursive: true });
  // 每轮从零开始，避免复用上一轮可能是匿名态的登录文件
  if (fs.existsSync(STATE)) fs.unlinkSync(STATE);
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
    // deviceScaleFactor=3 → 二维码元素截图约 432x432，手机容易识别
    const ctx = await browser.newContext({
      viewport: { width: 1360, height: 900 }, locale: "zh-CN", deviceScaleFactor: 3,
    });
    const page = await ctx.newPage();
    setStatus({ phase: "opening", note: "正在打开百炼登录页" });

    await page.goto("https://bailian.console.aliyun.com/", { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(2000);
    await page.getByText("登录", { exact: true }).first().click();

    let qr = null;
    for (let i = 0; i < 30; i++) {
      for (const f of page.frames()) {
        const loc = f.locator("img.alipay-qrcode");
        if (await loc.count().catch(() => 0)) { qr = loc.first(); break; }
      }
      if (qr) break;
      await page.waitForTimeout(500);
    }
    if (!qr) throw new Error("未找到登录二维码元素（页面结构可能变了）");

    let lastSrc = "";
    let version = 0;
    async function refreshQr() {
      const src = await qr.getAttribute("src").catch(() => null);
      if (!src || src === lastSrc) return false;
      lastSrc = src;
      if (src.startsWith("data:image")) {
        fs.writeFileSync(QR_RAW, Buffer.from(src.split(",")[1], "base64"));
      }
      await qr.screenshot({ path: QR_BIG });
      version++;
      log("二维码已生成/刷新, version=" + version);
      return true;
    }
    await refreshQr();
    setStatus({ phase: "waiting_for_scan", qr: QR_BIG, qr_version: version,
                note: "请用阿里云APP/支付宝/钉钉扫这张二维码，并在手机上确认登录" });

    const started = Date.now();
    let loggedIn = false;
    // 阿里云真正的认证 cookie；匿名态只有 JSESSIONID / XSRF-TOKEN / isg / tfstk 等
    const AUTH_COOKIE = /^(login_aliyunid|aliyun_choice|havana_lgc_token|havana_lgc_exp|havana_sdk_sso)$/i;
    while (Date.now() - started < TIMEOUT_MS) {
      await page.waitForTimeout(2000);
      try {
        if (await refreshQr()) {
          setStatus({ phase: "waiting_for_scan", qr: QR_BIG, qr_version: version,
                      note: "二维码已刷新，请扫最新版" });
        }
        const cookies = await ctx.cookies().catch(() => []);
        const names = cookies.map(c => c.name);
        const hasAuth = names.some(n => AUTH_COOKIE.test(n));
        const qrGone = (await qr.count().catch(() => 0)) === 0;
        const loginBtnGone = (await page.getByText("登录", { exact: true }).count().catch(() => 1)) === 0;
        const elapsed = Date.now() - started;
        // 三重校验：出现认证 cookie + 二维码/登录按钮消失 + 已运行 5 秒以上
        // （早期版本仅用主页面 body 文本判断，因登录框在 iframe 内而误判，已修正）
        if (elapsed > 5000 && hasAuth && (qrGone || loginBtnGone)) {
          await page.waitForTimeout(2000);
          await ctx.storageState({ path: STATE });
          loggedIn = true;
          setStatus({ phase: "logged_in", state: STATE, url: page.url(),
                      evidence: { hasAuth, qrGone, loginBtnGone, elapsed_ms: elapsed },
                      note: "登录成功，登录态已保存到本机" });
          log("登录成功，storageState 已保存");
          break;
        }
        setStatus({ phase: "waiting_for_scan", qr: QR_BIG, qr_version: version,
                    cookie_names: names, has_auth_cookie: hasAuth,
                    note: "请用阿里云APP/支付宝/钉钉扫二维码，并在手机上确认登录" });
      } catch (e) {
        log("轮询中忽略异常:", String(e).slice(0, 120));
      }
    }
    if (!loggedIn) setStatus({ phase: "timeout", note: "6 分钟内未检测到登录，可重新运行脚本生成新二维码" });
  } catch (e) {
    setStatus({ phase: "error", note: String(e).slice(0, 300) });
    log("ERROR:", String(e).slice(0, 300));
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
})();
