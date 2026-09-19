import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from '/Users/runqing/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';

const out = path.resolve('artifacts/finals_release_20260920/raw', new Date().toISOString().replaceAll(':','-'));
await fs.mkdir(out,{recursive:true});
const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context = await browser.newContext({viewport:{width:1440,height:900},recordVideo:{dir:out,size:{width:1440,height:900}},colorScheme:'light'});
const page = await context.newPage();
page.setDefaultTimeout(180000);
const start = Date.now(), marks=[];
async function mark(name){marks.push({name,seconds:(Date.now()-start)/1000});console.log(name,marks.at(-1).seconds);await page.screenshot({path:path.join(out,`${marks.length}-${name}.png`)});}
async function click(locator){await locator.scrollIntoViewIfNeeded();const b=await locator.boundingBox();if(b)await page.mouse.move(b.x+b.width/2,b.y+b.height/2,{steps:15});await page.waitForTimeout(700);await locator.click();await page.waitForTimeout(1800);}
const button=name=>page.getByRole('button',{name,exact:true});
const tab=name=>page.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:new RegExp(name)});
async function approve(){await click(tab('恢复方案'));await page.locator('#plan-actor').fill('青爷');await click(page.locator('.wiki-plan').filter({has:page.getByRole('heading',{name:'预算内折中',exact:true})}).getByRole('button'));await click(tab('执行与反馈'));}
try{
  await page.goto('http://localhost:3000/finals',{waitUntil:'networkidle'});
  await button('分析这次延期').waitFor();
  await mark('intake');await page.waitForTimeout(5000);
  await click(button('MCP Server'));await mark('mcp');await page.waitForTimeout(3000);await click(page.getByRole('button',{name:'关闭能力详情'}));
  await click(button('Skills'));await mark('skills');await page.waitForTimeout(3000);await click(page.getByRole('button',{name:'关闭能力详情'}));
  await click(button('分析这次延期'));await mark('analysis-start');
  await button('去补充信息').waitFor();await mark('analysis-done');await page.waitForTimeout(7000);
  await click(button('去补充信息'));await mark('question');await page.waitForTimeout(5000);
  await page.locator('#reply-preset').selectOption('oral');await click(button('发送'));
  await button('发送').isEnabled();
  await page.locator('article[aria-label="有界正在回复"]').waitFor({state:'hidden'});
  await mark('followup');await page.waitForTimeout(6000);
  await page.locator('#reply-preset').selectOption('partial');await mark('evidence');await click(button('发送'));
  await page.locator('article[aria-label="有界正在回复"]').waitFor({state:'hidden'});
  await click(tab('恢复方案'));await page.locator('.wiki-plan').first().waitFor();await mark('plans');await page.waitForTimeout(7000);
  await page.locator('.wiki-comparison').scrollIntoViewIfNeeded();await mark('gantt');await page.waitForTimeout(6000);
  await approve();await mark('approved');
  await click(button('手动注入变更：产线被占用32小时'));
  await button('重新计算恢复方案').waitFor();await mark('invalidated');await page.waitForTimeout(6000);
  await click(button('重新计算恢复方案'));await page.locator('.wiki-plan').first().waitFor();await mark('replanned');await page.waitForTimeout(6000);
  await approve();await click(button('确认方案，发送到测试业务系统'));
  await button('查看最新生产进度').waitFor();
  await page.waitForFunction(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent==='查看最新生产进度');return b&&!b.disabled;},{},{timeout:180000});
  await mark('delivered');await page.waitForTimeout(6000);await click(button('查看最新生产进度'));await mark('readback');await page.waitForTimeout(6000);
}catch(error){console.error(error.message);await mark('failed');await fs.writeFile(path.join(out,'failure.txt'),error.message);process.exitCode=1;}
finally{await fs.writeFile(path.join(out,'timings.json'),JSON.stringify(marks,null,2));await context.close();await browser.close();console.log('Recording directory:',out);}
