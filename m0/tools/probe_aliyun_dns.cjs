/**
 * 只读探测阿里云云解析 DNS：复用百炼扫码留下的登录态，确认主域名列表与现有解析记录。
 * 若登录态失效（跳登录页），输出 NEED_LOGIN，由主流程另开可见窗口让用户登录。
 * 不做任何增删改。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
// 改用「持有主域名的账号」登录态（百炼那个账号下域名列表为空）
const STATE = path.join(ROOT, "m0", ".secrets", "aliyun_dns_state.json");
const OUT = path.join(ROOT, "m0", "out", "aliyun_dns");
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE,
    viewport: { width: 1440, height: 950 },
    locale: "zh-CN",
  });
  const page = await ctx.newPage();
  const hits = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (!/json/i.test(r.headers()["content-type"] || "")) return;
    if (!/domain|record|dns|Describe/i.test(u)) return;
    try { hits.push({ url: u.slice(0, 200), status: r.status(), body: (await r.text()).slice(0, 2500) }); }
    catch (_) {}
  });
  const urls = [
    ["dns", "https://dns.console.aliyun.com/"],
    ["domain", "https://dc.console.aliyun.com/"],
  ];
  for (const [name, url] of urls) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForTimeout(8000);
      const body = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      const needLogin = /请登录|立即登录|扫码登录|Sign in|账号登录/i.test(body) || /\/login/i.test(page.url());
      console.log("=== " + name + " | FINAL_URL: " + page.url());
      console.log("NEED_LOGIN=" + needLogin);
      console.log("BODY: " + body.slice(0, 1200));
      await page.screenshot({ path: path.join(OUT, "aliyun_" + name + ".png") });
    } catch (e) {
      console.log("=== " + name + " ERR: " + String(e).slice(0, 200));
    }
  }
  fs.writeFileSync(path.join(OUT, "api_hits.json"), JSON.stringify(hits, null, 2), "utf-8");
  console.log("API_HITS=" + hits.length);
  for (const h of hits.slice(0, 10)) console.log("HIT:", h.status, h.url);
  await browser.close();
})();
