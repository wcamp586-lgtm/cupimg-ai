#!/usr/bin/env node
/** 只读：查看免费额度页的批量设置弹窗、行内开关结构、搜索框，以及 qwen-plus 额度。 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");
const URL = "https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE, viewport: { width: 1440, height: 950 }, locale: "zh-CN",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4500);

    // 搜索框结构
    const inputs = await page.locator("input").evaluateAll((els) =>
      els.map((e) => ({ ph: e.placeholder || "", type: e.type, cls: String(e.className).slice(0, 60) }))
    ).catch(() => []);
    console.log("INPUTS:", JSON.stringify(inputs));

    // 行内开关结构（只看 qwen3-vl-plus 那一行）
    const row = page.locator("tr").filter({ hasText: "qwen3-vl-plus" }).first();
    if (await row.count()) {
      const html = (await row.evaluate((e) => e.outerHTML)).replace(/\s+/g, " ").slice(0, 1400);
      console.log("ROW_HTML:", html);
    } else {
      console.log("ROW_HTML: not found");
    }

    // 搜索 qwen-plus
    const search = page.locator("input[placeholder*='模型'], input[placeholder*='搜索'], input[placeholder*='Code']").first();
    if (await search.count()) {
      await search.fill("qwen-plus").catch(() => {});
      await page.waitForTimeout(2500);
      const t = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      const i = t.indexOf("模型 Code");
      console.log("SEARCH_RESULT:", t.slice(i, i + 500));
      await page.screenshot({ path: path.join(OUT, "quota_qwen_plus.png") });
    } else {
      console.log("SEARCH_RESULT: no search input");
    }

    // 打开批量设置弹窗（只开不看提交）
    await page.getByText("批量设置", { exact: true }).first().click({ timeout: 8000 }).catch((e) => console.log("batch click err", String(e).slice(0, 100)));
    await page.waitForTimeout(1800);
    const dialogs = await page.locator("[role=dialog], .next-dialog, .ant-modal").allTextContents().catch(() => []);
    console.log("DIALOG:", JSON.stringify(dialogs.map((d) => d.replace(/\s+/g, " ").slice(0, 500))));
    await page.screenshot({ path: path.join(OUT, "quota_batch_dialog.png") });
    console.log("SHOT: m0/out/login/quota_batch_dialog.png");
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
  }
  await browser.close();
})();
