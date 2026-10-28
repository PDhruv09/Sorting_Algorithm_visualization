"use strict";

const element = (id) => document.getElementById(id);
let state = null;
let options = {};
let frameIndex = 0;
let timer = null;
let dirty = false;
let busy = false;
let backendAvailable = true;
let pendingDraft = null;
let checkingSession = false;

function validationMessage(path) {
    if (path === "/access") return "Enter a valid UCSD email address ending in @ucsd.edu.";
    if (path.startsWith("/answers/")) return "Choose a sorting algorithm and complete the reasoning answer.";
    if (path === "/submit") return "Your submission could not be validated. Reload the page and try again.";
    return "Could not load this question. Reload the page and try again.";
}

async function api(path, method = "GET", body) {
    // Only repeat the read-only session check. Never replay access, saves or submit.
    const delays = [5000, 10000, 20000, 30000];
    const retryDeadline = Date.now() + 90000;
    const previousNotice = element("notice").textContent;
    const reconnecting = "Reconnecting to your challenge. This can take about a minute. Keep this page open; any unsaved choices will stay here.";
    try {
        for (let attempt = 0; ; attempt++) {
            try {
                return await request(path, method, body);
            } catch (error) {
                if (method !== "GET" || !path.startsWith("/current") ||
                    error.status !== 503 || error.unavailable || attempt >= delays.length ||
                    Date.now() + delays[attempt] >= retryDeadline) throw error;
                element("notice").textContent = reconnecting;
                await new Promise((resolve) => setTimeout(resolve, delays[attempt]));
            }
        }
    } finally {
        if (element("notice").textContent === reconnecting) element("notice").textContent = previousNotice;
    }
}

