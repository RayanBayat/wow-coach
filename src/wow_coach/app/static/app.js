"use strict";

// The wow-coach window. Plain JavaScript, no libraries, no build step.
//
// SAFETY RULE: the answers come from an AI, so they are untrusted text. Text is only ever put
// on the page with `textContent` (through the small `make` helper below), which shows
// characters as characters and never as page code. Do not change that.

const SIGN_IN_PAGE_START = "https://auth.openai.com/";
const NEXT_QUESTION = "What should I do next?";

let state = null; // the last state the server sent
let selectedCharacter = null;
// The session secret is sent in a header by this page only. It is never a cookie (cookies
// ignore ports, so any other program on 127.0.0.1 would get it). It is kept in memory and in
// sessionStorage: that belongs to this tab and this exact address (including the port), is
// never sent by the browser by itself, and lets a reload keep the session.
let sessionSecret = null;
let serverInstance = null; // an id of THIS wow-coach run; a different one means another program
let gaveUp = false; // true once we know wow-coach is gone: stop asking
let eventFailures = 0;
const STORAGE_KEY = "wow-coach-session";
const MAX_EVENT_FAILURES = 10;
const SESSION_GONE = "Press Enter in the wow-coach terminal for a new link, then open it.";
const CLOSED = "wow-coach was closed. Start it again from the terminal.";

const $ = (id) => document.getElementById(id);

// ---- small helpers ---------------------------------------------------------------

/** Make an element holding plain text. */
function make(tag, text, className) {
  const element = document.createElement(tag);
  if (text) {
    element.textContent = text;
  }
  if (className) {
    element.className = className;
  }
  return element;
}

function formatTime(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString() : "";
}

/** Talk to the server. Resolves to {ok, status, data}; never throws for HTTP errors. */
function rememberSession() {
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ secret: sessionSecret, instance: serverInstance }),
    );
  } catch (error) {
    // Storage may be blocked (private window): the session then lasts until a reload.
  }
}

function recallSession() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null");
    if (saved && typeof saved.secret === "string") {
      sessionSecret = saved.secret;
      serverInstance = saved.instance || null;
    }
  } catch (error) {
    sessionSecret = null;
  }
}

function forgetSession() {
  sessionSecret = null;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch (error) {
    // Nothing to do.
  }
}

/** Stop talking to the server for good and tell the player why. */
function giveUp(message) {
  gaveUp = true;
  showBanner(message, true);
}

async function api(path, method, body) {
  if (!sessionSecret && path !== "/api/session") {
    return { ok: false, status: 401, data: { error: SESSION_GONE } };
  }
  const options = { method, credentials: "omit", headers: {} };
  if (sessionSecret) {
    options.headers["X-Wow-Coach-Session"] = sessionSecret;
  }
  if (method === "POST") {
    options.headers["X-Wow-Coach"] = "1"; // a custom header: other sites cannot send it
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body || {});
  }
  try {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (response.status === 401 && path !== "/api/session") {
      forgetSession(); // the server does not know this session any more
    }
    return { ok: response.ok, status: response.status, data };
  } catch (error) {
    return { ok: false, status: 0, data: { error: "wow-coach is not running any more." } };
  }
}

/** Show a message at the top. `isLimit` adds the "Manage usage" button (usage limit hit). */
function showBanner(message, isError, isLimit) {
  const banner = $("banner");
  $("banner-text").textContent = message;
  $("banner-link").hidden = !isLimit;
  banner.className = isError ? "banner error" : "banner";
  banner.hidden = !message;
}

function showThinking(on) {
  $("thinking").hidden = !on;
  $("ask-button").disabled = on;
  $("next-button").disabled = on;
  $("answer-now").disabled = on;
}

// ---- screens ------------------------------------------------------------------

