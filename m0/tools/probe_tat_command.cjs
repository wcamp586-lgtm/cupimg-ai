/**
 * 只读探测轻量实例「执行命令 / 自动化助手」入口与表单结构。
 * 目的：找到一条不需要 SSH 私钥、不需要重启实例的 bootstrap 通道，
 * 用于把本机公钥写入 ~/.ssh/authorized_keys，之后全程走 SSH 部署。
 * 本脚本绝不点击「执行 / 确定 / 创建」等提交按钮。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "tencent_state.json");
const OUT = path.join(ROOT, "m0", "out", "tencent");
const DETAIL = "https://console.cloud.tencent.com/lighthouse/instance/detail?rid=18&id=lhins-4er2ovz2";

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ storageState: STATE,
    viewport: { width: 1500, height: 1000 }, locale: "zh-CN" });
  const page = await ctx.newPage();

  await page.goto(DETAIL, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(8000);
  const tab = page.getByText("执行命令", { exact: true }).first();
  console.log("TAB_COUNT:", await tab.count().catch(() => 0));
  if (await tab.count().catch(() => 0)) {
    await tab.click({ timeout: 8000 }).catch((e) => console.log("click err", String(e).slice(0, 120)));
    await page.waitForTimeout(7000);
  }
  const p = ctx.pages()[ctx.pages().length - 1];
  console.log("FINAL_URL:", p.url());
  const body = ((await p.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
  console.log("BODY:", body.slice(0, 1800));
  const inputs = await p.locator("input, textarea, [contenteditable=true]").all().catch(() => []);
  console.log("FORM_FIELDS:", inputs.length);
  for (const el of inputs.slice(0, 12)) {
    try {
      const info = await el.evaluate((e) => ({ tag: e.tagName, type: e.type || "",
        placeholder: e.placeholder || "", cls: String(e.className || "").slice(0, 60) }));
      console.log("  FIELD:", JSON.stringify(info));
    } catch (_) {}
  }
  await p.screenshot({ path: path.join(OUT, "tat_command.png") });
  await browser.close();
})();
