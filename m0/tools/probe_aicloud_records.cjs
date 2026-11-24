/**
 * 只读查看 aicloud.plus 现有解析记录，确认 cupimg 子域未占用。
 * 不点击「添加记录 / 修改 / 删除 / 提交」。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "aliyun_dns_state.json");
const OUT = path.join(ROOT, "m0", "out", "aliyun_dns");
const DOMAIN = "aicloud.plus";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ storageState: STATE,
    viewport: { width: 1500, height: 1000 }, locale: "zh-CN" });
  const page = await ctx.newPage();
  const hits = [];
  page.on("response", async (r) => {
    const u = r.url();
    if (!/json/i.test(r.headers()["content-type"] || "")) return;
    if (!/Record|Domain|api\.json/i.test(u)) return;
    try {
      const t = await r.text();
      if (/RR|Value|Type|DomainName|records/i.test(t))
        hits.push({ url: u.slice(0, 200), status: r.status(), body: t.slice(0, 8000) });
    } catch (_) {}
  });

  await page.goto("https://dnsnext.console.aliyun.com/authoritative/domains",
                  { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(8000);
  // 点该域名行的「解析设置」
  const row = page.locator("tr", { hasText: DOMAIN }).first();
  console.log("ROW_COUNT:", await row.count().catch(() => 0));
  if (await row.count().catch(() => 0)) {
    const link = row.getByText("解析设置", { exact: true });
    if (await link.count().catch(() => 0)) await link.click({ timeout: 8000 }).catch(() => {});
    else await page.getByText(DOMAIN, { exact: true }).first().click({ timeout: 8000 }).catch(() => {});
  } else {
    await page.getByText(DOMAIN, { exact: true }).first().click({ timeout: 8000 }).catch(() => {});
  }
  await page.waitForTimeout(8000);
  const p = ctx.pages()[ctx.pages().length - 1];
  console.log("FINAL_URL:", p.url());
  const body = ((await p.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  console.log("BODY:", body.slice(0, 2000));
  await p.screenshot({ path: path.join(OUT, "aicloud_records.png") });
  fs.writeFileSync(path.join(OUT, "aicloud_record_hits.json"),
                   JSON.stringify(hits, null, 2), "utf-8");
  console.log("HITS:", hits.length);
  for (const h of hits.slice(0, 6)) console.log("HIT:", h.status, h.url.slice(0, 130));
  await browser.close();
})();
