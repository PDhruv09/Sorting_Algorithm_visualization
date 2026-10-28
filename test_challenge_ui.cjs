const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

async function loadPage(status, payload) {
    const elements = new Map();
    const documentEvents = new Map();
    const makeElement = (id) => ({
        hidden: id === "error", disabled: id === "start", textContent: "", value: "",
        style: {}, events: new Map(), children: [],
        addEventListener(name, handler) { this.events.set(name, handler); },
        focus() {}, setAttribute() {},
        replaceChildren(...children) { this.children = children; },
        append(...children) { this.children.push(...children); },
        querySelectorAll() { return this.children.flatMap((child) => child.children || []); },
    });
    const element = (id) => {
        if (!elements.has(id)) elements.set(id, makeElement(id));
        return elements.get(id);
    };
    const document = {
        visibilityState: "visible", getElementById: element,
        createElement: (tag) => makeElement(tag),
        addEventListener: (name, handler) => documentEvents.set(name, handler),
    };
    const context = vm.createContext({
        document,
        Option: function(text, value) { return { textContent: text, value }; },
        clearTimeout,
        setTimeout: (callback) => { callback(); return 1; },
        window: { addEventListener() {} },
        fetch: async () => {
            if (status === 0) throw new Error("Network unavailable");
            return { ok: status === 200, status, json: async () => payload };
        },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "static", "challenge.js"), "utf8"), context);
    await new Promise((resolve) => setImmediate(resolve));
    return { element, context, documentEvents };
}

test("session check recovers from 503 without replacing an unsaved choice", async () => {
    const { element, context } = await loadPage(401, {});
    vm.runInContext('state = { email: "tester@ucsd.edu", question: { number: 3 } }; dirty = true;', context);
    element("identification").value = "merge";
    element("notice").textContent = "Your answer has not been saved.";
    let calls = 0;
    const delays = [];
    context.setTimeout = (callback, delay) => {
        delays.push(delay);
        assert.match(element("notice").textContent, /Reconnecting/);
        callback();
    };
    context.fetch = async () => {
        calls++;
        return { ok: calls === 3, status: calls === 3 ? 200 : 503, json: async () => ({}) };
    };
    await vm.runInContext('checkSessionOnReturn()', context);
    assert.equal(calls, 3);
    assert.deepEqual(delays, [5000, 10000]);
    assert.equal(element("identification").value, "merge");
    assert.equal(vm.runInContext("dirty", context), true);
    assert.equal(element("notice").textContent, "Your answer has not been saved.");
    assert.equal(element("error").hidden, true);
});

test("503 session recovery stops on 401 and keeps the draft for email reentry", async () => {
    const { element, context } = await loadPage(401, {});
    vm.runInContext('state = { email: "tester@ucsd.edu", question: { number: 3 } }; dirty = true;', context);
    element("identification").value = "quick";
    let calls = 0;
    context.fetch = async () => ({ ok: false, status: ++calls === 1 ? 503 : 401,
        json: async () => ({ detail: "Your session has ended." }) });
    await vm.runInContext('checkSessionOnReturn()', context);
    assert.equal(calls, 2);
    assert.equal(element("challenge").hidden, true);
    assert.equal(element("email").value, "tester@ucsd.edu");
    assert.equal(vm.runInContext("pendingDraft.identification", context), "quick");
});

test("failed access, answer saves and final submission are never automatically replayed", async () => {
    const { context } = await loadPage(401, {});
    for (const [route, method] of [["/access", "POST"], ["/answers/0", "PUT"], ["/submit", "POST"]]) {
        let calls = 0;
        context.fetch = async () => { calls++; return { ok: false, status: 503, json: async () => ({}) }; };
        await assert.rejects(vm.runInContext(`api(${JSON.stringify(route)}, ${JSON.stringify(method)}, {})`, context));
        assert.equal(calls, 1);
    }
});

