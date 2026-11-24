#!/usr/bin/env node
/** 只读：确认 qwen-plus 免费额度状态 + 找到 API Key 管理页 URL（不创建 Key）。 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE, viewport: { width: 1440, height: 950 }, locale: "zh-CN",
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const p = await ctx.newPage();
  try {
    // A. qwen-plus 在「额度用尽或过期」里的状态
    await p.goto("https://bailian.console.aliyun.com/cn-beijing/costing-balance/free-quota", { waitUntil: "domcontentloaded", timeout: 45000 });
    await p.waitForTimeout(4000);
    const cards = await p.locator("body").innerText();
    console.log("CARDS:", cards.replace(/\s+/g, " ").slice(0, 260));
    const expiredCard = p.getByText(/额度用尽或过期模型/).first();
    await expiredCard.click({ timeout: 8000 }).catch((e) => console.log("card click err", String(e).slice(0, 100)));
    await p.waitForTimeout(2500);
    const s = p.locator("input[placeholder='请输入模型 code']").first();
    await s.fill("qwen-plus").catch(() => {});
    await p.waitForTimeout(2500);
    const t = ((await p.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    const i = t.indexOf("模型 Code");
    console.log("EXPIRED_FILTER_RESULT:", t.slice(i, i + 420));
    await p.screenshot({ path: path.join(OUT, "quota_expired_qwen_plus.png") }).catch(() => {});

    // B. 从首页点击 API Key 卡片，捕获真实 URL
    const p2 = await ctx.newPage();
    await p2.goto("https://bailian.console.aliyun.com/", { waitUntil: "domcontentloaded", timeout: 45000 });
    await p2.waitForTimeout(3000);
    const [pop] = await Promise.all([
      ctx.waitForEvent("page", { timeout: 6000 }).catch(() => null),
      p2.getByText("API Key", { exact: true }).first().click({ timeout: 10000 }).catch((e) => console.log("key click err", String(e).slice(0, 120))),
    ]);
    const k = pop || ctx.pages()[ctx.pages().length - 1];
    await k.waitForTimeout(3500);
    const kb = ((await k.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ").slice(0, 900);
    console.log("APIKEY_URL:", k.url());
    console.log("APIKEY_BODY:", kb);
    await k.screenshot({ path: path.join(OUT, "bailian_apikey_page.png") }).catch(() => {});
    console.log("SHOT: m0/out/login/bailian_apikey_page.png");
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
  }
  await browser.close();
})();
