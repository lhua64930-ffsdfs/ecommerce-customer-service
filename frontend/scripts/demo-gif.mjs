/**
 * 录制演示 GIF:驱动浏览器完成「欢迎页 → 订单查询 → RAG 引用 → 投诉转人工」,
 * 截取关键帧后调用 Pillow 合成 docs/images/demo.gif。
 *
 * 运行前需启动后端(8000)与 Vite(5173):
 *   node scripts/demo-gif.mjs
 */
import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const HERE = fileURLToPath(new URL('.', import.meta.url))
const ROOT = resolve(HERE, '../..')
const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const OUTPUT = process.env.GIF_OUT || resolve(ROOT, 'docs/images/demo.gif')

const windowsPython = resolve(ROOT, 'backend/venv/Scripts/python.exe')
const unixPython = resolve(ROOT, 'backend/venv/bin/python')
const PYTHON = process.env.PYTHON || (existsSync(windowsPython) ? windowsPython : unixPython)
const GIF_SCRIPT = resolve(ROOT, 'scripts/make_demo_gif.py')

const framesDir = mkdtempSync(join(tmpdir(), 'after-sales-frames-'))
let frameIndex = 0

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1280, height: 860 } })

const shot = async (name) => {
  const index = String(frameIndex++).padStart(2, '0')
  await page.screenshot({ path: join(framesDir, `${index}-${name}.png`) })
}

const scrollToBottom = async () => {
  await page
    .locator('.chat-messages')
    .evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    .catch(() => {})
}

try {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=智能客服小e', { timeout: 20000 })
  await page.waitForTimeout(900)
  await shot('welcome')

  await page.fill('textarea', '查订单 ORDER20260315001')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(500)
  await shot('order-typing')

  await page
    .locator('.bubble-bot', { hasText: 'ORDER20260315001' })
    .first()
    .waitFor({ state: 'visible', timeout: 90000 })
  await page.waitForTimeout(900)
  await scrollToBottom()
  await shot('order-result')

  await page.fill('textarea', '商品可以退换吗')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(500)
  await shot('rag-typing')

  await page.waitForSelector('.citation-chip', { timeout: 60000 })
  await page.waitForTimeout(900)
  await scrollToBottom()
  await shot('rag-citation')

  await page.fill('textarea', '太差了我要投诉')
  await page.keyboard.press('Enter')
  await page.waitForTimeout(500)
  await shot('transfer-typing')

  await page.waitForSelector('text=转接投诉处理专员', { timeout: 60000 })
  await page.waitForTimeout(900)
  await scrollToBottom()
  await shot('transfer-result')

  execFileSync(PYTHON, [GIF_SCRIPT, framesDir, OUTPUT], { stdio: 'inherit' })
  console.log(`GIF 输出:${OUTPUT}`)
} finally {
  await browser.close()
  if (process.env.KEEP_FRAMES !== '1') {
    rmSync(framesDir, { recursive: true, force: true })
  } else {
    console.log(`帧保留在:${framesDir}`)
  }
}
