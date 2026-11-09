// Local user profiles. Each user gets their own IndexedDB database, so cards, progress, settings and
// downloaded audio are separate. Profiles and optional passcode hashes live in localStorage (the
// database name has to be known before any database can be opened). This separates people sharing a
// phone; it is not real security, since anyone with the browser profile can read everything.
import { h } from "./util.js";
import * as db from "./db.js";

const REG = "language-app:users";
const ITERATIONS = 100_000;
const RELOCK_AFTER = 5 * 60_000; // ask for the passcode again after this long in the background
const LEGACY_DB = "language-app"; // data from before profiles existed becomes the first user
export const MIN_LENGTH = 4;
export const MAX_NAME = 24;
export const canLock = !!crypto?.subtle; // Web Crypto needs HTTPS or localhost

const safe = (area) => ({
  get: (k) => { try { return area.getItem(k); } catch { return null; } },
  set: (k, v) => { try { area.setItem(k, v); } catch { /* storage blocked */ } },
  del: (k) => { try { area.removeItem(k); } catch { /* storage blocked */ } },
});
const local = safe(localStorage);

let reg; // { users: [{ id, name, salt?, hash? }], last }
let current;

const save = () => local.set(REG, JSON.stringify(reg));
const dbName = (u) => (u.id === "main" ? LEGACY_DB : `${LEGACY_DB}-${u.id}`);
const toHex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const fromHex = (s) => new Uint8Array(s.match(/../g).map((x) => parseInt(x, 16)));

async function derive(passcode, salt) {
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(passcode), "PBKDF2", false, ["deriveBits"]);
  return toHex(await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt, iterations: ITERATIONS }, key, 256));
}

async function hashed(passcode) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  return { salt: toHex(salt), hash: await derive(passcode, salt) };
}

export async function check(user, passcode) {
  return !user.hash || (await derive(passcode, fromHex(user.salt))) === user.hash;
}

// Browse without an account: starts empty, is wiped on sign-out and at the next guest sign-in, and
// does not download content in the background.
const GUEST = { id: "guest", name: "Guest", guest: true };

export const currentUser = () => current;
// New accounts take the placement test once (the flag is cleared when they finish or skip it).
export const needsPlacement = () => !!current?.placement && !current.guest;
export function placementDone() {
  delete current.placement;
  save();
}
export const listUsers = () => reg.users;

function validName(name) {
  name = name.trim();
  if (!name) return "Enter a name.";
  if (name.length > MAX_NAME) return `Use at most ${MAX_NAME} characters.`;
  if (reg.users.some((u) => u.name.toLowerCase() === name.toLowerCase())) return "That name is taken.";
  return null;
}

async function createUser(name, passcode) {
  const user = { id: "u" + Date.now().toString(36), name: name.trim(), placement: true, ...(passcode ? await hashed(passcode) : {}) };
  reg.users.push(user);
  save();
  return user;
}

export async function setPasscode(passcode) {
  Object.assign(current, await hashed(passcode));
  save();
}

export function removePasscode() {
  delete current.salt;
  delete current.hash;
  save();
}

async function wipe(user) {
  await db.close();
  await new Promise((resolve) => {
    const req = indexedDB.deleteDatabase(dbName(user));
    req.onsuccess = req.onerror = req.onblocked = resolve;
  });
}

export async function switchUser() {
  if (current.guest) await wipe(current); // guest sessions leave nothing behind
  location.reload(); // every load starts at the user list
}

export async function deleteCurrentUser() {
  await wipe(current);
  reg.users = reg.users.filter((u) => u !== current);
  save();
  switchUser();
}

