#!/usr/bin/env node
/**
 * 只读：用已保存的百炼登录态，检查「免费额度」页是否存在可白嫖的图像生成模型。
 * 目的：若百炼侧自带生图免费额度，可绕开尚未注册的 BytePlus，直接把 live 全链路跑通。
 * 不做任何点击开关、创建 Key、开通或购买操作。
 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");
const URL = "https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE, viewport: { width: 1500, height: 1000 }, locale: "zh-CN",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(5000);

    // 全表文本（含所有模型行）
    const rows = await page.locator("tr").allTextContents().catch(() => []);
    const clean = rows.map((r) => r.replace(/\s+/g, " ").trim()).filter(Boolean);
    console.log("ROW_COUNT:", clean.length);
    console.log("--- ALL ROWS ---");
    clean.slice(0, 80).forEach((r, i) => console.log(String(i).padStart(2, "0"), "|", r.slice(0, 220)));

    const imageHits = clean.filter((r) => /image|image-edit|wanx|wan2|flux|seedream|绘图|文生图|图像|图片|视频/i.test(r));
    console.log("--- IMAGE-RELATED ROWS ---");
    imageHits.slice(0, 40).forEach((r) => console.log("*", r.slice(0, 260)));

    // 再用搜索框逐个查常见生图模型
    const search = page.locator("input[placeholder*='模型'], input[placeholder*='搜索'], input[placeholder*='Code']").first();
    if (await search.count()) {
      for (const kw of ["qwen-image", "wanx", "wan2", "seedream", "flux"]) {
        await search.fill(kw).catch(() => {});
        await page.waitForTimeout(1800);
        const t = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
        const i = t.indexOf("模型 Code");
        console.log("SEARCH[" + kw + "]:", (i >= 0 ? t.slice(i, i + 420) : t.slice(0, 420)));
      }
    } else {
      console.log("SEARCH: no search input");
    }

    await page.screenshot({ path: path.join(OUT, "quota_all_models.png"), fullPage: true });
    console.log("SHOT: m0/out/login/quota_all_models.png");
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
  }
  await browser.close();
})();
