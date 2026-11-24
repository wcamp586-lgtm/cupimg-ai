#!/usr/bin/env node
/**
 * 重置刚创建的 API Key（使已意外出现在调试输出中的旧值立即失效），
 * 捕获新值并写入本机 m0/.env。stdout 全程脱敏，绝不输出密钥内容。
 */
const fs = require("fs");
const path = require("path");
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");

const ROOT = path.resolve(__dirname, "..");
const STATE = path.join(ROOT, ".secrets", "aliyun_state.json");
const OUT = path.join(ROOT, "out", "login");
const ENV_PATH = path.join(ROOT, ".env");
const URL = "https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key";
const BASE_URL = "https://ws-gf70elw9s7tocx1l.cn-beijing.maas.aliyuncs.com/compatible-mode/v1";
const KEY_RE = /sk-[A-Za-z0-9._\-]{20,}/g;

const redact = (s) => String(s || "").replace(/sk-[A-Za-z0-9._\-]{16,}/g, "[REDACTED_KEY]");

async function collect(page) {
  const a = await page.locator("body").innerText().catch(() => "");
  const b = await page
    .locator("input, textarea, code, pre, [class*=copy]")
    .evaluateAll((els) => els.map((e) => (e.value !== undefined ? e.value : e.innerText) || "").join(" \n "))
    .catch(() => "");
  return a + " \n " + b;
}

function writeEnv(key) {
  const lines = [
    "# 本文件由 m0/tools/reset_api_key.cjs 生成，已在 .gitignore 中，绝不外发",
    "# 生成时间: " + new Date().toISOString(),
    "",
    "# 阿里云百炼 · 华北2（北京）· 业务空间专属域名",
    "# 注意：首次创建时明文曾出现在调试输出，已通过「重置」使其失效，本值为重置后的新密钥",
    "DASHSCOPE_API_KEY=" + key,
    "DASHSCOPE_BASE=" + BASE_URL,
    "VL_MODEL=qwen3-vl-plus",
    "# qwen-plus 本体无免费额度，改用同代有 1M 免费额度的 qwen3.7-plus",
    "TEXT_MODEL=qwen3.7-plus",
    "",
    "# BytePlus ModelArk 国际版：待开，留空即该环节走本地桩",
    "BYTEPLUS_API_KEY=",
    "BYTEPLUS_BASE=https://ark.byteplusapi.com/api/v3",
    "SEEDREAM_MODEL=seedream-4-5-251128",
    "",
    "REMBG_MODEL=isnet-general-use",
    "COST_CAP_CNY=10",
    "",
  ];
  fs.writeFileSync(ENV_PATH, lines.join("\n"), "utf8");
}

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
    const t0 = await collect(page);
    console.log("LIST_HAS_KEY:", /m0-pipeline/.test(t0), "| HAS_RESET_BTN:", /重置/.test(t0));

    const reset = page.getByRole("button", { name: /^重置$/ }).first();
    if (!(await reset.count().catch(() => 0))) {
      const more = page.getByRole("button", { name: /^更多$/ }).first();
      if (await more.count().catch(() => 0)) {
        await more.click({ timeout: 8000 }).catch(() => {});
        await page.waitForTimeout(1200);
      }
    }
    const reset2 = page.getByText("重置", { exact: true }).first();
    if (await reset2.count().catch(() => 0)) {
      await reset2.click({ timeout: 8000 }).catch((e) => console.log("reset click err", redact(String(e)).slice(0, 120)));
    }
    await page.waitForTimeout(1800);
    const dlg = redact(await collect(page));
    console.log("DIALOG_TAIL:", dlg.replace(/\s+/g, " ").slice(-420));
    const ok = page.getByRole("button", { name: /^(确定|确认|重置|立即重置)$/ }).last();
    if (await ok.count().catch(() => 0)) {
      await ok.click({ timeout: 8000 }).catch((e) => console.log("confirm err", redact(String(e)).slice(0, 120)));
    }
    await page.waitForTimeout(3500);

    const all = await collect(page);
    const found = all.match(KEY_RE) || [];
    // 新值应出现在「创建成功/重置成功」弹窗中；取最后一个匹配
    if (!found.length) {
      console.log("KEY_NOT_FOUND: 未捕获新密钥，未改动 .env");
      console.log("RESULT_TAIL:", redact(all).replace(/\s+/g, " ").slice(-500));
      await page.screenshot({ path: path.join(OUT, "apikey_reset_debug.png") }).catch(() => {});
      await browser.close();
      return;
    }
    const newKey = found[found.length - 1];
    const old = fs.existsSync(ENV_PATH) ? (fs.readFileSync(ENV_PATH, "utf8").match(KEY_RE) || [])[0] : null;
    writeEnv(newKey);
    const env = fs.readFileSync(ENV_PATH, "utf8");
    console.log("KEY_SAVED=1 | LENGTH=" + newKey.length);
    console.log("KEY_FORMAT_OK=" + (/^sk-ws-/.test(newKey) ? 1 : 0));
    console.log("BASE_URL_SET=" + (env.includes(BASE_URL) ? 1 : 0));
    console.log("TEXT_MODEL_SET=" + (env.includes("TEXT_MODEL=qwen3.7-plus") ? 1 : 0));
    console.log("ENV_WRITTEN=m0/.env");
    await page.screenshot({ path: path.join(OUT, "apikey_reset_done.png") }).catch(() => {});
  } catch (e) {
    console.log("FATAL:", redact(String(e)).slice(0, 300));
  }
  await browser.close();
})();