// The sign-in screen. With `only`, it just asks that user for their passcode again (no switching).
function gate({ only } = {}) {
  return new Promise((resolve) => {
    const frozen = [...document.body.children].filter((el) => el.tagName !== "SCRIPT");
    const box = h("div", { class: "lock-box stack" });
    const screen = h("div", { class: "lock-screen", role: "dialog", "aria-modal": "true", "aria-label": "Sign in" }, box);
    const input = (label, type = "text", auto = "off") => h("input", { class: "text-input", type, autocomplete: auto, "aria-label": label, placeholder: label, enterkeyhint: "go" });
    const submitOnEnter = (el, fn) => el.addEventListener("keydown", (e) => { if (e.key === "Enter") fn(); });
    const msg = () => h("p", { class: "caption error", role: "alert" });
    const show = (...nodes) => { box.replaceChildren(...nodes); box.querySelector("input")?.focus(); };
    const done = (user) => {
      frozen.forEach((el) => el.removeAttribute("inert"));
      screen.remove();
      resolve(user);
    };

    const pick = () => {
      const users = [...reg.users].sort((a, b) => (b.id === reg.last) - (a.id === reg.last));
      show(
        h("h1", { class: "display-lg" }, "Who's learning?"),
        ...users.map((u) => h("button", { class: "btn btn-outline btn-block", onClick: () => (u.hash ? passcode(u) : done(u)) }, u.name)),
        h("button", { class: "btn btn-outline btn-block", onClick: add }, "Add user"),
        h("button", { class: "btn btn-outline btn-block", onClick: () => done(GUEST) }, "Continue as guest"));
    };

    const passcode = (user) => {
      const pass = input("Passcode", "password", "current-password");
      const err = msg();
      const go = async () => {
        if (await check(user, pass.value)) return done(user);
        err.textContent = "Wrong passcode.";
        pass.value = "";
        pass.focus();
      };
      submitOnEnter(pass, go);
      show(
        h("h1", { class: "display-lg" }, only ? "Locked" : user.name),
        h("div", { class: "field" }, h("label", {}, "Passcode"), pass, err),
        h("button", { class: "btn btn-primary btn-block", onClick: go }, "Unlock"),
        only ? null : h("button", { class: "btn btn-outline btn-block", onClick: pick }, "Back"));
    };

    const add = () => {
      const name = input("Name");
      name.maxLength = MAX_NAME;
      const pass = input(`Passcode (optional, ${MIN_LENGTH}+ characters)`, "password", "new-password");
      const err = msg();
      const go = async () => {
        err.textContent = validName(name.value) || (pass.value && pass.value.length < MIN_LENGTH ? `Use at least ${MIN_LENGTH} characters.` : "");
        if (err.textContent) return;
        done(await createUser(name.value, pass.value));
      };
      submitOnEnter(name, go);
      submitOnEnter(pass, go);
      show(
        h("h1", { class: "display-lg" }, "Add user"),
        h("div", { class: "field" }, h("label", {}, "Name"), name),
        canLock ? h("div", { class: "field" }, h("label", {}, "Passcode"), pass) : null,
        err,
        h("button", { class: "btn btn-primary btn-block", onClick: go }, "Create"),
        reg.users.length
          ? h("button", { class: "btn btn-outline btn-block", onClick: pick }, "Back")
          : h("button", { class: "btn btn-outline btn-block", onClick: () => done(GUEST) }, "Continue as guest"));
    };

    frozen.forEach((el) => el.setAttribute("inert", ""));
    document.querySelectorAll("dialog[open]").forEach((d) => d.close()); // modal dialogs would sit above the screen
    document.body.append(screen);
    if (only) passcode(only);
    else if (!reg.users.length) add();
    else pick();
  });
}

async function load() {
  try { reg = JSON.parse(local.get(REG)); } catch { reg = null; }
  if (reg?.users) return;
  // First run with profiles: existing data becomes the first user, and the old in-database
  // passcode (if any) moves to the profile.
  const first = { id: "main", name: "Me" };
  db.useDatabase(LEGACY_DB);
  const old = await db.get("settings", "lock");
  if (old) {
    Object.assign(first, { salt: old.salt, hash: old.hash });
    await db.del("settings", "lock");
  }
  reg = { users: [first], last: first.id };
  save();
}

// Call once at startup; resolves when a user is signed in and the database is selected.
export async function initUsers() {
  await load();
  current = await gate(); // always show everyone; tap a name, then enter its passcode if it has one
  if (current.guest) {
    await wipe(current); // clear whatever an earlier guest left (e.g. the tab was just closed)
    db.useDatabase(dbName(current));
    await db.saveSettings({ ...(await db.getSettings()), autoSync: false });
  } else {
    reg.last = current.id;
    save();
    db.useDatabase(dbName(current));
  }

  let hiddenAt = 0;
  document.addEventListener("visibilitychange", async () => {
    if (document.hidden) hiddenAt = Date.now();
    else if (current.hash && hiddenAt && Date.now() - hiddenAt > RELOCK_AFTER && !document.querySelector(".lock-screen")) {
      hiddenAt = 0;
      await gate({ only: current });
    }
  });
}
