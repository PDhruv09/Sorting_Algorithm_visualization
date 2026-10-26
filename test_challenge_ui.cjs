const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

async function loadPage(status, payload) {
    const elements = new Map();
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, {
            hidden: id === "error", disabled: id === "start", textContent: "",
            addEventListener() {}, focus() {}, replaceChildren() {}, append() {},
        });
        return elements.get(id);
    };
    const context = vm.createContext({
        document: { getElementById: element },
        clearTimeout,
        window: { addEventListener() {} },
        fetch: async () => {
            if (status === 0) throw new Error("Network unavailable");
            return { ok: status === 200, status, json: async () => payload };
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "static", "challenge.js"), "utf8"), context);
    await new Promise((resolve) => setImmediate(resolve));
    return { element, context };
}

test("completed attempts show total score without unreleased feedback", async () => {
    const payload = { status: "submitted", email: "tester@ucsd.edu", score: 29, max_score: 30 };
    const { element, context } = await loadPage(200, payload);
    assert.equal(element("results").hidden, false);
    assert.equal(element("challenge").hidden, true);
    assert.equal(element("access").hidden, true);
    assert.equal(element("intro-title").textContent, "Thank you for participating.");
    assert.equal(element("intro-subtitle").textContent, "You can now leave the challenge or return to the visualizer.");
    assert.equal(element("score").textContent, "Score: 29 / 30");
    assert.equal(element("feedback").hidden, true);
    vm.runInContext('render({ status: "submitted", email: "tester@ucsd.edu" })', context);
    assert.equal(element("notice").textContent, "");
    const html = fs.readFileSync(path.join(__dirname, "static", "challenge.html"), "utf8");
    assert.match(html, /Your response has been stored\./);
    assert.match(html, /id="reasoning-choices"/);
    vm.runInContext("renderIntro()", context);
    assert.equal(element("intro-title").textContent, "Read the movements.");
    assert.match(element("intro-subtitle").textContent, /Watch the array/);
});

for (const [status, payload] of [[404, { detail: "Not found." }],
                                [405, { detail: "Method Not Allowed" }],
                                [503, { code: "challenge_unavailable", detail: "Disabled" }]]) {
    test(`unavailable backend (${status}) explains setup and prevents email submission`, async () => {
        const { element } = await loadPage(status, payload);
        assert.equal(element("error").hidden, true);
        assert.match(element("notice").textContent, /not available on this server/);
        assert.equal(element("start").disabled, true);
        assert.equal(element("email").disabled, true);
    });
}

test("enabled backend without a session shows the normal email form", async () => {
    const { element } = await loadPage(401, { detail: "Enter your email to start or resume your challenge." });
    assert.equal(element("error").hidden, true);
    assert.equal(element("notice").textContent, "");
    assert.equal(element("start").disabled, false);
    assert.equal(element("email").disabled, false);
});

test("a database save failure is not mislabeled as disabled Challenge Mode", async () => {
    const { element } = await loadPage(503, { detail: "Your response could not be saved. Keep this page open and try again." });
    assert.equal(element("error").hidden, false);
    assert.match(element("error").textContent, /could not be saved/);
    assert.equal(element("notice").textContent, "");
});

test("invalid email shows only email guidance, never answer-field instructions", async () => {
    const { element, context } = await loadPage(422, { detail: [{ loc: ["body", "email"], msg: "Invalid email" }] });
    await vm.runInContext('api("/access", "POST", { email: "student@gmail.com" }).catch(showError)', context);
    assert.equal(element("error").textContent, "Enter a valid UCSD email address ending in @ucsd.edu.");
    assert.doesNotMatch(element("error").textContent, /reasoning|answer fields|4000/i);
});

test("invalid answer shows answer guidance without suggesting an email problem", async () => {
    const { element, context } = await loadPage(422, { detail: [{ loc: ["body", "reasoning"], msg: "Too short" }] });
    await vm.runInContext('api("/answers/0", "PUT", {}).catch(showError)', context);
    assert.match(element("error").textContent, /Choose a sorting algorithm and complete the reasoning answer/);
    assert.doesNotMatch(element("error").textContent, /email|ucsd/i);
});

test("invalid final submission uses submission-specific guidance", async () => {
    const { element, context } = await loadPage(422, { detail: [{ loc: ["body", "revision"], msg: "Required" }] });
    await vm.runInContext('api("/submit", "POST", {}).catch(showError)', context);
    assert.match(element("error").textContent, /submission could not be validated/);
    assert.doesNotMatch(element("error").textContent, /email|reasoning/i);
});

test("an unauthorized UCSD email keeps the access-denied message", async () => {
    const message = "Access denied. This email is not authorized for Challenge Mode.";
    const { element, context } = await loadPage(403, { detail: message });
    await vm.runInContext('api("/access", "POST", { email: "unknown@ucsd.edu" }).catch(showError)', context);
    assert.equal(element("error").textContent, message);
});

test("a connection failure on the email screen does not claim answers exist", async () => {
    const { element, context } = await loadPage(0, {});
    await vm.runInContext('api("/access", "POST", {}).catch(showError)', context);
    assert.equal(element("error").textContent, "Could not connect. Check your connection and try again.");
    assert.doesNotMatch(element("error").textContent, /answers|saving/i);
});
