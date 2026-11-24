#!/usr/bin/env node
/**
 * 只读探测：用已保存的登录态打开百炼控制台，输出页面结构与关键状态。
 * 不做任何点击「开通/创建/付费/勾选协议」的操作，不输出 cookie 与密钥值。
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");

const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");
fs.mkdirSync(OUT, { recursive: true });

const TARGETS = [
  ["console", "https://bailian.console.aliyun.com/"],
  ["home", "https://home.console.aliyun.com/"],
];

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
    const ctx = await browser.newContext({
      storageState: STATE,
      viewport: { width: 1440, height: 950 },
      locale: "zh-CN",
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    });
    const page = await ctx.newPage();
    for (const [name, url] of TARGETS) {
      try {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
        await page.waitForTimeout(4000);
        const body = ((await page.locator("body").innerText().catch(() => "")) || "")
          .replace(/\s+/g, " ")
          .slice(0, 1400);
        const links = await page
          .locator("a[href]")
          .evaluateAll((els) =>
            els
              .map((e) => ({ t: (e.innerText || "").trim().slice(0, 30), h: e.getAttribute("href") }))
              .filter((x) => x.t && /API|Key|额度|费用|开通|模型|实名|账号|概览/.test(x.t))
              .slice(0, 25)
          )
          .catch(() => []);
        console.log(`--- ${name} ---`);
        console.log("URL:", page.url());
        console.log("TITLE:", (await page.title()).slice(0, 90));
        console.log("BODY:", body);
        console.log("LINKS:", JSON.stringify(links));
        await page.screenshot({ path: path.join(OUT, `bailian_${name}.png`), fullPage: false });
        console.log("SHOT:", `m0/out/login/bailian_${name}.png`);
      } catch (e) {
        console.log(`--- ${name} ERR:`, String(e).slice(0, 220));
      }
    }
    await browser.close();
  } catch (e) {
    console.log("FATAL:", String(e).slice(0, 300));
    if (browser) await browser.close().catch(() => {});
    process.exit(1);
  }
})();
