import { h, icon, dateKey, uid, toast } from "../util.js";
import * as db from "../db.js";
import { Session, countsFor, previews } from "../srs.js";
import { renderCard, plainText } from "../render.js";
import * as media from "../media.js";
import { topNav, timerFor, empty } from "./shared.js";

const fill = (el, ...kids) => el.replaceChildren(...kids.filter(Boolean));

const inDeck = (decks, deck) => {
  const ids = new Set(decks.filter((d) => d.name === deck.name || d.name.startsWith(deck.name + "::")).map((d) => d.id));
  return (c) => ids.has(c.did);
};

export async function decks(ctx) {
  const [ds, cards, s, day] = await Promise.all([db.getAll("decks"), db.getAll("cards"), db.getSettings(), db.getDay(dateKey())]);
  ds.sort((a, b) => a.name.localeCompare(b.name));

  const newDeck = async () => {
    const name = prompt("Deck name")?.trim();
    if (!name) return;
    await db.put("decks", { id: uid(), name });
    ctx.go("/cards");
  };

  const rows = ds.map((d) => {
    const c = countsFor(cards.filter(inDeck(ds, d)), s, day);
    return h("a", { class: "list-row", href: `#/cards/study?deck=${d.id}` },
      h("span", { class: "plate" }, icon("cards")),
      h("span", { class: "grow title-sm" }, d.name),
      h("span", { class: "caption counts", style: "gap:12px" }, h("b", {}, c.new), h("b", {}, c.learn), h("b", {}, c.review)));
  });

  const all = countsFor(cards, s, day);
  return h("div", { class: "page" },
    h("h1", { class: "display-lg" }, "Cards"),
    h("section", { class: "gradient-orb-card orb-mint stack" },
      h("span", { class: "caption-uppercase muted" }, "Due today"),
      h("div", { class: "counts display-sm" }, `${all.new} new · ${all.learn} learning · ${all.review} review`),
      h("a", { class: "btn btn-primary", href: "#/cards/study" }, "Study all")),
    h("div", { class: "row" },
      h("a", { class: "btn btn-outline", href: "#/cards/browse" }, "Browse"),
      h("button", { class: "btn btn-outline", onClick: newDeck }, "New deck"),
      h("a", { class: "btn btn-outline", href: "#/import" }, "Import")),
    h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" },
      h("div", { class: "row between caption-uppercase muted", style: "padding:8px 0" }, h("span", {}, "Deck"), h("span", {}, "New · Learn · Due")),
      rows));
}

export async function study(ctx) {
  const timer = await timerFor(ctx);
  const [ds, s, models] = await Promise.all([db.getAll("decks"), db.getSettings(), db.getAll("models")]);
  const modelById = new Map(models.map((m) => [m.id, m]));
  const deck = ds.find((d) => d.id === Number(ctx.query.deck));
  const day = await db.getDay(dateKey());

  let cards = (await db.getAll("cards")).filter(deck ? inDeck(ds, deck) : () => true);
  let session = new Session(cards, s, day);
  let last = null;
  const noteCache = new Map();
  const getNote = async (id) => noteCache.get(id) ?? (noteCache.set(id, await db.get("notes", id)), noteCache.get(id));

  ctx.onLeave(media.release);
  const root = h("div", {});
  const body = h("div", { class: "page has-top" });
  root.append(topNav(deck ? deck.name : "All decks", "/cards"), body);

  const counts = h("div", { class: "counts caption" });
  const paintCounts = () => {
    const r = session.remaining;
    counts.replaceChildren(h("span", {}, "New ", h("b", {}, r.new)), h("span", {}, "Learn ", h("b", {}, r.learn)), h("span", {}, "Due ", h("b", {}, r.review)));
  };

  async function show() {
    paintCounts();
    const card = session.next();
    if (!card) {
      fill(body, 
        timer && h("div", { class: "feature-card" }, timer.el),
        h("section", { class: "gradient-orb-card orb-lavender stack", style: "text-align:center" },
          h("h1", { class: "display-md" }, "Done for now."),
          h("p", {}, session.remaining.learn ? "Cards in learning will be back shortly." : "No more cards due. Nice."),
          h("a", { class: "btn btn-primary", href: "#/today" }, "Back to Today")),
        last && h("button", { class: "btn btn-text", onClick: undo }, "Undo last answer"));
      return;
    }
    const note = await getNote(card.nid);
    const model = modelById.get(note.mid);
    const { front, back } = renderCard(note, model, card.ord);
    let revealed = false;
    const probe = h("div", { html: back });
    const sound = probe.querySelector(".sound")?.dataset.sound;
    if (sound) media.prepare(sound);
    const face = h("div", { class: "face card", html: front, onClick: (e) => {
      const b = e.target.closest(".sound");
      if (b) media.playNow(b.dataset.sound);
    } });
    const actions = h("div", {});
    const draw = () => {
      face.innerHTML = revealed ? back : front;
      if (!revealed) {
        actions.replaceChildren(h("button", { class: "btn btn-primary btn-block", onClick: () => { revealed = true; draw(); if (sound) media.playNow(sound); } }, "Show answer"));
      } else {
        const p = previews(card, s);
        const names = ["Again", "Hard", "Good", "Easy"];
        actions.replaceChildren(h("div", { class: "answers" }, names.map((n, i) =>
          h("button", { class: `btn ${i === 2 ? "btn-primary" : "btn-outline"}`, onClick: () => rate(card, i + 1) }, n, h("small", {}, p[i])))));
      }
    };
    fill(body, 
      timer && h("div", { class: "feature-card", style: "padding:12px 16px" }, timer.el),
      counts,
      h("div", { class: "feature-card study-card" }, face),
      actions,
      h("div", { class: "row between" },
        h("button", { class: "btn btn-text", disabled: !last, onClick: undo }, "Undo"),
        h("a", { class: "btn btn-text", href: `#/cards/edit?note=${card.nid}&back=${encodeURIComponent(location.hash.slice(1))}` }, "Edit")));
    draw();
  }

  async function rate(card, rating) {
    const day = await db.getDay(dateKey());
    const { before, after } = session.apply(card, rating);
    const countKind = before.kind === "new" ? "newDone" : before.kind === "review" ? "revDone" : null;
    if (countKind) day[countKind]++;
    last = { before, after, countKind };
    await Promise.all([
      db.put("cards", after),
      db.saveDay(day),
      db.put("revlog", { id: Date.now(), cid: card.id, ease: rating, ivl: after.ivl, kind: before.kind }),
    ]);
    await show();
  }

  async function undo() {
    if (!last) return;
    const day = await db.getDay(dateKey());
    if (last.countKind) day[last.countKind] = Math.max(0, day[last.countKind] - 1);
    await Promise.all([db.put("cards", last.before), db.saveDay(day)]);
    last = null;
    cards = (await db.getAll("cards")).filter(deck ? inDeck(ds, deck) : () => true);
    session = new Session(cards, s, day);
    await show();
  }

  await show();
  return root;
}

