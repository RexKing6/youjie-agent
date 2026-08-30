import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "/Users/runqing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";

const root = "/Users/runqing/Documents/Codex/2026-07-28/https-www-goaihz-com-tracks-track/outputs/goai_delivery_guard";
const outDir = path.join(root, "artifacts/semifinal_video_erpnext");
const finalRaw = path.join(outDir, "youjie_semifinal_demo_erpnext_raw.webm");

await fs.mkdir(outDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  deviceScaleFactor: 1,
  recordVideo: { dir: outDir, size: { width: 1280, height: 720 } },
  colorScheme: "light",
});
const page = await context.newPage();
const video = page.video();

await page.addInitScript(() => {
  document.addEventListener("mousemove", (event) => {
    let cursor = document.getElementById("demo-cursor");
    if (!cursor) {
      cursor = document.createElement("div");
      cursor.id = "demo-cursor";
      Object.assign(cursor.style, {
        position: "fixed", width: "20px", height: "20px",
        border: "3px solid #ff7657", borderRadius: "50%",
        background: "rgba(255,255,255,.78)", pointerEvents: "none",
        zIndex: "2147483647", transform: "translate(-50%,-50%)",
        boxShadow: "0 0 0 5px rgba(255,118,87,.18)",
      });
      document.documentElement.appendChild(cursor);
    }
    cursor.style.left = `${event.clientX}px`;
    cursor.style.top = `${event.clientY}px`;
  }, true);
});

const pause = (ms) => page.waitForTimeout(ms);
async function focus(locator, ms = 700) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await pause(ms);
}
async function click(locator, after = 1200) {
  await focus(locator);
  await locator.click();
  await pause(after);
}

try {
  await page.goto(process.env.DEMO_URL || "http://localhost:3000/", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "先输入一句真实事故，再看 Agent 到底做了什么" }).waitFor({ timeout: 15000 });
  await pause(4500);

  const input = page.getByRole("textbox", { name: "自然语言事故输入" });
  await input.fill("Mendeley seat supplier 通知：座椅在未来 48 小时无法发运，请分析受影响订单并给出恢复方案。");
  await click(page.getByRole("button", { name: "实际运行 Agent" }), 800);
  await page.getByText("awaiting_approval", { exact: true }).waitFor({ timeout: 30000 });
  await focus(page.getByText("CP-SAT + verifier 的动态结果"), 6500);

  await page.getByRole("combobox", { name: "选择恢复方案" }).selectOption({ label: "平衡方案" });
  await click(page.getByRole("button", { name: "人工批准并生成草稿" }), 800);
  await page.getByText("审批完成：现在才允许调用外部业务系统").waitFor({ timeout: 20000 });
  await pause(3500);

  const profile = page.getByRole("combobox", { name: "选择 ERP MES 集成 profile" });
  await profile.selectOption("erpnext_open_source_test_profile");
  await click(page.getByRole("button", { name: "写入 ERPNext 草稿" }), 800);
  await page.getByRole("region", { name: "真实 ERPNext 测试实例证据" }).waitFor({ timeout: 25000 });
  await focus(page.getByRole("region", { name: "真实 ERPNext 测试实例证据" }), 7500);

  await click(page.getByRole("button", { name: "同步到真实 OpenMES" }), 800);
  const openmesRegion = page.getByRole("region", { name: "真实 OpenMES 测试实例证据" });
  await openmesRegion.waitFor({ timeout: 25000 });
  await focus(openmesRegion, 7500);
  await click(page.getByRole("button", { name: "读取真实 MES 回流" }), 800);
  await focus(openmesRegion, 6500);

  await profile.selectOption("kingdee_blacklake_contract_profile");
  await click(page.getByRole("button", { name: "运行合同沙箱" }), 800);
  await page.getByText("PARTIALLY_APPLIED", { exact: false }).first().waitFor({ timeout: 25000 });
  await focus(page.getByText("PARTIALLY_APPLIED", { exact: false }).first(), 7500);

  const walkthrough = page.getByText("一次供应延期，从发现影响到执行回流");
  await focus(walkthrough, 2500);
  const next = page.getByRole("button", { name: "下一步" });
  await click(next, 3800);
  await click(next, 5200);
  await click(next, 3000);
  await click(page.getByRole("button", { name: "我是计划员，批准这个方案" }), 2500);
  await click(next, 4300);
  await click(next, 5200);
  await pause(2500);
} finally {
  await context.close();
  await browser.close();
}

const recorded = await video.path();
await fs.copyFile(recorded, finalRaw);
console.log(finalRaw);
