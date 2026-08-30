import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "/Users/runqing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs";

const root = "/Users/runqing/Documents/Codex/2026-07-28/https-www-goaihz-com-tracks-track/outputs/goai_delivery_guard";
const outDir = path.join(root, "artifacts/semifinal_video");
const finalRaw = path.join(outDir, "youjie_semifinal_demo_raw.webm");

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
  const ensureCursor = () => {
    let cursor = document.getElementById("demo-cursor");
    if (!cursor) {
      cursor = document.createElement("div");
      cursor.id = "demo-cursor";
      Object.assign(cursor.style, {
        position: "fixed",
        width: "18px",
        height: "18px",
        border: "3px solid #ff7a1a",
        borderRadius: "50%",
        background: "rgba(255,255,255,.72)",
        pointerEvents: "none",
        zIndex: "2147483647",
        transform: "translate(-50%,-50%)",
        boxShadow: "0 0 0 4px rgba(255,122,26,.18)",
      });
      document.documentElement.appendChild(cursor);
    }
    return cursor;
  };
  document.addEventListener("mousemove", (event) => {
    const cursor = ensureCursor();
    cursor.style.left = `${event.clientX}px`;
    cursor.style.top = `${event.clientY}px`;
  }, true);
  document.addEventListener("mousedown", () => {
    const cursor = ensureCursor();
    cursor.style.background = "rgba(255,122,26,.72)";
    setTimeout(() => { cursor.style.background = "rgba(255,255,255,.72)"; }, 300);
  }, true);
});

async function pause(ms) {
  await page.waitForTimeout(ms);
}

async function focus(locator, ms = 800) {
  await locator.scrollIntoViewIfNeeded();
  const box = await locator.boundingBox();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  }
  await pause(ms);
}

async function click(locator, after = 1200) {
  await focus(locator);
  await locator.click();
  await pause(after);
}

async function selectNextCase(expectedText) {
  const combo = page.getByRole("combobox", { name: "复赛验证案例" });
  await focus(combo, 500);
  await combo.click();
  const option = page.getByRole("option", { name: expectedText });
  await option.waitFor({ timeout: 5000 });
  await option.click();
  await page.getByText(expectedText, { exact: false }).first().waitFor({ timeout: 8000 });
  await pause(1800);
}

try {
  await page.goto(process.env.DEMO_URL || "http://127.0.0.1:8510/", { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /有界/ }).waitFor({ timeout: 10000 });
  await page.getByText("Live · qwen3.8-max", { exact: false }).first().waitFor({ timeout: 10000 });
  await pause(3000);

  await click(page.getByRole("tab", { name: "② 事故与 Agent" }), 2500);
  await page.getByText("模拟供应商邮件", { exact: false }).first().scrollIntoViewIfNeeded();
  await pause(2500);
  await click(page.getByRole("button", { name: "启动 LangGraph 演练" }), 1200);
  await page.getByText("LangGraph 已运行至：awaiting_approval").waitFor({ timeout: 20000 });
  await page.getByText("本次模型：qwen3.8-max", { exact: false }).scrollIntoViewIfNeeded();
  await pause(3500);
  await click(page.getByRole("tab", { name: "③ 恢复指挥台" }), 1600);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await page.getByRole("heading", { name: "订单影响图" }).waitFor({ timeout: 8000 });
  await pause(6000);
  await page.getByRole("heading", { name: "LangGraph 人工中断点" }).scrollIntoViewIfNeeded();
  await pause(3500);
  const planCombo = page.getByRole("combobox", { name: "待审批方案" });
  await planCombo.click();
  await page.getByRole("option", { name: "平衡方案" }).click();
  await pause(1200);
  await click(page.getByRole("button", { name: "批准并恢复图执行" }), 1600);
  await page.getByText(/哈希复核通过，生成 4 张 draft_only 工单/).waitFor({ timeout: 15000 });
  await pause(3500);

  await click(page.getByRole("tab", { name: "④ ERP/MES闭环" }), 1800);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await pause(3500);
  await click(page.getByRole("button", { name: "启动本地HTTP沙箱并演练执行回流" }), 1600);
  await page.getByText(/ERP草稿已创建，但MES因产能版本变化拒绝/).waitFor({ timeout: 20000 });
  await pause(6000);
  await page.getByRole("heading", { name: "执行结果回流 → 旧计划失效 → 重新求解" }).scrollIntoViewIfNeeded();
  await pause(6500);

  await click(page.getByRole("tab", { name: "⑤ 工具审计" }), 1800);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await page.getByText("真实模型对抗评测").waitFor({ timeout: 8000 });
  await pause(6000);
} finally {
  await context.close();
  await browser.close();
}

const recorded = await video.path();
await fs.copyFile(recorded, finalRaw);
console.log(finalRaw);