function showScreen(name) {
  for (const screen of document.querySelectorAll(".screen")) {
    screen.hidden = screen.id !== "screen-" + name;
  }
  for (const tab of document.querySelectorAll(".tab")) {
    if (tab.dataset.screen === name) {
      tab.setAttribute("aria-current", "page");
    } else {
      tab.removeAttribute("aria-current");
    }
  }
  if (name === "settings") {
    loadModels();
  }
}

// ---- drawing the Coach screen -----------------------------------------------------

function renderAnswerInto(container, answer, headingTag) {
  container.replaceChildren();
  if (answer.question) {
    container.append(make("p", "You asked: " + answer.question, "asked"));
  }
  container.append(make(headingTag, answer.title));
  if (answer.steps.length > 0) {
    const list = make("ol");
    for (const step of answer.steps) {
      list.append(make("li", step));
    }
    container.append(list);
  }
  if (answer.text) {
    container.append(make("p", answer.text, "body"));
  }
  for (const warning of answer.warnings) {
    container.append(make("p", "Careful: " + warning, "warning"));
  }
  const source = answer.source ? "From " + answer.source + ". " : "";
  container.append(make("p", source + formatTime(answer.answered_at), "meta"));
}

function renderCharacters() {
  const select = $("character");
  select.replaceChildren();
  for (const key of state.characters) {
    const option = make("option", key);
    option.value = key;
    option.selected = key === state.selected;
    select.append(option);
  }
  select.disabled = state.characters.length === 0;
  $("last-save").textContent = state.last_save ? "Last saved " + formatTime(state.last_save) : "";
}

function renderAnswers() {
  const newest = $("newest");
  const olderBox = $("older-box");
  const older = $("older");
  const [first, ...rest] = state.answers;
  newest.hidden = !first;
  $("empty").hidden = Boolean(first);
  if (first) {
    renderAnswerInto(newest, first, "h2");
  }
  older.replaceChildren();
  for (const answer of rest) {
    const details = make("details", "", "older");
    details.append(make("summary", answer.title + " (" + formatTime(answer.answered_at) + ")"));
    const body = make("div");
    renderAnswerInto(body, answer, "h3");
    details.append(body);
    older.append(details);
  }
  olderBox.hidden = rest.length === 0;
}

function renderQuestions() {
  const list = $("questions");
  list.replaceChildren();
  for (const question of state.open_questions) {
    list.append(make("li", question.text));
  }
  $("questions-box").hidden = state.open_questions.length === 0;
}

function renderProblem() {
  $("problem").textContent = state.problem || "";
  $("problem").hidden = !state.problem;
}

// ---- drawing the other screens ------------------------------------------------------

function renderChatGpt() {
  $("welcome").hidden = !(state.signed_in && state.welcome_pending);
  $("ask-privacy").hidden = state.signed_in;
  $("plan-line").hidden = !state.signed_in;
  $("signed-in-box").hidden = !state.signed_in;
  $("signed-out-box").hidden = state.signed_in;
  if (state.signed_in) {
    $("signin-waiting").hidden = true;
    $("signin-button").disabled = false;
  }
  const usage = state.usage;
  $("usage-text").textContent =
    "Questions in the last hour: " + usage.last_hour +
    ". Questions in the last day: " + usage.last_day + ".";
}

function renderSettings() {
  for (const input of document.querySelectorAll("[data-setting]")) {
    const value = state.settings[input.dataset.setting];
    if (input.type === "checkbox") {
      input.checked = Boolean(value);
    } else if (input.tagName === "SELECT") {
      input.value = value || "";
    } else {
      input.value = value;
    }
  }
  $("notify-warning").hidden = state.alerts.notify;
}

function renderTriggers() {
  const rules = state.settings.triggers;
  $("on-save").value = rules.on_save;
  $("quiet-instances").checked = rules.quiet_in_instances;
}

function render() {
  renderCharacters();
  renderAnswers();
  renderQuestions();
  renderProblem();
  renderChatGpt();
  renderSettings();
  renderTriggers();
}

// ---- loading ------------------------------------------------------------------------

