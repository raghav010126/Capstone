// End-to-end UI flow against the real stack (Next.js + FastAPI + LangGraph), driven in system Chrome.
//   WEB=http://localhost:3000 node e2e/flow.mjs <screenshot dir>
import { chromium } from "playwright-core"
import fs from "node:fs"
import path from "node:path"

const WEB = process.env.WEB ?? "http://localhost:3000"
const out = process.argv[2] ?? "/tmp/flow"
const DS = path.resolve(process.cwd(), "../data/official/dataset")
const CLUSTER = process.env.CLUSTER ?? "C_003"
fs.mkdirSync(out, { recursive: true })

let failed = 0
const check = (ok, msg) => {
  console.log(`${ok ? "  ok  " : "  FAIL"} ${msg}`)
  if (!ok) failed++
}
const browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true })
const ctx = await browser.newContext({ viewport: { width: 1480, height: 960 }, acceptDownloads: true })
const page = await ctx.newPage()
const problems = []
page.on("console", (m) => m.type() === "error" && problems.push(m.text().slice(0, 200)))
page.on("pageerror", (e) => problems.push(e.message.slice(0, 200)))

async function as(user) {
  await page.goto(`${WEB}/login`)
  await page.evaluate(() => localStorage.clear())   // sign out explicitly: /login redirects home while signed in
  await page.goto(`${WEB}/login`)
  await page.getByRole("button", { name: new RegExp(`${user}$`) }).click()
  await page.waitForURL(`${WEB}/`)
}
const shot = (name, full = false) => page.screenshot({ path: `${out}/${name}.png`, fullPage: full })

// ── 1. submitter uploads a patient's bundle through the drop zone and watches the pipeline ──────────────
console.log(`1. submitter uploads ${CLUSTER}`)
await as("submitter")
await page.getByRole("link", { name: "New case" }).first().click()
await page.waitForURL(/cases\/new/)
const meta = JSON.parse(fs.readFileSync(`${DS}/metadata.json`, "utf8"))
const files = meta.filter((m) => m.case_cluster_id === CLUSTER).map((m) => path.join(DS, m.file_path))
await page.locator('input[type=file]').setInputFiles(files)
check((await page.locator("li", { hasText: ".png" }).count()) === files.length, `${files.length} files listed with previews`)
await shot("10-upload-ready")
await page.getByRole("button", { name: /^Submit/ }).click()
await page.getByText(/^CASE-/).first().waitFor()
const caseId = (await page.getByText(/^CASE-[0-9A-F]{8}$/).first().textContent()).trim()
await page.getByRole("link", { name: /Open case/ }).waitFor({ timeout: 120_000 })
check(true, `case ${caseId} processed; pipeline graph finished`)
check(await page.getByText("Human review").first().waitFor({ state: "visible", timeout: 10_000 }).then(() => true, () => false), "pipeline graph shows the human-review stage")
await shot("11-pipeline-done")
await page.getByRole("link", { name: /Open case/ }).click()

// ── 2. case detail: documents, evidence boxes, agent panels ──────────────────────────────────────────────
console.log("2. case detail")
await page.getByText("Extracted fields").waitFor()
await page.getByRole("tab", { name: /claim form/ }).click()
await page.waitForSelector("img[alt^='Scanned']")
const boxes = await page.locator("button[aria-label^='Field ']").count()
check(boxes > 5, `${boxes} evidence boxes drawn over the claim form`)
await page.locator("tr", { hasText: "total_charge" }).first().click()
await page.waitForTimeout(700)
check((await page.locator("button[aria-label='Field total_charge']").evaluate((el) => el.className)).includes("border-escalate"), "selecting a field highlights its box on the page")
check(await page.getByText("Policy", { exact: true }).first().isVisible(), "policy agent panel with clause citations")
check(await page.getByText("Four-eyes").count() === 0, "no approval banner yet")
await shot("12-case-detail", true)

