import { h, uid, toast } from "../util.js";
import * as db from "../db.js";
import { newCardState } from "../srs.js";
import { timerFor } from "./shared.js";

export function clozeOrds(text) {
  const s = new Set([...text.matchAll(/\{\{c(\d+)::/g)].map((m) => Number(m[1]) - 1));
  return [...s].sort((a, b) => a - b);
}

export async function createNote({ did, model, fields, tags }) {
  const nid = uid();
  const ords = model.cloze ? clozeOrds(fields[0]) : model.templates.map((_, i) => i);
  if (!ords.length) throw new Error("Cloze needs at least one {{c1::…}}");
  const note = { id: nid, guid: String(nid), mid: model.id, fields, tags };
  const cards = ords.map((ord, i) => newCardState({ id: nid + i + 1, nid, did, ord }));
  await db.put("notes", note);
  await db.putMany("cards", cards);
  return note;
}

export async function add(ctx) {
  const timer = await timerFor(ctx);
  const [decks, models] = await Promise.all([db.getAll("decks"), db.getAll("models")]);
  let added = 0;

  const deckSel = h("select", { class: "select-pill", "aria-label": "Deck" }, decks.map((d) => h("option", { value: d.id }, d.name)));
  const modelSel = h("select", { class: "select-pill", "aria-label": "Note type" }, models.map((m) => h("option", { value: m.id }, m.name)));
  const tags = h("input", { class: "text-input", placeholder: "tags, space separated", autocapitalize: "none" });
  const fieldsBox = h("div", { class: "stack" });
  const counter = h("p", { class: "caption muted" });
  let inputs = [];

  const drawFields = () => {
    const m = models.find((x) => x.id === Number(modelSel.value));
    inputs = m.fields.map((f) => h("textarea", { class: "text-input", rows: 2, "aria-label": f }));
    fieldsBox.replaceChildren(...m.fields.map((f, i) => h("div", { class: "field" }, h("label", {}, f), inputs[i])));
    if (m.cloze) fieldsBox.prepend(h("p", { class: "caption muted" }, "Wrap hidden text as {{c1::answer}}."));
  };
  modelSel.addEventListener("change", drawFields);
  drawFields();

  const submit = async () => {
    const m = models.find((x) => x.id === Number(modelSel.value));
    const values = inputs.map((i) => i.value.trim());
    if (!values[0]) { toast("Fill in the first field"); return; }
    try {
      await createNote({ did: Number(deckSel.value), model: m, fields: values, tags: tags.value.split(/\s+/).filter(Boolean) });
    } catch (e) { toast(e.message); return; }
    inputs.forEach((i) => (i.value = ""));
    inputs[0].focus();
    counter.textContent = `${++added} added this visit`;
    toast("Card added");
  };

  return h("div", { class: "page" },
    h("h1", { class: "display-lg" }, "Add card"),
    timer && h("div", { class: "feature-card" }, timer.el),
    h("div", { class: "stack" },
      h("div", { class: "field" }, h("label", {}, "Deck"), deckSel),
      h("div", { class: "field" }, h("label", {}, "Type"), modelSel),
      fieldsBox,
      h("div", { class: "field" }, h("label", {}, "Tags"), tags),
      h("button", { class: "btn btn-primary btn-block", onClick: submit }, "Add"),
      counter));
}