async function loadState() {
  const query = selectedCharacter ? "?character=" + encodeURIComponent(selectedCharacter) : "";
  const result = await api("/api/state" + query, "GET");
  if (!result.ok) {
    showBanner(result.data.error || "Could not load. Run wow-coach app again.", true);
    return;
  }
  if (serverInstance && result.data.instance !== serverInstance) {
    giveUp(CLOSED); // another program now answers on this port
    return;
  }
  state = result.data;
  selectedCharacter = state.selected;
  render();
}

async function loadModels() {
  const select = $("model");
  const note = $("models-note");
  if (!state || !state.signed_in) {
    note.textContent = "Sign in with ChatGPT to choose a model. Until then, one is picked for you.";
    return;
  }
  const result = await api("/api/models", "GET");
  select.replaceChildren();
  const automatic = make("option", "Choose a good one for me");
  automatic.value = "";
  select.append(automatic);
  const models = result.ok ? result.data.models : [];
  for (const model of models) {
    const option = make("option", model.name);
    option.value = model.slug;
    select.append(option);
  }
  select.value = state.settings.model || "";
  note.textContent = result.ok ? "" : result.data.error || "The model list could not be loaded.";
}

// ---- actions ------------------------------------------------------------------------

async function ask(question) {
  showBanner("", false);
  showThinking(true);
  const result = await api("/api/ask", "POST", { question, character: selectedCharacter });
  if (!result.ok) {
    showThinking(false);
    showBanner(result.data.error || "The question could not be sent.", true);
    return;
  }
  $("ask-input").value = "";
}

async function answerNow() {
  showBanner("", false);
  const result = await api("/api/answer-open", "POST", { character: selectedCharacter });
  if (!result.ok) {
    showBanner(result.data.error || "Could not start.", true);
  } else if (result.data.started) {
    showThinking(true);
  } else {
    showBanner(result.data.message || "", false);
  }
}

async function saveSettings(event) {
  event.preventDefault();
  const changes = {};
  for (const input of document.querySelectorAll("[data-setting]")) {
    const name = input.dataset.setting;
    if (input.type === "checkbox") {
      changes[name] = input.checked;
    } else if (input.type === "number") {
      changes[name] = Number(input.value);
    } else {
      changes[name] = input.value || null;
    }
  }
  const result = await api("/api/settings", "POST", { changes });
  if (!result.ok) {
    showBanner(result.data.error || "Could not save.", true);
    return;
  }
  $("settings-saved").hidden = false;
  await loadState();
}

async function saveTriggers(event) {
  event.preventDefault();
  const triggers = {
    on_save: $("on-save").value,
    quiet_in_instances: $("quiet-instances").checked,
  };
  const result = await api("/api/settings", "POST", { changes: { triggers } });
  if (!result.ok) {
    showBanner(result.data.error || "Could not save.", true);
    return;
  }
  $("triggers-saved").hidden = false;
  await loadState();
}

async function dismissWelcome() {
  $("welcome").hidden = true;
  await api("/api/welcome-seen", "POST");
}

async function signIn() {
  $("signin-button").disabled = true;
  const result = await api("/api/signin", "POST");
  if (!result.ok) {
    $("signin-button").disabled = false;
    showBanner(result.data.error || "Could not start the sign-in.", true);
    return;
  }
  $("signin-waiting").hidden = false;
}

async function signOut() {
  const result = await api("/api/signout", "POST");
  if (result.ok && !result.data.revoke_confirmed) {
    showBanner(
      "You are signed out of wow-coach, but OpenAI did not confirm it. " +
        "To be sure, disconnect wow-coach in your ChatGPT settings.",
      true,
    );
  }
  await loadState();
}

// ---- live updates -------------------------------------------------------------------

function readEvent(event) {
  try {
    return JSON.parse(event.data);
  } catch (error) {
    return {};
  }
}

function onAnswer(event) {
  const data = readEvent(event);
  showThinking(false);
  showBanner(data.note || "", false);
  loadState();
}

