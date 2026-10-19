/**
 * 浏览器冒烟测试:验证聊天页核心链路。
 * 运行前需启动后端(8000)与 Vite(5173)。
 *   node scripts/smoke.mjs
 * 使用系统已安装的 Microsoft Edge,无需额外下载浏览器。
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const SHOT_DIR = process.env.SHOT_DIR || 'C:/Users/hp/AppData/Local/Temp'

const errors = []
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})

try {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=智能客服小e', { timeout: 15000 })
  const welcome = await page.locator('body').innerText()
  console.log('WELCOME_OK:', welcome.includes('我可以帮您查询订单'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-welcome.png` })

  await page.fill('textarea', '查订单 ORDER20260315001')
  await page.keyboard.press('Enter')
  await page.waitForSelector('text=订单详情', { timeout: 60000 })
  const orderText = await page.locator('body').innerText()
  console.log('ORDER_DETAIL_OK:', orderText.includes('ORDER20260315001'))
  console.log('ADDRESS_OK:', orderText.includes('北京市朝阳区建国路88号'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-order.png` })

  await page.fill('textarea', '太差了我要投诉')
  await page.keyboard.press('Enter')
  await page.waitForSelector('text=转接投诉处理专员', { timeout: 60000 })
  const transferText = await page.locator('body').innerText()
  console.log('TRANSFER_OK:', transferText.includes('转接投诉处理专员'))
  console.log('NEGATIVE_BADGE_OK:', transferText.includes('需要关注'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-transfer.png` })

  await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=意图分布', { timeout: 15000 })
  await page.waitForTimeout(1200)
  const dashboardText = await page.locator('body').innerText()
  console.log('DASHBOARD_OK:', dashboardText.includes('会话总量') && dashboardText.includes('情感分布'))
  await page.screenshot({ path: `${SHOT_DIR}/dashboard.png`, fullPage: true })

  await page.goto(`${BASE}/knowledge`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=知识库管理', { timeout: 15000 })
  await page.waitForSelector('text=怎么联系人工客服', { timeout: 15000 })
  console.log('KNOWLEDGE_OK:', true)
  await page.screenshot({ path: `${SHOT_DIR}/knowledge.png`, fullPage: true })

  await page.goto(`${BASE}/sessions`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=会话ID', { timeout: 15000 })
  await page.getByRole('button', { name: '查看' }).first().click()
  await page.waitForSelector('.ant-drawer-open', { timeout: 15000 })
  await page.waitForSelector('.ant-drawer-body .message-bubble', { timeout: 15000 })
  const drawerText = await page.locator('.ant-drawer-body').innerText()
  console.log('SESSION_DETAIL_OK:', drawerText.includes('订单详情') || drawerText.includes('转接投诉'))
  await page.screenshot({ path: `${SHOT_DIR}/sessions.png` })

  console.log('PAGE_ERRORS:', errors.length ? JSON.stringify(errors) : 'none')
} finally {
  await browser.close()
}
