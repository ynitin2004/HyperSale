// The M1 demo loop in a real browser, against stub providers (D31).
import { expect, test, type Page } from '@playwright/test'
import { createHmac } from 'node:crypto'

const SECRET = process.env.E2E_JWT_SECRET ?? 'e2e-secret-that-is-at-least-32-bytes-long'
const USER_ID = '00000000-0000-4000-8000-0000000000e2'

function token(): string {
  const b64 = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
  const head = b64({ alg: 'HS256', typ: 'JWT' })
  const body = b64({ sub: USER_ID, aud: 'authenticated', email: 'e2e@hypersale.dev', exp: Math.floor(Date.now() / 1000) + 3600 })
  const sig = createHmac('sha256', SECRET).update(`${head}.${body}`).digest('base64url')
  return `${head}.${body}.${sig}`
}

async function signedIn(page: Page) {
  const session = { access_token: token(), refresh_token: 'none', expires_at: Math.floor(Date.now() / 1000) + 3600, email: 'e2e@hypersale.dev' }
  await page.addInitScript((s) => localStorage.setItem('hs.session', JSON.stringify(s)), session)
}

test('signed-out visitors see the sign-in form, not the app', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByTestId('scenario-list')).toHaveCount(0)
})

test('catalog shows five scenarios with one highlighted to try first', async ({ page }) => {
  await signedIn(page)
  await page.goto('/')
  await expect(page.getByTestId('whoami')).toContainText('owner')
  await expect(page.getByTestId('scenario-list').locator('a.scenario')).toHaveCount(5)
  const featured = page.getByTestId('scenario-elena-inbound-follow-up')
  await expect(featured).toContainText('Try this first')
})

test('a full roleplay produces a verified, speaker-labelled report', async ({ page }) => {
  await signedIn(page)
  await page.goto('/')
  await page.getByTestId('scenario-marcus-discovery').click()
  await expect(page.getByTestId('preflight')).toContainText('Demo mode')

  await page.getByTestId('start-call').click()
  await expect(page.getByTestId('call-state')).toHaveText('Live', { timeout: 15_000 })
  const live = page.getByTestId('live-transcript').locator('li.rep, li.buyer')
  await expect(live).toHaveCount(11, { timeout: 20_000 })
  await expect(live.first()).toContainText('Who\'s calling?')

  const ended = Date.now()
  await page.getByTestId('end-call').click()
  await expect(page).toHaveURL(/#\/report\//, { timeout: 15_000 })
  // Deterministic metrics come first, before any model output (PRD: < 1 s after end).
  await expect(page.getByTestId('metrics')).toContainText('Questions asked')
  expect(Date.now() - ended).toBeLessThan(10_000)

  const criteria = page.getByTestId('criteria').locator('article')
  await expect(criteria).toHaveCount(7, { timeout: 30_000 })
  await expect(page.getByTestId('scoring-progress')).toHaveCount(0)
  await expect(page.getByTestId('degraded')).toHaveCount(0)

  // Every quote is attributed to the rep and seeks/highlights its transcript turn.
  const quotes = page.getByTestId('evidence')
  expect(await quotes.count()).toBeGreaterThan(3)
  for (const label of await quotes.locator('.who').allTextContents()) expect(label).toMatch(/^You said/)
  await quotes.first().click()
  await expect(page.getByTestId('transcript').locator('li.hit')).toHaveCount(1)
  await expect(page.getByTestId('transcript').locator('li.hit')).toHaveClass(/rep/)
  await page.keyboard.press('ArrowRight')
  await expect(quotes.nth(1)).toHaveClass(/active/)

  await expect(page.getByTestId('drills').locator('li')).toHaveCount(3)
  await expect(page.getByTestId('provenance')).toContainText('rubric-v1')
  await expect(page.getByTestId('provenance')).toContainText('metrics-v1')
  await expect(page.getByTestId('no-audio')).toBeVisible() // stub calls have no media

  await page.goto('/#/')
  await expect(page.getByTestId('history').locator('tbody tr').first()).toContainText('ready')
})

test('latency dashboard and evidence integrity reflect the calls made', async ({ page }) => {
  await signedIn(page)
  await page.goto('/#/latency')
  await expect(page.getByTestId('stage-connect_ms')).not.toContainText('no data')
  await expect(page.getByTestId('stage-end_to_metrics_ms')).toContainText('within')
  await expect(page.getByTestId('integrity')).toContainText('0 failing')
})

test('a manager compares the team, reviews attempts and assigns a scenario (D39)', async ({ page }) => {
  await signedIn(page)
  await page.goto('/')
  await page.getByRole('link', { name: 'Team' }).click()
  const row = page.getByTestId('team-table').locator('tr', { hasText: 'e2e@hypersale.dev' })
  await expect(row).toBeVisible()
  await row.getByRole('button').click()
  await expect(page.getByTestId('member-attempts').getByRole('link', { name: 'Review →' }).first()).toBeVisible()

  const form = page.getByTestId('assign-form')
  await form.getByLabel('Member').selectOption({ label: 'e2e@hypersale.dev' })
  await form.getByLabel('Scenario').selectOption({ label: 'Warm inbound: follow up on a demo request' })
  await form.getByRole('button', { name: 'Assign' }).click()
  await expect(page.getByTestId('assignment-table')).toContainText('Warm inbound')
  await expect(page.getByTestId('assignment-table')).toContainText('open')

  await page.getByRole('link', { name: 'Practice' }).click()
  await expect(page.getByTestId('my-assignments')).toContainText('Warm inbound')
})

test('the rater page is empty outside the Evals workspace (D37)', async ({ page }) => {
  await signedIn(page)
  await page.goto('/#/rate')
  await expect(page.getByText('No items in this workspace')).toBeVisible()
})
