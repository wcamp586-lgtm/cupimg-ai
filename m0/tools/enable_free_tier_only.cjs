#!/usr/bin/env node
/**
 * 仅对本项目使用的两个模型开启「免费额度用完即停」，避免误扣费。
 * 不做批量修改（账号上还有其他云资源，最小影响面）。
 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");
const URL = "https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota";
const MODELS = ["qwen3-vl-plus", "qwen3.7-plus"];

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE, viewport: { width: 1440, height: 950 }, locale: "zh-CN",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4000);
    for (const model of MODELS) {
      const box = page.locator("input[placeholder='请输入模型 code']").first();
      await box.fill(model);
      await page.waitForTimeout(2200);
      const row = page.locator("tr[data-row-key]").filter({ hasText: model }).first();
      if (!(await row.count())) {
        console.log(`${model}: ROW_NOT_FOUND`);
        continue;
      }
      const sw = row.locator("[role=switch]").first();
      const before = await sw.getAttribute("aria-checked").catch(() => "unknown");
      console.log(`${model}: switch_before=${before}`);
      if (before === "true" || before === "1") continue;
      await sw.click({ timeout: 8000 }).catch((e) => console.log(`${model}: click err`, String(e).slice(0, 120)));
      await page.waitForTimeout(1500);
      // 可能出现的二次确认（仅接受「确定/确认/开启」，绝不点协议或付费类按钮）
      const confirm = page.getByRole("button", { name: /^(确定|确认|开启)$/ }).last();
      if (await confirm.count().catch(() => 0)) {
        const label = (await confirm.innerText().catch(() => "")) || "";
        console.log(`${model}: confirm-dialog button=${label}`);
        await confirm.click({ timeout: 6000 }).catch(() => {});
        await page.waitForTimeout(1500);
      }
      const after = await sw.getAttribute("aria-checked").catch(() => "unknown");
      console.log(`${model}: switch_after=${after}`);
    }
    // 刷新后复核真实持久化状态
    await page.reload({ waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4000);
    for (const model of MODELS) {
      await page.locator("input[placeholder='请输入模型 code']").first().fill(model);
      await page.waitForTimeout(2000);
      const row = page.locator("tr[data-row-key]").filter({ hasText: model }).first();
      const text = ((await row.innerText().catch(() => "")) || "").replace(/\s+/g, " ");
      console.log(`VERIFY ${model}: ${text.slice(0, 160)}`);
    }
    await page.screenshot({ path: path.join(OUT, "quota_switch_result.png") }).catch(() => {});
    console.log("SHOT: m0/out/login/quota_switch_result.png");
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
  }
  await browser.close();
})();
