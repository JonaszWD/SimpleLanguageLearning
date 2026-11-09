// "Report a problem": notes about the app itself, kept on this device until they're dealt with.
import { h, toast, icon } from "../util.js";
import * as db from "../db.js";
import { topNav } from "./shared.js";

const fmt = (ts) => new Date(ts).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export async function report() {
  const text = h("textarea", { class: "text-input", rows: 4, placeholder: "What went wrong, or what should change?" });
  const list = h("div", { class: "stack" });

  const paint = async () => {
    const items = (await db.getAll("reports")).sort((a, b) => b.ts - a.ts);
    list.replaceChildren(items.length
      ? h("div", { class: "feature-card stack" },
        h("div", { class: "row between" },
          h("span", { class: "caption-uppercase muted" }, `Saved · ${items.length}`),
          h("button", { class: "btn btn-text", onClick: async () => {
            const all = items.map((r) => `- ${r.text}`).join("\n");
            try { await navigator.clipboard.writeText(all); toast("Copied all"); } catch { toast("Couldn't copy"); }
          } }, "Copy all")),
        items.map((r) => h("div", { class: "list-row", style: "align-items:flex-start" },
          h("span", { class: "grow" },
            h("span", { class: "body-sm", style: "display:block;white-space:pre-wrap" }, r.text),
            h("span", { class: "caption muted" }, fmt(r.ts))),
          h("button", { class: "icon-btn", "aria-label": "Delete", onClick: async () => { await db.del("reports", r.id); paint(); } }, icon("trash")))))
      : h("p", { class: "caption muted" }, "Nothing saved yet."));
  };

  const save = async () => {
    const t = text.value.trim();
    if (!t) { toast("Describe the problem first"); return; }
    await db.put("reports", { id: Date.now(), ts: Date.now(), text: t });
    text.value = "";
    toast("Saved");
    paint();
  };

  await paint();
  return h("div", {}, topNav("Report a problem", "/today"),
    h("div", { class: "page has-top" },
      h("h1", { class: "display-md" }, "Report a problem"),
      h("p", { class: "muted" }, "Notes are saved on this device. Use Copy all to pass them on."),
      h("div", { class: "stack" }, text, h("button", { class: "btn btn-primary btn-block", onClick: save }, "Save")),
      list));
}
