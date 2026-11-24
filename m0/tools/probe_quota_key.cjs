#!/usr/bin/env node
/**
 * 只读导航：从百炼控制台首页进入「免费额度」与「API Key」页面，输出状态。
 * 严禁点击：领取/开通/创建/购买/同意协议/任何付费按钮。
 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");

const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");

async function dump(page, tag) {
  await page.waitForTimeout(3500);
  const body = ((await page.locator("body").innerText().catch(() => "")) || "")
    .replace(/\s+/g, " ")
    .slice(0, 1800);
  console.log(`--- ${tag} ---`);
  console.log("URL:", page.url());
  console.log("BODY:", body);
  const btns = await page
    .locator("button, a")
    .evaluateAll((els) =>
      els
        .map((e) => (e.innerText || e.value || "").trim().slice(0, 24))
        .filter((t) => t && /领取|开通|创建|购买|同意|协议|停用|设置|限额|剩余|有效期/.test(t))
        .slice(0, 30)
    )
    .catch(() => []);
  console.log("BUTTONS:", JSON.stringify(btns));
  await page.screenshot({ path: path.join(OUT, `bailian_${tag}.png`) }).catch(() => {});
  console.log("SHOT:", `m0/out/login/bailian_${tag}.png`);
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({
    storageState: STATE,
    viewport: { width: 1440, height: 950 },
    locale: "zh-CN",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  });
  const page = await ctx.newPage();
  try {
    await page.goto("https://bailian.console.aliyun.com/", { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(3000);
    const [pop1] = await Promise.all([
      ctx.waitForEvent("page", { timeout: 6000 }).catch(() => null),
      page.getByText("免费额度", { exact: true }).first().click({ timeout: 10000 }).catch((e) => console.log("quota click err", String(e).slice(0, 120))),
    ]);
    const q = pop1 || ctx.pages()[ctx.pages().length - 1];
    await dump(q, "quota");
    if (pop1) await pop1.close().catch(() => {});

    await page.bringToFront().catch(() => {});
    const [pop2] = await Promise.all([
      ctx.waitForEvent("page", { timeout: 6000 }).catch(() => null),
      page.getByText("API Key", { exact: true }).first().click({ timeout: 10000 }).catch((e) => console.log("key click err", String(e).slice(0, 120))),
    ]);
    const k = pop2 || ctx.pages()[ctx.pages().length - 1];
    await dump(k, "apikey");
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
  }
  await browser.close();
})();
