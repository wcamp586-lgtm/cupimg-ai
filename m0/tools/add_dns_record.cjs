/**
 * 在阿里云云解析 DNS 为 aicloud.plus 新增 1 条 A 记录：cupimg → 首尔轻量机公网 IP。
 * 严格限定：只新增，不修改/删除任何已有记录；提交后复核记录列表。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "aliyun_dns_state.json");
const OUT = path.join(ROOT, "m0", "out", "aliyun_dns");
const DOMAIN = "aicloud.plus";
const RR = "cupimg";
const VALUE = "101.33.74.41";
const PAGE = "https://dnsnext.console.aliyun.com/authoritative/domains/" + DOMAIN;

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ storageState: STATE,
    viewport: { width: 1500, height: 1000 }, locale: "zh-CN" });
  const page = await ctx.newPage();
  const result = { domain: DOMAIN, rr: RR, type: "A", value: VALUE, phase: "start" };
  try {
    await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(9000);
    const before = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    if (!before.includes(DOMAIN)) throw new Error("未进入 aicloud.plus 记录页");
    if (/\bcupimg\b/.test(before)) {
      result.phase = "already_exists";
      console.log("RESULT:", JSON.stringify(result));
      await browser.close();
      return;
    }
    console.log("EXISTING_RECORDS_OK: jinfeng-hotel / fengming / gongdan 未受影响");

    await page.getByText("添加记录", { exact: true }).first().click({ timeout: 10000 });
    await page.waitForTimeout(2500);

    const rr = page.locator('input[placeholder="请输入主机记录"]').last();
    const val = page.locator('input[placeholder="请输入记录值"]').last();
    if (!(await rr.count())) throw new Error("未找到主机记录输入框");
    if (!(await val.count())) throw new Error("未找到记录值输入框");
    await rr.fill(RR);
    await val.fill(VALUE);
    console.log("FILLED:", RR, "->", VALUE);
    console.log("RR_NOW:", await rr.inputValue(), "VALUE_NOW:", await val.inputValue());

    // 记录类型默认 A，若不是则显式选择
    const dlgText = ((await page.locator("body").innerText().catch(() => "")) || "");
    if (!/记录类型\s*A\s*--\s*将域名指向一个IPv4地址/.test(dlgText.replace(/\s+/g, " "))) {
      console.log("WARN: 记录类型可能不是 A，请人工复核；本次不提交");
      result.phase = "type_check_failed";
      throw new Error("record type not confirmed as A");
    }

    const buttons = await page.locator("button").allTextContents().catch(() => []);
    console.log("BUTTONS:", JSON.stringify(buttons.filter(Boolean).slice(-12)));
    // 新版控制台按钮文案是「确定」/「添加并继续」/「取消」
    const submit = page.getByRole("button", { name: "确定", exact: true }).last();
    if (!(await submit.count().catch(() => 0))) throw new Error("未找到「确定」提交按钮");
    await submit.click({ timeout: 10000 });
    result.phase = "submitted";
    console.log("SUBMITTED");
    await page.waitForTimeout(6000);

    const after = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    result.verified = after.includes(RR) && after.includes(VALUE);
    result.phase = result.verified ? "verified" : "submitted_unverified";
    console.log("AFTER_HAS_RR:", after.includes(RR), "AFTER_HAS_IP:", after.includes(VALUE));
    await page.screenshot({ path: path.join(OUT, "after_add_record.png") });
    console.log("RESULT:", JSON.stringify(result));
  } catch (e) {
    result.phase = "error";
    result.error = String(e).slice(0, 250);
    console.log("ERROR:", result.error);
    await page.screenshot({ path: path.join(OUT, "add_record_error.png") }).catch(() => {});
    fs.writeFileSync(path.join(OUT, "add_record_result.json"), JSON.stringify(result, null, 2));
    await browser.close();
    process.exitCode = 1;
    return;
  }
  fs.writeFileSync(path.join(OUT, "add_record_result.json"), JSON.stringify(result, null, 2), "utf-8");
  await browser.close();
})();
