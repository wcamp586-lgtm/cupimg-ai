#!/usr/bin/env node
/**
 * 已执行过一次，勿重复运行（会再建一个 Key）。保留仅作流程留档。
 * 后续如需新 Key，请用 reset_api_key.cjs（重置而非新建）。
 *
 * 教训（2026-11-06 修复）：百炼新版 Key 形如 sk-ws-xxx.yyy.zzz，含点/下划线/连字符，
 * 旧正则 sk-[A-Za-z0-9]{20,} 匹配不到，曾导致明文进入调试输出。已统一改为
 * sk-[A-Za-z0-9._-]{20,}，脱敏函数同步覆盖，且已把当时那个 Key 重置作废。
 *
 * 安全约定：stdout 绝不输出 Key 内容；不代勾协议；不点任何付费/购买按钮。
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

function maskText(s) {
  return String(s || "").replace(/sk-[A-Za-z0-9._\-]{16,}/g, "[REDACTED_KEY]");
}

async function collectText(page) {
  const parts = [];
  parts.push(await page.locator("body").innerText().catch(() => ""));
  parts.push(
    await page.locator("input, textarea, code, pre").evaluateAll((els) =>
      els.map((e) => (e.value !== undefined ? e.value : e.innerText) || "").join(" \n ")
    ).catch(() => "")
  );
  return parts.join(" \n ");
}

function extractKey(text) {
  const m = String(text).match(/sk-[A-Za-z0-9._\-]{20,}/);
  return m ? m[0] : null;
}

function writeEnv(key, existing) {
  const prev = fs.existsSync(ENV_PATH) ? fs.readFileSync(ENV_PATH, "utf8") : "";
  const lines = [
    "# 本文件由 m0/tools/create_api_key.cjs 生成/更新，已在 .gitignore 中，绝不外发",
    "# 生成时间: " + new Date().toISOString(),
    "",
    "# 阿里云百炼 · 华北2（北京）· 业务空间专属域名（旧 dashscope 域名已进维护状态）",
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
  let key = null;
  try {
    await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 45000 });
    await page.waitForTimeout(4500);
    const before = maskText(await collectText(page));
    console.log("PAGE_HAS_NO_KEY_HINT:", before.includes("暂无API Key"));
    if (!before.includes("暂无API Key")) {
      console.log("STOP: 页面已存在 API Key 列表，未创建新 Key（避免重复凭据）");
      await browser.close();
      return;
    }

    const createBtn = page.getByRole("button", { name: /创建API[- ]?KEY|创建API Key/i }).first();
    console.log("CREATE_BTN_COUNT:", await createBtn.count());
    await createBtn.click({ timeout: 10000 });
    await page.waitForTimeout(1800);

    // 结构探测（输出全部脱敏）
    const dlgText = maskText(await collectText(page));
    console.log("DIALOG_STRUCT:", dlgText.replace(/\s+/g, " ").slice(-620));
    const inputs = await page.locator("[role=dialog] input, .next-dialog input, .ant-modal input, input").evaluateAll((els) =>
      els.map((e) => ({ ph: e.placeholder || "", type: e.type, checked: e.checked }))
    ).catch(() => []);
    console.log("INPUTS:", JSON.stringify(inputs.slice(0, 8)));
    const btns = await page.getByRole("button").allTextContents().catch(() => []);
    console.log("BUTTONS:", JSON.stringify(btns.map((b) => b.trim()).filter(Boolean).slice(-14)));

    // 协议勾选框：不代勾，停下来等用户
    const agreement = page.locator("input[type=checkbox]").filter({ hasNot: page.locator("x") });
    const unchecked = await page.locator("input[type=checkbox]:not(:checked)").count().catch(() => 0);
    const dlgHasAgreement = /协议|同意|条款/.test(dlgText) && unchecked > 0;
    if (dlgHasAgreement) {
      console.log("NEED_USER_ACTION: 弹窗含未勾选协议，脚本不代勾，未创建 Key");
      await page.screenshot({ path: path.join(OUT, "apikey_agreement.png") }).catch(() => {});
      await browser.close();
      return;
    }

    // 填名称（若需要）
    // 必须限定在弹窗内：页面上还有「请输入关键词」的全局产品搜索框，填错会污染左侧抽屉
    const nameInput = page.locator("[role=dialog] textarea, [role=dialog] input[placeholder*='描述'], textarea").first();
    if (await nameInput.count().catch(() => 0)) {
      await nameInput.fill("m0-pipeline").catch(() => {});
    }

    const ok = page.getByRole("button", { name: /^(确定|确认|创建|立即创建)$/ }).last();
    if (await ok.count().catch(() => 0)) {
      await ok.click({ timeout: 8000 }).catch((e) => console.log("confirm click err", String(e).slice(0, 100)));
    }
    await page.waitForTimeout(3000);

    const all = await collectText(page);
    key = extractKey(all);
    if (!key) {
      await page.screenshot({ path: path.join(OUT, "apikey_created_debug.png") }).catch(() => {});
      console.log("KEY_NOT_FOUND: 已保存调试截图（本地，含明文，勿外发）");
      console.log("RESULT_TEXT:", maskText(all).replace(/\s+/g, " ").slice(-700));
      await browser.close();
      return;
    }

    writeEnv(key);
    console.log("KEY_SAVED=1");
    console.log("ENV_PATH=m0/.env");
    console.log("KEY_LENGTH=" + key.length);
    console.log("BASE_URL_SET=" + (fs.readFileSync(ENV_PATH, "utf8").includes(BASE_URL) ? "1" : "0"));
    console.log("TEXT_MODEL_SET=" + (fs.readFileSync(ENV_PATH, "utf8").includes("TEXT_MODEL=qwen3.7-plus") ? "1" : "0"));
    await page.screenshot({ path: path.join(OUT, "apikey_created.png") }).catch(() => {});
  } catch (e) {
    console.log("FATAL:", maskText(String(e)).slice(0, 300));
  }
  await browser.close();
})();
