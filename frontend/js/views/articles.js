import { h, icon, uid, toast } from "../util.js";
import * as db from "../db.js";
import { createNote } from "./add.js";
import { dismissArticle } from "../sync.js";
import { apiUrl } from "../config.js";
import { topNav, timerFor, empty } from "./shared.js";

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const keep = (ctx) => (ctx.query.task ? `?task=${ctx.query.task}` : "");

const BOOKMARKLET = "javascript:(()=>{const a=document.querySelector('article')||document.body;" +
  "const t=[...a.querySelectorAll('h1,p')].map(e=>e.innerText.trim()).filter(Boolean).join('\\n\\n');" +
  "navigator.clipboard.writeText(t).then(()=>alert('Copied '+t.split(/\\s+/).length+' words. Open the app and paste.')," +
  "()=>prompt('Copy this text:',t))})()";

async function post(path, body) {
  let res;
  try {
    res = await fetch(apiUrl(`/articles/${path}`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch {
    throw new Error("Importing needs a connection to your server.");
  }
  if ([404, 405, 501].includes(res.status)) throw new Error("Importing needs the backend server. It isn't available on this hosting.");
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Server error ${res.status}`);
  return data;
}

async function save(a) {
  if (a.truncated && !confirm(`Only ${a.words} words, so this is probably cut off by a paywall. Save anyway?`)) return null;
  if (!a.dictionary) toast("Dictionary not installed on the server: no translations");
  const id = `article:${uid()}`;
  await db.put("library", { id, kind: "article", title: a.title, source: a.source, url: a.url, text: a.text, words: a.words, glossary: a.glossary, added: Date.now() });
  return id;
}

export async function addArticle(ctx) {
  const back = "/practice/read" + keep(ctx);
  const status = h("p", { class: "body-sm", role: "status" });
  const busy = async (fn) => {
    status.className = "body-sm"; status.textContent = "Importing…";
    try {
      const id = await fn();
      status.textContent = "";
      if (id) ctx.go(`/practice/article?item=${encodeURIComponent(id)}${ctx.query.task ? `&task=${ctx.query.task}` : ""}`);
    } catch (e) { status.className = "body-sm error"; status.textContent = e.message; }
  };

  const url = h("input", { class: "text-input", type: "url", placeholder: "https://www.elmundo.es/…", autocapitalize: "none", inputmode: "url" });
  const importUrl = () => busy(async () => (url.value.trim() ? save(await post("import", { url: url.value.trim() })) : null));

  const src = h("select", { class: "select-pill", "aria-label": "Source" },
    h("option", { value: "elmundo" }, "El Mundo"), h("option", { value: "elpais" }, "El País"));
  const list = h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px", hidden: true });
  const loadFeed = async () => {
    list.hidden = false;
    list.replaceChildren(h("p", { class: "muted", style: "padding:16px 0" }, "Loading…"));
    try {
      const res = await fetch(apiUrl(`/articles/feed?source=${src.value}`));
      if (!res.ok) throw new Error();
      const items = await res.json();
      list.replaceChildren(...items.map((it) => h("button", { class: "list-row", onClick: () => {
        if (it.pasteOnly) {
          window.open(it.url, "_blank", "noopener");
          status.className = "body-sm"; status.textContent = "El País opens in Safari. Select the text, copy it, then paste it below.";
        } else busy(async () => save(await post("import", { url: it.url })));
      } },
        h("span", { class: "grow" }, h("span", { class: "body-strong", style: "display:block" }, it.title)),
        icon("chevron"))));
    } catch { list.replaceChildren(h("p", { class: "muted", style: "padding:16px 0" }, "Couldn't load headlines. Are you online?")); }
  };
  src.addEventListener("change", () => { list.hidden = true; });

  const title = h("input", { class: "text-input", placeholder: "Title (optional)" });
  const body = h("textarea", { class: "text-input", rows: 6, placeholder: "Paste the article text here" });
  const importPaste = () => busy(async () => {
    let t = title.value.trim(), text = body.value.trim();
    if (!text) return null;
    if (!t) { const [first, ...rest] = text.split(/\n+/); if (first.length <= 200 && rest.length) { t = first; text = rest.join("\n\n"); } }
    return save(await post("prepare", { title: t, text, source: src.value === "elpais" ? "El País" : "" }));
  });
  const copyBm = async () => { try { await navigator.clipboard.writeText(BOOKMARKLET); toast("Bookmarklet copied"); } catch { prompt("Copy this:", BOOKMARKLET); } };

  return h("div", {}, topNav("Add article", back), h("div", { class: "page has-top" },
    h("h1", { class: "display-lg" }, "Add article"),
    status,
    h("section", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, "From a link · El Mundo"),
      url, h("button", { class: "btn btn-primary btn-block", onClick: importUrl }, "Import")),
    h("section", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, "Latest headlines"),
      h("div", { class: "row" }, src, h("button", { class: "btn btn-outline", onClick: loadFeed }, "Show")), list),
    h("section", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, "Paste text · works for El País"),
      h("p", { class: "body-sm muted" }, "El País blocks automatic downloads. Open the article in Safari (signed in if you subscribe), copy the text, paste it here."),
      title, body,
      h("button", { class: "btn btn-primary btn-block", onClick: importPaste }, "Import text"),
      h("button", { class: "btn btn-text", onClick: copyBm }, "Copy “copy article” bookmarklet"))));
}

function sentenceAround(p, i) {
  let start = 0;
  for (const m of p.matchAll(/[.!?…]+["»”')]*\s+/g)) {
    const end = m.index + m[0].length;
    if (end <= i) start = end; else break;
  }
  const re = /[.!?…]+["»”')]*(?=\s|$)/g;
  re.lastIndex = i;
  const m = re.exec(p);
  return { start, end: m ? m.index + m[0].length : p.length };
}

export async function reader(ctx) {
  const timer = await timerFor(ctx);
  const item = await db.get("library", ctx.query.item);
  if (!item) return h("div", { class: "page" }, empty("Not found", "This article may have been deleted."));
  if (!item.readAt) { item.readAt = Date.now(); await db.put("library", item); } // opened = read
  const paras = item.text.split(/\n\s*\n/);
  const gloss = item.glossary || {};
  let active = null;

  const article = h("article", { class: "article" }, paras.map((p, pi) => {
    const el = h("p", {});
    let last = 0;
    for (const m of p.matchAll(/\p{L}+/gu)) {
      if (m.index > last) el.append(p.slice(last, m.index));
      el.append(h("span", { class: "w", "data-p": pi, "data-i": m.index }, m[0]));
      last = m.index + m[0].length;
    }
    el.append(p.slice(last));
    return el;
  }));

  const dlg = h("dialog", { class: "sheet", "aria-label": "Translation" });
  dlg.addEventListener("close", () => active?.classList.remove("on"));
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });

  async function addToAnki(word, hits, p, i) {
    const { start, end } = sentenceAround(p, i);
    const sentence = p.slice(start, end).trim();
    const off = i - start - (p.slice(start, end).length - p.slice(start, end).trimStart().length);
    const cloze = esc(sentence.slice(0, off)) + `{{c1::${esc(word)}}}` + esc(sentence.slice(off + word.length));
    const top = hits[0];
    const extra = top ? `${esc(top.lemma)} (${esc(top.pos)}): ${esc(top.gloss.join("; "))}` : "";
    const models = await db.getAll("models");
    const decks = await db.getAll("decks");
    let deck = decks.find((d) => d.name === "Reading");
    if (!deck) { deck = { id: uid(), name: "Reading" }; await db.put("decks", deck); }
    await createNote({ did: deck.id, model: models.find((m) => m.cloze && m.name === "Cloze"), fields: [cloze, extra], tags: ["reading"] });
    toast("Added to Anki");
    dlg.close();
  }

  article.addEventListener("click", (e) => {
    const w = e.target.closest(".w");
    if (!w) return;
    active?.classList.remove("on");
    active = w; w.classList.add("on");
    const word = w.textContent, p = paras[w.dataset.p], i = Number(w.dataset.i);
    const hits = gloss[word.toLowerCase()] || [];
    dlg.replaceChildren(
      h("h2", { class: "display-md" }, word),
      h("div", { class: "stack", style: "margin:16px 0" },
        hits.length ? hits.map((x) => h("div", {},
          h("div", { class: "row" }, h("span", { class: "title-sm" }, x.lemma), h("span", { class: "badge-pill" }, x.pos)),
          x.form && h("p", { class: "caption muted" }, x.form),
          h("ul", { style: "margin:4px 0 0;padding-left:20px" }, x.gloss.map((g) => h("li", {}, g)))))
        : [h("p", { class: "muted" }, item.glossary && Object.keys(gloss).length ? "No translation found offline." : "No dictionary was available when this was imported."),
           h("a", { class: "btn btn-text", href: `https://www.wordreference.com/es/en/translation.asp?spen=${encodeURIComponent(word)}`, target: "_blank", rel: "noopener" }, "Look up on WordReference")]),
      h("div", { class: "stack" },
        h("button", { class: "btn btn-primary btn-block", onClick: () => addToAnki(word, hits, p, i) }, "Add to Anki"),
        h("button", { class: "btn btn-outline btn-block", onClick: () => dlg.close() }, "Close")));
    dlg.showModal();
  });

  const remove = async () => {
    if (!confirm("Delete this article?")) return;
    await db.del("library", item.id);
    if (item.auto) await dismissArticle(item.id); // don't sync it back
    ctx.go("/practice/read" + keep(ctx));
  };

  return h("div", {}, topNav(item.source || "Article", "/practice/read" + keep(ctx)),
    h("div", { class: "page has-top" },
      timer && h("div", { class: "feature-card" }, timer.el),
      h("h1", { class: "display-md" }, item.title),
      h("p", { class: "caption muted" }, "Tap any word for its translation."),
      article, dlg,
      h("button", { class: "btn btn-outline btn-block", onClick: remove }, "Delete article")));
}
