/**
 * 浏览器冒烟测试:验证聊天页核心链路。
 * 运行前需启动后端(8000)与 Vite(5173)。
 *   node scripts/smoke.mjs
 * 使用系统已安装的 Microsoft Edge,无需额外下载浏览器。
 */
import { tmpdir } from 'node:os'
import { chromium } from 'playwright'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:5173'
const SHOT_DIR = process.env.SHOT_DIR || tmpdir()

const errors = []
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})

const scrollToBottom = async () => {
  await page
    .locator('.chat-messages')
    .evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    .catch(() => {})
  await page.waitForTimeout(400)
}

try {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('text=智能客服小e', { timeout: 15000 })
  const welcome = await page.locator('body').innerText()
  console.log('WELCOME_OK:', welcome.includes('我可以帮您查询订单'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-welcome.png` })

  await page.fill('textarea', '查订单 ORDER20260315001')
  await page.keyboard.press('Enter')
  await page
    .locator('.bubble-bot', { hasText: 'ORDER20260315001' })
    .first()
    .waitFor({ state: 'visible', timeout: 90000 })
  await scrollToBottom()
  const orderText = await page.locator('body').innerText()
  console.log('ORDER_DETAIL_OK:', orderText.includes('ORDER20260315001'))
  console.log('ADDRESS_MASKED_OK:', orderText.includes('北京市朝阳区***'))
  console.log('PHONE_MASKED_OK:', orderText.includes('138****6789'))
  console.log('FULL_PHONE_HIDDEN:', !orderText.includes('13800006789'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-order.png` })

  await page.fill('textarea', '商品可以退换吗')
  await page.keyboard.press('Enter')
  await page.waitForSelector('.citation-chip', { timeout: 90000 })
  await scrollToBottom()
  const ragText = await page.locator('body').innerText()
  console.log('RAG_CITATION_OK:', ragText.includes('退换货政策') || ragText.includes('商品可以退换吗'))
  await page.screenshot({ path: `${SHOT_DIR}/chat-rag.png` })

  await page.fill('textarea', '太差了我要投诉')
  await page.keyboard.press('Enter')
  await page.waitForSelector('text=转接投诉处理专员', { timeout: 90000 })
  await scrollToBottom()
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
  console.log(
    'SESSION_DETAIL_OK:',
    drawerText.includes('ORDER20260315001') ||
      drawerText.includes('订单') ||
      drawerText.includes('转接投诉'),
  )
  await page.screenshot({ path: `${SHOT_DIR}/sessions.png` })

  // 可选:真实 LLM 模式下演示「查订单 → 提交取消申请 → 核验 → 确认执行」
  if (process.env.COMPOUND_DEMO === '1') {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
    await page.waitForSelector('text=智能客服小e', { timeout: 15000 })
    await page.fill('textarea', '查订单 ORDER20260401001 然后帮我取消')
    await page.keyboard.press('Enter')

    await page.waitForSelector('.approval-card', { timeout: 90000 })
    await scrollToBottom()
    const cardText = await page.locator('.approval-card').first().innerText()
    console.log('APPROVAL_PENDING:', cardText.includes('待确认'))
    console.log('APPROVAL_SUMMARY_OK:', cardText.includes('ORDER20260401001'))
    await page.screenshot({ path: `${SHOT_DIR}/chat-cancel.png` })

    await page
      .locator('.approval-card input[aria-label="手机号后四位"]')
      .fill('1234')
    await page.getByRole('button', { name: '核验订单' }).click()
    await page.waitForTimeout(1000)
    await page.locator('.approval-card .ant-btn-primary').first().click()

    await page.waitForSelector('.approval-card.is-closed', { timeout: 30000 })
    await scrollToBottom()
    const closedText = await page.locator('.approval-card').first().innerText()
    console.log('APPROVAL_EXECUTED:', closedText.includes('已执行'))
    await page.screenshot({ path: `${SHOT_DIR}/chat-cancel-executed.png` })
  }

  console.log('PAGE_ERRORS:', errors.length ? JSON.stringify(errors) : 'none')
} finally {
  await browser.close()
}
