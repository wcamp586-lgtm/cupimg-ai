#!/usr/bin/env node
/** 只读探测：BytePlus 注册/登录页真实表单结构、第三方登录入口、是否强制绑卡。 */
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const OUT = path.resolve(__dirname, "..", "out", "byteplus");

const URLS = [
  ["signup", "https://console.byteplus.com/auth/signup"],
  ["login", "https://signin.byteplus.com/auth/login?redirectURI=https%3A%2F%2Fconsole.byteplus.com%2Fhome"],
];

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 }, locale: "en-US" });
  const page = await ctx.newPage();
  for (const [tag, url] of URLS) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(7000);
      const body = ((await page.locator("body").innerText().catch(() => "")) || "")
        .replace(/\s+/g, " ").slice(0, 1100);
      const inputs = await page.locator("input").evaluateAll((els) =>
        els.map((e) => ({ type: e.type, name: e.name || "", ph: e.placeholder || "", id: e.id || "" }))
      ).catch(() => []);
      const buttons = await page.getByRole("button").allTextContents().catch(() => []);
      const links = await page.locator("a[href]").evaluateAll((els) =>
        els.map((e) => ({ t: (e.innerText || "").trim().slice(0, 28), h: (e.getAttribute("href") || "").slice(0, 100) }))
          .filter((x) => x.t).slice(0, 24)
      ).catch(() => []);
      console.log(`--- ${tag} ---`);
      console.log("FINAL_URL:", page.url());
      console.log("TITLE:", (await page.title()).slice(0, 90));
      console.log("BODY:", body);
      console.log("INPUTS:", JSON.stringify(inputs.slice(0, 16)));
      console.log("BUTTONS:", JSON.stringify(buttons.map((b) => b.trim()).filter(Boolean).slice(0, 18)));
      console.log("LINKS:", JSON.stringify(links));
      console.log("IFRAMES:", page.frames().length);
      await page.screenshot({ path: path.join(OUT, `signup_${tag}.png`), fullPage: false }).catch(() => {});
      console.log("SHOT:", `m0/out/byteplus/signup_${tag}.png`);
    } catch (e) {
      console.log(`--- ${tag} ERR:`, String(e).slice(0, 220));
    }
  }
  await browser.close();
})();
