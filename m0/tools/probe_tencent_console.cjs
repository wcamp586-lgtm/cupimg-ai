/**
 * 只读探测腾讯云控制台：CVM 实例（公网 IP / 地域 / 规格）、DNS 域名、安全组。
 * 绝不点击任何写操作按钮、不购买、不修改配置。
 * 捕获控制台自身发出的只读 JSON 响应，辅助拿到表格里没有的字段。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "tencent_state.json");
const OUT = path.join(ROOT, "m0", "out", "tencent");
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE,
    viewport: { width: 1500, height: 1000 },
    locale: "zh-CN",
  });
  const page = await ctx.newPage();
  const hits = [];
  page.on("response", async (r) => {
    const u = r.url();
    const ct = r.headers()["content-type"] || "";
    if (!/json/i.test(ct)) return;
    if (!/Describe|Instance|Domain|Record|Security|capi|cgi/i.test(u)) return;
    try {
      const t = await r.text();
      hits.push({ url: u.slice(0, 220), status: r.status(), body: t.slice(0, 4000) });
    } catch (_) {}
  });

  // 用户明确：服务器是轻量应用服务器 Lighthouse，不是 CVM。
  const targets = [
    ["lighthouse", "https://console.cloud.tencent.com/lighthouse/instance"],
    ["lh_firewall", "https://console.cloud.tencent.com/lighthouse/firewall"],
    ["lh_detail", "https://console.cloud.tencent.com/lighthouse"],
  ];
  for (const [name, url] of targets) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForTimeout(8000);
      const body = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      console.log("=== " + name + " | FINAL_URL: " + page.url());
      console.log("BODY: " + body.slice(0, 1400));
      await page.screenshot({ path: path.join(OUT, "console_" + name + ".png") });
    } catch (e) {
      console.log("=== " + name + " ERR: " + String(e).slice(0, 200));
    }
  }
  fs.writeFileSync(path.join(OUT, "api_hits.json"), JSON.stringify(hits, null, 2), "utf-8");
  console.log("API_HITS=" + hits.length);
  for (const h of hits.slice(0, 12)) console.log("HIT:", h.status, h.url);
  await browser.close();
})();
