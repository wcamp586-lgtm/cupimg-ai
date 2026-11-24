/**
 * 只读探测首尔轻量应用服务器详情：实例 ID、地域、镜像、防火墙规则、SSH 密钥。
 * 不点击任何「新建/修改/删除/购买」按钮。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "tencent_state.json");
const OUT = path.join(ROOT, "m0", "out", "tencent");
const TARGET_IP = "101.33.74.41";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ storageState: STATE,
    viewport: { width: 1500, height: 1000 }, locale: "zh-CN" });
  const page = await ctx.newPage();
  const hits = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (!/json/i.test(r.headers()["content-type"] || "")) return;
    if (!/Firewall|Instance|KeyPair|Lighthouse|capi|cgi/i.test(u)) return;
    try {
      const t = await r.text();
      if (/101\.33\.74\.41|Firewall|InstanceId|Ubuntu/i.test(t))
        hits.push({ url: u.slice(0, 200), status: r.status(), body: t.slice(0, 6000) });
    } catch (_) {}
  });

  await page.goto("https://console.cloud.tencent.com/lighthouse/instance",
                  { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(9000);
  console.log("LIST_URL:", page.url());

  // 点开首尔那台实例的卡片/名称，进入详情页
  const candidates = ["Ubuntu-a3xa", TARGET_IP];
  let clicked = false;
  for (const c of candidates) {
    const loc = page.getByText(c, { exact: false }).first();
    if (await loc.count().catch(() => 0)) {
      await loc.click({ timeout: 8000 }).catch((e) => console.log("click err", String(e).slice(0, 100)));
      clicked = true;
      break;
    }
  }
  console.log("CLICKED:", clicked);
  await page.waitForTimeout(9000);
  const pages = ctx.pages();
  const p = pages[pages.length - 1];
  console.log("DETAIL_URL:", p.url());
  const body = ((await p.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  console.log("DETAIL_BODY:", body.slice(0, 2200));
  await p.screenshot({ path: path.join(OUT, "lighthouse_detail.png") });

  // 再尝试直接访问防火墙标签页（只读）
  const m = p.url().match(/[?&]id=(lhins-[a-z0-9]+)/i);
  if (m) {
    const fw = "https://console.cloud.tencent.com/lighthouse/instance/detail?rid=18&id=" + m[1] + "&tab=firewall";
    await p.goto(fw, { waitUntil: "domcontentloaded", timeout: 45000 });
    await p.waitForTimeout(7000);
    const fb = ((await p.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    console.log("FIREWALL_URL:", p.url());
    console.log("FIREWALL_BODY:", fb.slice(0, 1400));
    await p.screenshot({ path: path.join(OUT, "lighthouse_firewall.png") });
  } else {
    console.log("INSTANCE_ID: not found in URL");
  }
  fs.writeFileSync(path.join(OUT, "lighthouse_api_hits.json"),
                   JSON.stringify(hits, null, 2), "utf-8");
  console.log("HITS:", hits.length);
  for (const h of hits.slice(0, 8)) console.log("HIT:", h.status, h.url.slice(0, 130));
  await browser.close();
})();