// ── 3. reviewer overrides; over $10k it needs a second approver ──────────────────────────────────────────
console.log("3. reviewer requests an override")
await as("reviewer")
await page.goto(`${WEB}/review`)
await page.getByText(caseId).first().waitFor()
await shot("13-review-queue")
await page.goto(`${WEB}/cases/view?id=${caseId}`)
// reclassify (to the same type, so replayed model answers still apply): the case re-runs and returns to review
await page.getByRole("button", { name: /Reclassify/ }).click()
await page.getByRole("button", { name: /Reclassify & re-run/ }).click()
await page.getByText(/Re-running the case/).waitFor()
await page.getByText("Waiting for a human reviewer").waitFor({ timeout: 60_000 })
check(true, "reclassify re-ran the case; it is back in review")
await page.getByRole("button", { name: /Override decision/ }).click()
await page.getByText("Over $10,000").waitFor()
check(true, "dialog warns that the amount needs a second approver")
await page.getByRole("combobox", { name: "Reason code" }).click()
await page.getByRole("option", { name: /Additional information/ }).click()
await page.getByLabel(/Note/).fill("Provider confirmed the diagnosis by phone")
await shot("14-override-dialog")
await page.getByRole("button", { name: /Request override/ }).click()
await page.getByText(/Approval pending/).first().waitFor()
check(true, "override is only a request; case still awaits approval")
check(await page.getByText("Four-eyes approval needed").isVisible(), "pending banner shown")
check((await page.getByRole("button", { name: /^Approve$/ }).count()) === 0, "the requester has no approve button")

// ── 4. senior reviewer approves ──────────────────────────────────────────────────────────────────────────
console.log("4. senior reviewer approves")
await as("senior")
await page.goto(`${WEB}/review`)
await page.getByText("Waiting for a second approver").waitFor()
await shot("15-senior-approval")
await page.getByRole("button", { name: /^Approve$/ }).first().click()
await page.getByText(/Approved: the decision is final/).waitFor()
await page.goto(`${WEB}/cases/view?id=${caseId}`)
await page.getByText("Final decision").waitFor()
check(await page.getByText("Reviewed").first().isVisible(), "case is finalized after approval")
check(await page.getByText("a reviewer changed it").isVisible(), "panel shows the automated decision was overridden")
await shot("16-finalized", true)

// ── 5. auditor: chain verified; report downloads ─────────────────────────────────────────────────────────
console.log("5. auditor and report")
await as("auditor")
await page.goto(`${WEB}/audit`)
await page.getByText("Chain verified").waitFor()
await page.getByPlaceholder(/Filter by case id/).fill(caseId)
await page.getByText("override applied").first().waitFor()
check(true, "audit log shows the override chain for the case")
await shot("17-audit")
await page.goto(`${WEB}/cases/view?id=${caseId}`)
const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /Case report/ }).click()])
const file = `${out}/${caseId}-report.pdf`
await dl.saveAs(file)
const bytes = fs.readFileSync(file)
check(bytes.slice(0, 4).toString() === "%PDF" && bytes.length > 20_000, `PDF report downloaded (${Math.round(bytes.length / 1024)} KB)`)

// ── 6. access control in the UI ──────────────────────────────────────────────────────────────────────────
console.log("6. access control")
await as("submitter")
check((await page.getByRole("link", { name: "Audit log" }).count()) === 0, "submitter does not see the audit log in the menu")
await page.goto(`${WEB}/cases/view?id=${caseId}`)
check(await page.getByText("Override decision").count() === 0, "submitter has no override button")

async function denied(route) {
  await page.goto(`${WEB}${route}`)
  const ok = await page.getByText("Your role cannot open this page").waitFor({ timeout: 15_000 }).then(() => true, () => false)
  if (!ok) {
    await shot(`fail-${route.slice(1)}`)
    console.log(`     url=${page.url()} body="${(await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 300)}"`)
  }
  check(ok, `${route} opened by URL shows a no-access message instead of data`)
}
await denied("/audit")
await denied("/insights")

check(problems.length === 0, `no browser console errors${problems.length ? ": " + problems[0] : ""}`)
await browser.close()
console.log(failed ? `\n${failed} check(s) FAILED` : "\nall checks passed")
process.exit(failed ? 1 : 0)