export async function browse(ctx) {
  const [notes, cards, ds, models] = await Promise.all([db.getAll("notes"), db.getAll("cards"), db.getAll("decks"), db.getAll("models")]);
  const deckName = new Map(ds.map((d) => [d.id, d.name]));
  const deckOf = new Map(cards.map((c) => [c.nid, c.did]));
  void models;
  const list = h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" });
  const q = h("input", { class: "text-input", type: "search", placeholder: "Search · tag:verbs · deck:Spanish", autocapitalize: "none" });

  const draw = () => {
    const terms = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    const hit = notes.filter((n) => {
      const text = plainText(n.fields.join(" ")).toLowerCase();
      return terms.every((t) =>
        t.startsWith("tag:") ? n.tags.some((x) => x.toLowerCase() === t.slice(4))
        : t.startsWith("deck:") ? (deckName.get(deckOf.get(n.id)) || "").toLowerCase().startsWith(t.slice(5))
        : text.includes(t) || n.tags.some((x) => x.toLowerCase().includes(t)));
    }).slice(0, 100);
    list.replaceChildren(...(hit.length ? hit.map((n) => h("a", { class: "list-row", href: `#/cards/edit?note=${n.id}&back=/cards/browse` },
      h("span", { class: "grow" },
        h("span", { class: "body-strong", style: "display:block" }, plainText(n.fields[0]).slice(0, 60)),
        h("span", { class: "caption muted", style: "display:block" }, plainText(n.fields[1] || "").slice(0, 60))),
      icon("chevron"))) : [h("p", { class: "muted", style: "padding:16px 0" }, "No matches.")]));
  };
  q.addEventListener("input", draw);
  draw();
  return h("div", {}, topNav(`Browse · ${notes.length}`, "/cards"), h("div", { class: "page has-top" }, q, list));
}

export async function editNote(ctx) {
  const note = await db.get("notes", Number(ctx.query.note));
  if (!note) return h("div", { class: "page" }, empty("Note not found", "It may have been deleted."));
  const back = ctx.query.back || "/cards/browse";
  const model = await db.get("models", note.mid);
  const cards = await db.byIndex("cards", "nid", note.id);
  const inputs = model.fields.map((f, i) => h("textarea", { class: "text-input", rows: 2, "aria-label": f }, note.fields[i] || ""));
  const tags = h("input", { class: "text-input", value: note.tags.join(" "), autocapitalize: "none" });
  const suspended = cards.every((c) => c.suspended);

  const save = async () => {
    note.fields = inputs.map((i) => i.value);
    note.tags = tags.value.split(/\s+/).filter(Boolean);
    await db.put("notes", note);
    toast("Saved");
    ctx.go(back);
  };
  const toggle = async () => {
    await db.putMany("cards", cards.map((c) => ({ ...c, suspended: !suspended })));
    toast(suspended ? "Unsuspended" : "Suspended");
    ctx.go(back);
  };
  const remove = async () => {
    if (!confirm("Delete this note and its cards?")) return;
    await db.del("notes", note.id);
    await db.delMany("cards", cards.map((c) => c.id));
    ctx.go(back);
  };

  return h("div", {}, topNav("Edit note", back),
    h("div", { class: "page has-top" },
      ...model.fields.map((f, i) => h("div", { class: "field" }, h("label", {}, f), inputs[i])),
      h("div", { class: "field" }, h("label", {}, "Tags"), tags),
      h("button", { class: "btn btn-primary btn-block", onClick: save }, "Save"),
      h("div", { class: "row" },
        h("button", { class: "btn btn-outline grow", onClick: toggle }, suspended ? "Unsuspend" : "Suspend"),
        h("button", { class: "btn btn-outline grow", onClick: remove }, "Delete"))));
}