test("completed attempts show total score without unreleased feedback", async () => {
    const payload = { status: "submitted", email: "tester@ucsd.edu", score: 14, max_score: 15 };
    const { element, context } = await loadPage(200, payload);
    assert.equal(element("results").hidden, false);
    assert.equal(element("challenge").hidden, true);
    assert.equal(element("access").hidden, true);
    assert.equal(element("intro-title").textContent, "Thank you for participating.");
    assert.equal(element("intro-subtitle").textContent, "You can now leave the challenge or return to the visualizer.");
    assert.equal(element("score").textContent, "Score: 14 / 15");
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

function fourSortPayload() {
    return { status: "in_progress", email: "tester@ucsd.edu", attempt_id: "new-four-sort-attempt",
        test_version: "sorting-15-v3", points_per_question: 1, total: 15, saved_count: 0,
        options: { insertion: "Insertion sort", selection: "Selection sort", quick: "Quick sort", merge: "Merge sort" },
        question: { number: 1, frames: [{ values: [3, 1, 2], active: [], action: "ready" }],
            reasoning_choices: ["Ordered prefix", "Selected minimum", "Pivot partition", "Merged ranges"].map((text, index) => ({id: `new-${index}`, text})) } };
}

test("four-sort page offers four choices and states one whole point per question", async () => {
    const { element } = await loadPage(200, fourSortPayload());
    assert.deepEqual(Array.from(element("identification").children, child => child.value),
        ["", "insertion", "selection", "quick", "merge"]);
    assert.equal(element("reasoning-options").children.length, 4);
    assert.match(element("reasoning-help").textContent, /One point per question/);
    assert.doesNotMatch(element("reasoning-help").textContent, /0\.5|half/);
});

test("old-version unsaved choices are not applied to a new four-sort attempt", async () => {
    const { element, context } = await loadPage(401, {});
    vm.runInContext('pendingDraft = {email: "tester@ucsd.edu", attempt_id: "old-attempt", position: 8, identification: "bucket", reasoning: "old-choice"}', context);
    element("email").value = "tester@ucsd.edu";
    const calls = [];
    context.fetch = async (url) => { calls.push(url); return { ok: true, status: 200, json: async () => fourSortPayload() }; };
    await element("access-form").events.get("submit")({preventDefault() {}});
    assert.deepEqual(calls, ["/api/challenge/access"]);
    assert.equal(element("identification").value, "");
    assert.equal(element("reasoning").value, "");
    assert.equal(vm.runInContext("dirty", context), false);
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

test("an expired session hides the question and score before showing the email form", async () => {
    const message = "Your session has ended. Enter your email to resume your saved challenge.";
    const { element, context } = await loadPage(401, { detail: message });
    vm.runInContext('state = { email: "tester@ucsd.edu", question: { number: 5 } }; dirty = true;', context);
    element("access").hidden = true;
    element("challenge").hidden = false;
    element("results").hidden = false;
    element("signout").hidden = false;
    element("student").textContent = "tester@ucsd.edu";
    await vm.runInContext('api("/current").catch(showError)', context);
    assert.equal(element("access").hidden, false);
    assert.equal(element("challenge").hidden, true);
    assert.equal(element("results").hidden, true);
    assert.equal(element("signout").hidden, true);
    assert.equal(element("student").textContent, "");
    assert.equal(element("email").value, "tester@ucsd.edu");
    assert.equal(element("error").textContent, message);
    assert.equal(vm.runInContext("state", context), null);
    assert.equal(vm.runInContext("dirty", context), false);
});

test("a database save failure is not mislabeled as disabled Challenge Mode", async () => {
    const { element } = await loadPage(503, { detail: "Your response could not be saved. Keep this page open and try again." });
    assert.equal(element("error").hidden, false);
    assert.match(element("error").textContent, /database is temporarily unavailable/);
    assert.equal(element("start").disabled, false);
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
    assert.equal(element("start").disabled, false);
    await vm.runInContext('api("/access", "POST", {}).catch(showError)', context);
    assert.equal(element("error").textContent, "Could not connect. Check your connection and try again.");
    assert.doesNotMatch(element("error").textContent, /answers|saving/i);
});

test("returning after another device ends the session hides the question and retains an unsaved draft", async () => {
    const { element, context, documentEvents } = await loadPage(401, { detail: "Your session has ended. Enter your email to resume your saved challenge." });
    vm.runInContext('state = { email: "tester@ucsd.edu", question: { number: 5 } }; dirty = true;', context);
    element("access").hidden = true;
    element("challenge").hidden = false;
    element("identification").value = "merge";
    element("reasoning").value = "choice-5";
    documentEvents.get("visibilitychange")();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(element("challenge").hidden, true);
    assert.equal(element("access").hidden, false);
    assert.equal(element("email").value, "tester@ucsd.edu");
    assert.equal(vm.runInContext("pendingDraft.identification", context), "merge");
    assert.equal(vm.runInContext("pendingDraft.reasoning", context), "choice-5");
});

test("returning after temporary database unavailability keeps the current unsaved answer", async () => {
    const { element, context, documentEvents } = await loadPage(503, { detail: "Challenge data is temporarily unavailable. Keep this page open and try again." });
    vm.runInContext('state = { email: "tester@ucsd.edu", question: { number: 5 } }; dirty = true;', context);
    element("access").hidden = true;
    element("challenge").hidden = false;
    element("identification").value = "merge";
    documentEvents.get("visibilitychange")();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(element("challenge").hidden, false);
    assert.equal(element("identification").value, "merge");
    assert.equal(vm.runInContext("dirty", context), true);
    assert.match(element("error").textContent, /temporarily unavailable/);
});

test("step back moves one frame and stops at the first frame without exposing an array text control", async () => {
    const { element, context } = await loadPage(401, { detail: "Enter your email." });
    vm.runInContext('state = { question: { frames: [{ values: [2, 1], active: [], action: "ready" }, { values: [1, 2], active: [], action: "swap" }] } }; frameIndex = 1;', context);
    element("step-back").events.get("click")();
    assert.equal(vm.runInContext("frameIndex", context), 0);
    assert.equal(element("step-back").disabled, true);
    assert.equal(element("step").disabled, false);
    const html = fs.readFileSync(path.join(__dirname, "static", "challenge.html"), "utf8");
    assert.match(html, /id="step-back"/);
    assert.doesNotMatch(html, /array-text|View current array as text/);
});
