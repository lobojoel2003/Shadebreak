// Capture the README screenshots from a running demo server.
//   python scripts/demo_server.py --port 8765 &
//   node scripts/screenshots.cjs http://127.0.0.1:8765 docs/images
const { chromium } = require("playwright");
const { mkdirSync } = require("node:fs");
const { join } = require("node:path");

const [base = "http://127.0.0.1:8765", out = "docs/images"] = process.argv.slice(2);
mkdirSync(out, { recursive: true });

async function signedIn(browser, { width, height, language = "en" }) {
  const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, locale: "en-US" });
  const page = await context.newPage();
  await page.goto(`${base}/accounts/login/`);
  await page.fill("#id_username", "demo");
  await page.fill("#id_password", "demo-pass-123");
  await Promise.all([page.waitForURL(`${base}/`), page.click("form.form button[type=submit]")]);
  if (language !== "en") {
    await Promise.all([page.waitForLoadState("load"), page.click(`.lang-switch button[value=${language}]`)]);
  }
  return { context, page };
}

async function shoot(page, path, file, { full = false, clip } = {}) {
  await page.goto(`${base}${path}`);
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: join(out, file), fullPage: full, clip });
  console.log("saved", file);
}

(async () => {
const browser = await chromium.launch();

// Phone, English: the crew lead's morning screen and the other tabs.
{
  const { context, page } = await signedIn(browser, { width: 390, height: 844 });
  await shoot(page, "/", "dashboard-mobile.png");
  await page.evaluate(() => document.querySelector("#site-1, article.site-card").scrollIntoView());
  await page.evaluate(() => window.scrollBy(0, 560));
  await page.screenshot({ path: join(out, "dashboard-mobile-crew.png") });
  console.log("saved dashboard-mobile-crew.png");
  await shoot(page, "/crew/", "crew-mobile.png");
  // One worker's conversation (Luis gets his texts in Spanish).
  await page.goto(`${base}/messages/`);
  await Promise.all([page.waitForURL(/worker=/), page.selectOption("#thread", { label: "Luis Ortega" })]);
  await page.screenshot({ path: join(out, "texts-thread-mobile.png") });
  console.log("saved texts-thread-mobile.png");
  await context.close();
}

// Phone, Spanish.
{
  const { context, page } = await signedIn(browser, { width: 390, height: 844, language: "es" });
  await shoot(page, "/", "dashboard-mobile-es.png");
  await context.close();
}

// Desktop.
{
  const { context, page } = await signedIn(browser, { width: 1360, height: 980 });
  await shoot(page, "/", "dashboard-desktop.png");
  await context.close();
}

await browser.close();
})();
