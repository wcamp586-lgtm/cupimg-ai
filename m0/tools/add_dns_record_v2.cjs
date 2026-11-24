/**
 * aicloud.plus 新增 A 记录 cupimg -> 101.33.74.41（修正版）。
 * 关键：第一次「确定」后还有「解析变更确认」二次确认框，必须再确认一次才写入。
 * 复核方式：关闭当前页面、用全新 page 重新打开记录页读表格，绝不依赖表单残留文本。
 */
const { chromium } = require("D:/DevTools/npm-global/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "../..");
const STATE = path.join(ROOT, "m0", ".secrets", "aliyun_dns_state.json");
const OUT = path.join(ROOT, "m0", "out", "aliyun_dns");
const DOMAIN = "aicloud.plus", RR = "cupimg", VALUE = "101.33.74.41";
const PAGE = "https://dnsnext.console.aliyun.com/authoritative/domains/" + DOMAIN;

async function readTable(page) {
  await page.goto(PAGE, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(9000);
  return ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
}

(async () => {
  const browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ storageState: STATE,
    viewport: { width: 1500, height: 1000 }, locale: "zh-CN" });
  const result = { domain: DOMAIN, rr: RR, type: "A", value: VALUE, phase: "start" };
  try {
    const page = await ctx.newPage();
    let table = await readTable(page);
    result.before_count = (table.match(/共 (\d+) 条/) || [])[1] || "?";
    console.log("BEFORE:", result.before_count, "条记录 | cupimg exists:", table.includes(RR));
    if (table.includes(RR) && table.includes(VALUE)) {
      result.phase = "already_exists";
      console.log("RESULT:", JSON.stringify(result));
      fs.writeFileSync(path.join(OUT, "add_record_v2_result.json"), JSON.stringify(result, null, 2));
      await browser.close(); return;
    }

    await page.getByText("添加记录", { exact: true }).first().click({ timeout: 10000 });
    await page.waitForTimeout(2200);
    await page.locator('input[placeholder="请输入主机记录"]').last().fill(RR);
    await page.locator('input[placeholder="请输入记录值"]').last().fill(VALUE);
    console.log("FILLED:", RR, "->", VALUE);

    // 第一次确定：提交表单
    await page.getByRole("button", { name: "确定", exact: true }).first().click({ timeout: 10000 });
    console.log("FIRST_CONFIRM_CLICKED");

    // 二次确认框「解析变更确认」
    await page.getByText("解析变更确认", { exact: false }).first().waitFor({ timeout: 12000 });
    await page.waitForTimeout(1000);
    const confirmText = ((await page.locator("body").innerText().catch(() => "")) || "").replace(/\s+/g, " ");
    const idx = confirmText.indexOf("解析变更确认");
    console.log("SECOND_DIALOG:", confirmText.slice(idx, idx + 220));
    if (!confirmText.slice(idx, idx + 260).includes(VALUE)) {
      throw new Error("二次确认框里的记录值不符，拒绝提交");
    }
    const btns = page.getByRole("button", { name: "确定", exact: true });
    const n = await btns.count();
    console.log("CONFIRM_BUTTONS:", n);
    await btns.last().click({ timeout: 10000 });
    console.log("SECOND_CONFIRM_CLICKED");
    await page.waitForTimeout(7000);
    result.phase = "submitted";
    await page.screenshot({ path: path.join(OUT, "after_v2_submit.png") });

    // 独立会话复核：关掉当前页，新开 page 重新读取记录表
    await page.close();
    const verify = await ctx.newPage();
    table = await readTable(verify);
    const i = table.indexOf("记录类型");
    result.after_count = (table.match(/共 (\d+) 条/) || [])[1] || "?";
    result.table_slice = table.slice(i >= 0 ? i : 0, (i >= 0 ? i : 0) + 700);
    result.verified = table.includes(RR) && table.includes(VALUE);
    result.phase = result.verified ? "verified" : "not_written";
    console.log("AFTER:", result.after_count, "条 | verified:", result.verified);
    console.log("TABLE:", result.table_slice.slice(0, 500));
    await verify.screenshot({ path: path.join(OUT, "verify_v2_records.png") });
  } catch (e) {
    result.phase = "error";
    result.error = String(e).slice(0, 250);
    console.log("ERROR:", result.error);
  }
  fs.writeFileSync(path.join(OUT, "add_record_v2_result.json"), JSON.stringify(result, null, 2), "utf-8");
  console.log("RESULT:", JSON.stringify({ phase: result.phase, verified: result.verified,
                                          before: result.before_count, after: result.after_count }));
  await browser.close();
})();
