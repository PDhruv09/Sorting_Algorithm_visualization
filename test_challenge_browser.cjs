// Run against an isolated local server seeded with browser-check@ucsd.edu.
// NODE_PATH can point at the bundled Playwright installation.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.CHALLENGE_BROWSER_EXECUTABLE || undefined });
    try {
        const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
        const errors = [];
        page.on("pageerror", error => errors.push(error.message));
        const base = process.env.CHALLENGE_BROWSER_URL || "http://127.0.0.1:18081";
        assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
        await page.goto(`${base}/challenge`);
        await page.locator("#email").fill("unauthorized@ucsd.edu");
        await page.locator("#start").click();
        await page.getByText("Access denied. This email is not authorized for Challenge Mode.", { exact: true }).waitFor();
        await page.locator("#email").fill("browser-check@ucsd.edu");
        await page.locator("#start").click();
        await page.getByText("Question 1 of 15", { exact: true }).waitFor();
        assert.equal(await page.locator("#reasoning").isVisible(), false);
        assert.equal(await page.locator("#reasoning-options input").count(), 6);
        await page.locator("#identification").selectOption("insertion");
        const firstChoice = await page.locator("#reasoning-options input").first().getAttribute("value");
        await page.locator("#reasoning-options input").first().check();
        await page.locator("#next").click();
        await page.getByText("Question 2 of 15", { exact: true }).waitFor();
        await page.reload();
        await page.getByText("Question 2 of 15", { exact: true }).waitFor();
        await page.locator("#previous").click();
        await page.getByText("Question 1 of 15", { exact: true }).waitFor();
        assert.equal(await page.locator("#reasoning-options input:checked").inputValue(), firstChoice);
        await page.locator("#next").click();
        for (let number = 2; number <= 15; number++) {
            await page.getByText(`Question ${number} of 15`, { exact: true }).waitFor();
            await page.locator("#identification").selectOption("insertion");
            await page.locator("#reasoning-options input").first().check();
            await page.locator("#next").click();
        }
        await page.locator("#results").waitFor();
        const score = await page.locator("#score").textContent();
        assert.match(score, /^Score: \d+ \/ 30$/);
        assert.equal(await page.locator("#feedback").isVisible(), false);
        await page.reload();
        await page.locator("#results").waitFor();
        assert.equal(await page.locator("#score").textContent(), score);
        const response = await page.request.get(`${base}/api/challenge/current?feedback=true`);
        const result = await response.json();
        assert.equal(result.feedback, undefined);
        assert.equal(result.answers, undefined);
        assert.equal(result.questions, undefined);
        assert.deepEqual(errors, []);
        console.log("Browser passed: unauthorized access, 15 radio-choice answers, refresh/resume, saved selections, score-only completion, no script errors.");
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