function onError(event) {
  showThinking(false);
  $("signin-waiting").hidden = true;
  $("signin-button").disabled = false;
  const data = readEvent(event);
  showBanner(data.message || "Something went wrong.", true, data.kind === "limit");
  loadState();
}

function onInfo(event) {
  const data = readEvent(event);
  showThinking(false);
  showBanner(data.text || "", false);
}

function onSignIn(event) {
  const data = readEvent(event);
  if (data.state === "waiting") {
    const link = $("signin-link");
    // Only ever link to OpenAI's own sign-in page.
    if (typeof data.url === "string" && data.url.startsWith(SIGN_IN_PAGE_START)) {
      link.href = data.url;
      link.hidden = false;
    }
    $("signin-waiting").hidden = false;
  } else {
    loadState();
  }
}

/** Handle one complete event block ("event: x" and "data: {...}" lines). */
function handleEventBlock(block) {
  let name = "message";
  let data = "";
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }
  const handlers = {
    answer: onAnswer,
    question: loadState,
    save: loadState,
    error: onError,
    signin: onSignIn,
    info: onInfo,
  };
  if (handlers[name]) {
    handlers[name]({ data });
  }
}

/**
 * Read the live-update stream with fetch (so the session header can be sent).
 * Returns "gone" (session unknown), "failed" (could not connect) or "dropped" (was connected).
 */
async function listenForEvents() {
  const response = await fetch("/api/events", {
    credentials: "omit",
    headers: { "X-Wow-Coach-Session": sessionSecret },
  });
  if (response.status === 401) {
    return "gone";
  }
  if (!response.ok || !response.body) {
    return "failed";
  }
  eventFailures = 0;
  await loadState(); // also catches anything missed while the stream was down
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (!gaveUp) {
    const { done, value } = await reader.read();
    if (done) {
      return "dropped";
    }
    buffer += decoder.decode(value, { stream: true });
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      handleEventBlock(buffer.slice(0, end));
      buffer = buffer.slice(end + 2);
      end = buffer.indexOf("\n\n");
    }
  }
  return "dropped";
}

async function connectEvents() {
  while (!gaveUp) {
    let outcome = "failed";
    try {
      outcome = await listenForEvents();
    } catch (error) {
      outcome = "failed"; // the connection broke
    }
    if (outcome === "gone") {
      giveUp(SESSION_GONE);
      return;
    }
    eventFailures += 1;
    if (eventFailures >= MAX_EVENT_FAILURES) {
      giveUp(CLOSED);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
}

// ---- start ----------------------------------------------------------------------------

/** Trade the one-time token in the link's # part for a session; else reuse this tab's one. */
async function startSession() {
  const token = window.location.hash.slice(1);
  if (!token) {
    recallSession();
    return;
  }
  const result = await api("/api/session", "POST", { token });
  if (result.ok) {
    sessionSecret = result.data.session;
    serverInstance = result.data.instance;
    rememberSession();
  } else {
    recallSession();
  }
  // Remove the token from the address bar and the browser history.
  history.replaceState(null, "", window.location.pathname);
}

function wireUp() {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.addEventListener("click", () => showScreen(tab.dataset.screen));
  }
  $("character").addEventListener("change", (event) => {
    selectedCharacter = event.target.value;
    loadState();
  });
  $("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = $("ask-input").value.trim();
    if (question) {
      ask(question);
    }
  });
  $("next-button").addEventListener("click", () => ask(NEXT_QUESTION));
  $("answer-now").addEventListener("click", answerNow);
  $("settings-form").addEventListener("submit", saveSettings);
  $("triggers-form").addEventListener("submit", saveTriggers);
  $("signin-button").addEventListener("click", signIn);
  $("welcome-ok").addEventListener("click", dismissWelcome);
  $("signout-button").addEventListener("click", signOut);
}

async function main() {
  wireUp();
  await startSession();
  await loadState();
  if (state) {
    connectEvents();
  }
}

main();
