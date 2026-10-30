// Minimal Anki template renderer + sanitizer for imported HTML.

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function cloze(text, ord, reveal) {
  return text.replace(/\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}/gs, (_, n, ans, hint) => {
    if (Number(n) !== ord + 1) return ans;
    return reveal ? `<b>${ans}</b>` : `<b>[${hint || "..."}]</b>`;
  });
}

function fill(tpl, fields, ctx) {
  // sections: {{#F}}..{{/F}} and {{^F}}..{{/F}}
  tpl = tpl.replace(/\{\{([#^])([^}]+)\}\}(.*?)\{\{\/\2\}\}/gs, (_, kind, name, inner) => {
    const has = (fields[name.trim()] || "").trim() !== "";
    return (kind === "#") === has ? fill(inner, fields, ctx) : "";
  });
  return tpl.replace(/\{\{([^}]+)\}\}/g, (_, expr) => {
    const parts = expr.trim().split(":");
    const name = parts.pop();
    const mods = parts;
    if (name === "FrontSide") return ctx.front ?? "";
    if (name === "Tags") return esc(ctx.tags.join(" "));
    let val = fields[name] ?? "";
    if (mods.includes("cloze")) val = cloze(val, ctx.ord, ctx.reveal);
    if (mods.includes("type")) return "";
    if (mods.includes("text")) val = val.replace(/<[^>]*>/g, "");
    return val;
  });
}

export function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("script,iframe,object,embed,link,meta,style,base,form").forEach((n) => n.remove());
  doc.body.querySelectorAll("*").forEach((el) => {
    for (const a of [...el.attributes]) {
      if (/^on/i.test(a.name) || /^\s*javascript:/i.test(a.value)) el.removeAttribute(a.name);
    }
  });
  return doc.body.innerHTML;
}

const PLAY = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5z"/></svg>';
const soundButtons = (s) =>
  s.replace(/\[sound:([^\]]*)\]/g, (_, f) => `<button type="button" class="sound" data-sound="${esc(f)}" aria-label="Play audio">${PLAY}</button>`);

export function renderCard(note, model, ord, tags = note.tags) {
  const fields = Object.fromEntries(model.fields.map((f, i) => [f, soundButtons(note.fields[i] || "")]));
  const t = model.templates[model.cloze ? 0 : ord] || model.templates[0];
  const base = { ord, tags };
  const front = fill(t.qfmt, fields, { ...base, reveal: false });
  const back = fill(t.afmt, fields, { ...base, reveal: true, front });
  return { front: sanitize(front), back: sanitize(back) };
}

export function plainText(html) {
  return new DOMParser().parseFromString(html, "text/html").body.textContent || "";
}