async function request(path, method = "GET", body) {
    let response;
    try {
        response = await fetch(`/api/challenge${path}`, {
            method, credentials: "same-origin", cache: "no-store",
            headers: { "Content-Type": "application/json", "X-Challenge-Request": "1" },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
    } catch {
        throw new Error(path === "/access" || !state ?
            "Could not connect. Check your connection and try again." :
            "Connection lost. Your answers are still on this page. Try saving again.");
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        const unavailable = response.status === 404 || response.status === 405 || result.code === "challenge_unavailable";
        if (unavailable) backendAvailable = false;
        if (response.status === 401) backendAvailable = true;
        if (response.status === 401 && state) {
            const email = state.email;
            if (dirty && state.question) pendingDraft = {
                email, attempt_id: state.attempt_id, position: state.question.number - 1,
                identification: element("identification").value,
                reasoning: element("reasoning").value,
            };
            stopPlayback();
            state = null;
            dirty = false;
            renderIntro();
            element("access").hidden = false;
            element("challenge").hidden = true;
            element("results").hidden = true;
            element("signout").hidden = true;
            element("student").textContent = "";
            element("notice").textContent = "";
            element("email").value = email;
        }
        const message = unavailable ? "Challenge Mode is not available on this server yet. Please return once it has been enabled." :
            response.status === 503 && (path === "/access" || !state) ? "Could not start or resume your challenge because the database is temporarily unavailable. Please try again." :
            typeof result.detail === "string" ? result.detail :
            response.status === 422 ? validationMessage(path) :
            path === "/access" ? "Could not check access. Please try again." : "Could not save. Please try again.";
        const error = new Error(message);
        error.status = response.status;
        error.unavailable = unavailable;
        throw error;
    }
    backendAvailable = true;
    return result;
}

function showError(error) {
    if (error.unavailable) {
        element("notice").textContent = error.message;
        element("error").hidden = true;
        element("email").disabled = true;
        element("start").disabled = true;
        element("start").textContent = "Challenge unavailable";
        return;
    }
    element("error").textContent = error.message;
    element("error").hidden = false;
}

function setBusy(value) {
    busy = value;
    element("start").disabled = value || !backendAvailable;
    for (const id of ["next", "previous", "signout"]) element(id).disabled = value;
    element("identification").disabled = value;
    element("reasoning").disabled = value;
    element("reasoning-choices").disabled = value;
    if (!value && state?.question) element("previous").disabled = state.question.number === 1;
}

function stopPlayback() {
    clearTimeout(timer);
    timer = null;
    element("play").textContent = "Play";
}

function drawFrame() {
    const frames = state.question.frames;
    const frame = frames[frameIndex];
    const maximum = Math.max(...frames[0].values);
    const bars = frame.values.map((value, index) => {
        const bar = document.createElement("div");
        bar.className = `bar ${frame.action === "complete" ? "complete" : frame.active.includes(index) ? frame.action : ""}`;
        bar.style.height = `${value / maximum * 90}%`;
        const label = document.createElement("span");
        label.textContent = value;
        bar.append(label);
        return bar;
    });
    element("bars").replaceChildren(...bars);
    element("bars").setAttribute("aria-label", `Sorting animation frame ${frameIndex + 1} of ${frames.length}: ${frame.action}.`);
    element("action").textContent = { ready: "Ready to play", compare: "Comparing highlighted positions", swap: "Swapping highlighted positions", write: "Writing a value", read: "Reading a value", complete: "Animation complete" }[frame.action];
    element("frame-count").textContent = `Frame ${frameIndex + 1} / ${frames.length}`;
    element("step").disabled = frameIndex === frames.length - 1;
    element("step-back").disabled = frameIndex === 0;
}

function advance() {
    if (frameIndex < state.question.frames.length - 1) {
        frameIndex += 1;
        drawFrame();
        timer = setTimeout(advance, Number(element("speed").value));
    } else stopPlayback();
}

function renderIntro(submitted = false) {
    element("intro-eyebrow").textContent = submitted ? "CHALLENGE COMPLETE" : "OBSERVE. IDENTIFY. EXPLAIN.";
    element("intro-title").textContent = submitted ? "Thank you for participating." : "Read the movements.";
    element("intro-subtitle").textContent = submitted ?
        "You can now leave the challenge or return to the visualizer." :
        "Watch the array, recognize the pattern, and tell us how you know.";
}

function render(result, focus = true) {
    stopPlayback();
    state = result;
    renderIntro(result.status === "submitted");
    options = result.options || options;
    dirty = false;
    element("access").hidden = true;
    element("error").hidden = true;
    element("student").textContent = result.email;
    element("signout").hidden = false;
    element("challenge").hidden = result.status === "submitted";
    element("results").hidden = result.status !== "submitted";
    if (result.status === "submitted") {
        element("notice").textContent = "";
        element("score").textContent = `Score: ${result.score} / ${result.max_score}`;
        element("feedback").replaceChildren();
        element("feedback").hidden = !result.feedback;
        element("feedback-status").textContent = result.feedback ? "Detailed feedback is now available below." : "Detailed feedback will be available after course staff release it.";
        for (const item of result.feedback?.questions || []) {
            const card = document.createElement("section");
            card.className = "card feedback-item";
            for (const text of [`Question ${item.number}`, ...(item.points === undefined ? [] : [`Credit: ${item.points} / 1`]), `Your algorithm: ${item.selected_answer}`, `Correct algorithm: ${item.correct_answer}`, `Your reasoning: ${item.reasoning}`, item.explanation]) {
                const paragraph = document.createElement("p");
                paragraph.textContent = text;
                card.append(paragraph);
            }
            element("feedback").append(card);
        }
        if (focus) element("results-title").focus();
        return;
    }
    element("question-number").textContent = `Question ${result.question.number} of ${result.total}`;
    element("saved-count").textContent = `${result.saved_count} of ${result.total} answers saved`;
    element("progress").value = result.saved_count;
    element("progress").max = result.total;
    const placeholder = new Option("Choose an algorithm", "");
    element("identification").replaceChildren(placeholder, ...Object.entries(options).map(([value, label]) => new Option(label, value)));
    element("identification").value = result.answer?.identification || "";
    element("reasoning").value = result.answer?.reasoning || "";
    const choices = result.question.reasoning_choices;
    element("reasoning").hidden = !!choices;
    element("reasoning").required = !choices;
    element("reasoning-label").hidden = !!choices;
    element("character-count").hidden = !!choices;
    element("reasoning-choices").hidden = !choices;
    element("reasoning-help").textContent = choices ?
        (result.points_per_question === 1 ? "One point per question when the algorithm and reasoning are both correct." :
            "One point for identification and one point for reasoning.") : "Written reasoning is saved for review.";
    element("reasoning-options").replaceChildren(...(choices || []).map((choice) => {
        const label = document.createElement("label");
        label.className = "reason-choice";
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "reason-choice";
        radio.value = choice.id;
        radio.required = true;
        radio.checked = choice.id === element("reasoning").value;
        radio.addEventListener("change", () => { element("reasoning").value = choice.id; markDirty(); });
        const text = document.createElement("span");
        text.textContent = choice.text;
        label.append(radio, text);
        return label;
    }));
    element("character-count").textContent = `${element("reasoning").value.length} / 4000`;
    element("save-status").textContent = result.answer ? "This answer is saved. You can edit it before final submission." : "Your answer will save when you continue.";
    element("next").textContent = result.question.number === result.total ? "Submit challenge" : "Save & next →";
    element("previous").disabled = result.question.number === 1;
    frameIndex = 0;
    drawFrame();
    if (focus) element("question-number").focus();
}

element("access-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const draft = dirty && state?.question ? { email: state.email, attempt_id: state.attempt_id, position: state.question.number - 1, identification: element("identification").value, reasoning: element("reasoning").value } : pendingDraft;
    setBusy(true);
    try {
        let result = await api("/access", "POST", { email: element("email").value.trim() });
        if (draft && draft.email === result.email && draft.attempt_id === result.attempt_id && result.status === "in_progress") {
            result = await api(`/current?position=${draft.position}`);
        }
        render(result);
        if (draft && draft.email === result.email && draft.attempt_id === result.attempt_id && result.status === "in_progress") {
            element("identification").value = draft.identification;
            element("reasoning").value = draft.reasoning;
            for (const radio of element("reasoning-options").querySelectorAll("input")) radio.checked = radio.value === draft.reasoning;
            markDirty();
        }
        pendingDraft = null;
        if (result.status === "in_progress") element("notice").textContent = result.saved_count ? "Welcome back. Your saved challenge has resumed." : "Your challenge has begun. Watch the animation, then answer below.";
    } catch (error) { showError(error); }
    finally { setBusy(false); }
});

element("answer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !state) return;
    const reasoning = element("reasoning").value.trim();
    if (!reasoning) return showError(new Error(state.question.reasoning_choices ? "Choose a reason before continuing." : "Explain the movements that led you to your answer."));
    const position = state.question.number - 1;
    setBusy(true);
    element("error").hidden = true;
    element("save-status").textContent = "Saving your response…";
    try {
        const saved = await api(`/answers/${position}`, "PUT", { identification: element("identification").value, reasoning, revision: state.revision });
        state.revision = saved.revision;
        dirty = false;
        if (position === state.total - 1) {
            render(await api("/submit", "POST", { revision: saved.revision }));
        } else {
            render(saved.question.number === position + 2 ? saved : await api(`/current?position=${position + 1}`));
            element("notice").textContent = `Question ${position + 1} saved.`;
        }
    } catch (error) {
        element("save-status").textContent = error.status === 401 ?
            "Session ended. Sign in again to retry this unsaved answer." :
            dirty ? "Not saved. Your answer is still here; please retry." :
                "Answer saved. Please retry to finish continuing or submitting.";
        showError(error);
    } finally { setBusy(false); }
});

