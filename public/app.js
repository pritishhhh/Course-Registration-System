"use strict";
const $ = (id) => document.getElementById(id);
let config, session = null, sections = [], enrollments = [], busy = false, refreshing = null;
let authGeneration = 0;
const messages = {
  ENROLLED: "You're registered. Your seat is confirmed.", WAITLISTED: "You've joined the waitlist.",
  ALREADY_ENROLLED: "You're already registered for this section.", ALREADY_WAITLISTED: "You're already on this waitlist.",
  DROPPED: "Registration dropped.", NOT_ENROLLED: "This registration has already been dropped.",
  FULL_NO_WAITLIST: "This section and its waitlist are full.", REGISTRATION_NOT_OPEN: "Registration has not opened yet.",
  REGISTRATION_CLOSED: "Registration has closed for this term."
};
function notice(message, error = false) {
  $("notice").textContent = message; $("notice").classList.toggle("error", error); $("notice").hidden = !message;
}
function node(tag, text, className) {
  const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
  if (className) el.className = className; return el;
}
async function json(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail || data.msg || data.error_description || data.message;
    throw new Error(messages[detail] || (typeof detail === "string" ? detail : "The request failed. Please try again."));
  }
  return data;
}
function saveSession(value) {
  session = value?.access_token ? value : null; authGeneration++;
  try { if (session) sessionStorage.setItem("course-session", JSON.stringify(session)); else sessionStorage.removeItem("course-session"); } catch { /* In-memory login still works when storage is unavailable. */ }
  enrollments = []; account(); render();
}
async function auth(path, body, token) {
  return json(await fetch(`${config.supabase_url}/auth/v1/${path}`, {
    method: "POST", headers: { "apikey": config.supabase_key, "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined
  }));
}
async function accessToken() {
  if (!session) return null;
  if ((session.expires_at || 0) > Date.now() / 1000 + 45) return session.access_token;
  if (!refreshing) {
    const generation = authGeneration;
    refreshing = auth("token?grant_type=refresh_token", { refresh_token: session.refresh_token }).then(value => {
      if (generation !== authGeneration) throw new Error("Account changed. Try again.");
      value.expires_at = Math.floor(Date.now() / 1000) + value.expires_in;
      saveSession(value); return value.access_token;
    }).catch(error => { if (generation === authGeneration) saveSession(null); throw error; }).finally(() => { refreshing = null; });
  }
  return refreshing;
}
async function api(path, method = "GET", authenticated = false) {
  const token = authenticated ? await accessToken() : null;
  if (authenticated && !token) throw new Error("Sign in to continue.");
  const response = await fetch(`/api/${path}`, { method, headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (response.status === 401 && authenticated) saveSession(null);
  return json(response);
}
function account() {
  $("auth-form").hidden = !!session; $("signout").hidden = !session;
  $("github-login").hidden = !!session;
  $("account-title").textContent = session ? "You're signed in" : "Ready to register?";
  $("account-note").textContent = session?.user?.email || "Sign in to manage your courses and waitlists.";
}
function render() {
  const search = $("search").value.toLowerCase(); const list = $("courses"); list.replaceChildren();
  const filtered = sections.filter(s => `${s.course_code} ${s.title} ${s.instructor || ""} ${s.term}`.toLowerCase().includes(search));
  for (const s of filtered) {
    const card = node("article", undefined, "course"), info = node("div"), action = node("div", undefined, "course-action");
    info.append(node("span", `${s.course_code} · ${s.section_code}`, "code"), node("h3", s.title),
      node("p", `${s.instructor || "Instructor to be announced"} · ${s.credits} credits`, "metadata"), node("p", s.term, "metadata"));
    const now = Date.now(); const closed = s.registration_closes_at && now >= Date.parse(s.registration_closes_at);
    const future = s.registration_opens_at && now < Date.parse(s.registration_opens_at);
    const own = enrollments.find(e => e.section_id === s.section_id);
    const seats = s.capacity - s.seats_filled, full = !seats && s.waitlist_filled >= s.waitlist_capacity;
    const label = closed ? "Registration closed" : future ? "Opens soon" : seats ? `${seats} of ${s.capacity} seats available` : `${s.waitlist_filled}/${s.waitlist_capacity} on waitlist`;
    action.append(node("span", label, `availability ${closed || future ? "closed" : !seats ? "wait" : ""}`));
    const button = node("button", own ? own.status === "ENROLLED" ? "Registered ✓" : "Waitlisted ✓" : full ? "Section full" : seats ? "Register" : "Join waitlist");
    button.type = "button"; button.disabled = busy || !!own || !!closed || !!future || full;
    button.addEventListener("click", () => mutate(s.section_id, false)); action.append(button); card.append(info, action); list.append(card);
  }
  if (!filtered.length) list.append(node("p", sections.length ? "No courses match your search." : "No sections are currently available.", "muted"));
  const registrations = $("registrations"); registrations.replaceChildren();
  if (!enrollments.length) registrations.append(node("p", session ? "No active registrations yet. Find your first course in the catalog." : "Sign in to see your courses and waitlist positions.", "muted"));
  for (const e of enrollments) {
    const row = node("div", undefined, "registration");
    row.append(node("strong", `${e.course_code} · ${e.section_code}`), node("span", e.status === "ENROLLED" ? "ENROLLED" : `WAITLIST · POSITION ${e.waitlist_position}`, "badge"), node("p", e.title, "metadata"));
    const button = node("button", e.status === "ENROLLED" ? "Drop course" : "Leave waitlist", "secondary"); button.type = "button"; button.disabled = busy;
    button.addEventListener("click", () => { if (window.confirm(`Drop ${e.course_code} section ${e.section_code}?`)) mutate(e.section_id, true); });
    row.append(button); registrations.append(row);
  }
}
async function reload() {
  sections = await api("sections");
  if (session) {
    // Refresh before capturing the generation, since refresh updates the session.
    await accessToken(); const generation = authGeneration;
    const records = await api("me/enrollments", "GET", true);
    if (generation === authGeneration && session) enrollments = records;
  }
  render();
}
async function mutate(id, dropping) {
  if (!session) { notice("Sign in to register for a course."); $("email").focus(); return; }
  if (busy) return; busy = true; render();
  try {
    const value = await api(`sections/${id}/${dropping ? "registration" : "register"}`, dropping ? "DELETE" : "POST", true);
    notice(messages[value.result] || value.result);
    await reload();
  } catch (error) { notice(error.message, true); }
  finally { busy = false; render(); }
}
async function signIn(signup) {
  if (!$("auth-form").reportValidity()) return;
  $("signin").disabled = $("signup").disabled = true;
  try {
    const value = await auth(signup ? "signup" : "token?grant_type=password", { email: $("email").value.trim(), password: $("password").value });
    $("password").value = "";
    if (value.access_token) {
      value.expires_at = Math.floor(Date.now() / 1000) + value.expires_in; saveSession(value);
      notice("You're signed in."); await reload();
    } else notice("Check your email to confirm your account, then return here to sign in.");
  } catch (error) { notice(error.message, true); }
  finally { $("signin").disabled = $("signup").disabled = false; }
}
$("auth-form").addEventListener("submit", event => { event.preventDefault(); signIn(false); });
$("signup").addEventListener("click", () => signIn(true));
$("github").addEventListener("click", () => {
  if (!config) { notice("Authentication is not configured yet.", true); return; }
  const url = new URL(`${config.supabase_url}/auth/v1/authorize`);
  url.searchParams.set("provider", "github"); url.searchParams.set("redirect_to", location.origin);
  location.assign(url.href);
});
$("signout").addEventListener("click", async () => {
  const token = session?.access_token; saveSession(null); notice("You're signed out.");
  if (token) try { await auth("logout", null, token); } catch { /* Local credentials have already been removed. */ }
});
$("search").addEventListener("input", render);
$("refresh").addEventListener("click", async () => {
  $("refresh").disabled = true;
  try { await reload(); notice("Availability updated."); } catch (error) { notice(error.message, true); }
  finally { $("refresh").disabled = false; }
});
(async () => {
  try {
    // The default Supabase email confirmation flow returns tokens in a fragment.
    const fragment = new URLSearchParams(location.hash.slice(1));
    if (fragment.has("access_token") || fragment.has("error")) history.replaceState(null, "", location.pathname);
    try { session = JSON.parse(sessionStorage.getItem("course-session") || "null"); } catch { session = null; }
    if (fragment.has("access_token")) session = { access_token: fragment.get("access_token"), refresh_token: fragment.get("refresh_token"), expires_at: Math.floor(Date.now() / 1000) + Number(fragment.get("expires_in") || 3600) };
    try { config = await api("config"); }
    catch (error) {
      notice(error.message, true);
      $("signin").disabled = $("signup").disabled = $("github").disabled = true;
      session = null;
    }
    account();
    if (session) saveSession(session);
    await reload();
    if (fragment.has("error")) notice(fragment.get("error_description") || "Email confirmation failed. Try signing in again.", true);
  } catch (error) { $("courses").replaceChildren(node("p", "Courses could not be loaded.", "muted")); notice(error.message, true); }
})();