element("previous").addEventListener("click", async () => {
    if (busy || (dirty && !window.confirm("This answer has unsaved edits. Go back without saving those edits?"))) return;
    setBusy(true);
    try { render(await api(`/current?position=${state.question.number - 2}`)); }
    catch (error) { showError(error); }
    finally { setBusy(false); }
});

function markDirty() {
    dirty = true;
    element("character-count").textContent = `${element("reasoning").value.length} / 4000`;
    element("save-status").textContent = "Unsaved changes — select Next or Submit challenge to save.";
}

element("reasoning").addEventListener("input", markDirty);
element("identification").addEventListener("change", markDirty);
element("play").addEventListener("click", () => {
    if (timer) return stopPlayback();
    if (frameIndex === state.question.frames.length - 1) { frameIndex = 0; drawFrame(); }
    element("play").textContent = "Pause";
    timer = setTimeout(advance, Number(element("speed").value));
});
element("step").addEventListener("click", () => { stopPlayback(); frameIndex = Math.min(frameIndex + 1, state.question.frames.length - 1); drawFrame(); });
element("step-back").addEventListener("click", () => { stopPlayback(); frameIndex = Math.max(frameIndex - 1, 0); drawFrame(); });
element("replay").addEventListener("click", () => { stopPlayback(); frameIndex = 0; drawFrame(); });
element("signout").addEventListener("click", async () => {
    if (busy || (dirty && !window.confirm("Leave without saving the edits on this question? Earlier saved answers will be kept."))) return;
    setBusy(true);
    try {
        await api("/session", "DELETE");
        stopPlayback();
        state = null;
        pendingDraft = null;
        renderIntro();
        dirty = false;
        element("access").hidden = false;
        for (const id of ["challenge", "results", "signout", "error"]) element(id).hidden = true;
        element("student").textContent = "";
        element("notice").textContent = "You have left the challenge. Previously saved responses are kept.";
        element("email").focus();
    } catch (error) { showError(error); }
    finally { setBusy(false); }
});
window.addEventListener("beforeunload", (event) => { if (dirty || pendingDraft) { event.preventDefault(); event.returnValue = ""; } });

async function checkSessionOnReturn() {
    if (!state || busy || checkingSession) return;
    checkingSession = true;
    setBusy(true);
    try {
        await api("/current");
        element("error").hidden = true;
    } catch (error) {
        showError(error);
    } finally {
        checkingSession = false;
        setBusy(false);
    }
}

document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkSessionOnReturn();
});

setBusy(true);
api("/current").then((result) => {
    render(result, false);
    if (result.status === "in_progress") element("notice").textContent = "Your saved challenge has resumed.";
}).catch((error) => {
    if (error.status !== 401) showError(error);
}).finally(() => setBusy(false));
