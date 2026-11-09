// Rearrangeable bento grid (vanilla port of Kokonut UI's Widget Grid: spans, drag-to-reorder, saved layout).
// Two columns on every screen so it stays usable on a phone. Tiles are plain links until "Edit" is on;
// then the grip handle drags (only the handle blocks touch scrolling) and the buttons move/resize without dragging.
// bentoGroups() returns { toggle, status, el }: the caller places the Edit button in its own header.
// Tiles reorder within their category; spans and order are saved as one flat list.
//   groups: [{ id, title, items }]   items: [{ id, href, icon, title, caption, tint?, defaultSpan? }]   layout: [{ id, span }]  span: 1 | 2
import { h, icon } from "./util.js";

export function normalize(layout, items) {
  const known = new Set(items.map((i) => i.id)), seen = new Set(), out = [];
  for (const e of layout || []) {
    if (known.has(e.id) && !seen.has(e.id)) { seen.add(e.id); out.push({ id: e.id, span: e.span === 2 ? 2 : 1 }); }
  }
  for (const i of items) if (!seen.has(i.id)) out.push({ id: i.id, span: i.defaultSpan === 2 ? 2 : 1 });
  return out;
}

function board(items, layout, onChange, say) {
  const byId = new Map(items.map((i) => [i.id, i]));
  let order = normalize(layout, items);
  let editing = false;
  const grid = h("div", { class: "bento" });
  const save = () => onChange(order.map((e) => ({ ...e })));

  const draw = () => {
    grid.classList.toggle("editing", editing);
    grid.replaceChildren(...order.map((e, idx) => tile(byId.get(e.id), e, idx)));
  };

  const move = (idx, to) => {
    if (to < 0 || to >= order.length) return;
    const [m] = order.splice(idx, 1);
    order.splice(to, 0, m);
    save(); draw();
    say(`${byId.get(m.id).title} moved to position ${to + 1} of ${order.length}`);
    grid.children[to].querySelector(".bento-grip")?.focus();
  };
  const resize = (e) => {
    e.span = e.span === 2 ? 1 : 2;
    save(); draw();
    say(`${byId.get(e.id).title} is now ${e.span === 2 ? "wide" : "narrow"}`);
  };

  function tile(it, e, idx) {
    const wide = e.span === 2;
    const body = [
      h("span", { class: "plate" }, icon(it.icon)),
      h("span", { class: "bento-text" },
        h("span", { class: "title-sm" }, it.title),
        h("span", { class: "caption muted" }, it.caption)),
    ];
    const cls = `bento-tile${wide ? " wide" : ""}${it.tint ? ` orb-${it.tint}` : ""}`;
    if (!editing) return h("a", { class: cls, href: it.href, "data-id": e.id }, ...body, h("span", { class: "bento-go" }, icon("chevron")));

    const grip = h("button", { class: "bento-grip icon-btn", "aria-label": `Drag ${it.title}. Arrow keys also move it.`, onPointerdown: (ev) => startDrag(ev, el, e.id),
      onKeydown: (ev) => {
        const step = { ArrowUp: -2, ArrowLeft: -1, ArrowDown: 2, ArrowRight: 1 }[ev.key];
        if (step) { ev.preventDefault(); const at = order.findIndex((o) => o.id === e.id); move(at, at + step); }
      } }, icon("grip"));
    const el = h("div", { class: cls, "data-id": e.id },
      ...body,
      h("span", { class: "bento-tools" }, grip,
        h("button", { class: "icon-btn", "aria-label": `Make ${it.title} ${wide ? "narrow" : "wide"}`, onClick: () => resize(e) }, icon(wide ? "shrink" : "expand"))));
    return el;
  }

  // Pointer drag: the tile follows the finger; whichever tile the pointer crosses swaps places live.
  function startDrag(ev, el, id) {
    if (ev.button > 0) return;
    ev.preventDefault();
    const handle = ev.currentTarget;
    handle.setPointerCapture(ev.pointerId);
    el.classList.add("lifted");
    let px = ev.clientX, py = ev.clientY, raf = 0;
    const place = () => {
      el.style.transform = "";
      const r = el.getBoundingClientRect();
      // grab offset stays under the finger: shift by pointer minus the tile's grab point
      el.style.transform = `translate(${px - grabX - r.left}px, ${py - grabY - r.top}px)`;
    };
    const r0 = el.getBoundingClientRect();
    const grabX = ev.clientX - r0.left, grabY = ev.clientY - r0.top;
    const overlap = () => {
      for (const t of grid.children) {
        if (t === el) continue;
        const r = t.getBoundingClientRect();
        if (px >= r.left && px <= r.right && py >= r.top && py <= r.bottom) {
          const from = order.findIndex((o) => o.id === id), to = order.findIndex((o) => o.id === t.dataset.id);
          const [m] = order.splice(from, 1); order.splice(to, 0, m);
          // FLIP the siblings so the swap animates
          const rects = new Map([...grid.children].map((c) => [c, c.getBoundingClientRect()]));
          if (to < from) t.before(el); else t.after(el);
          for (const [c, old] of rects) {
            if (c === el) continue;
            const now = c.getBoundingClientRect();
            const dx = old.left - now.left, dy = old.top - now.top;
            if (dx || dy) c.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: "none" }], { duration: 180, easing: "ease-out" });
          }
          break;
        }
      }
    };
    const edge = () => {
      const m = 90, dy = py < m ? -12 : py > innerHeight - m ? 12 : 0;
      if (dy) { scrollBy(0, dy); place(); overlap(); raf = requestAnimationFrame(edge); } else raf = 0;
    };
    const move = (e2) => {
      if (e2.pointerId !== ev.pointerId) return;
      px = e2.clientX; py = e2.clientY;
      place(); overlap(); place();
      if (!raf && (py < 90 || py > innerHeight - 90)) raf = requestAnimationFrame(edge);
    };
    const end = (e2) => {
      if (e2.pointerId !== ev.pointerId) return;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      cancelAnimationFrame(raf);
      el.classList.remove("lifted"); el.style.transform = "";
      save(); say("Layout saved");
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
    place();
  }

  const setEditing = (v) => { editing = v; draw(); };
  draw();
  return { grid, setEditing };
}

export function bentoGroups(groups, layout, onChange) {
  const toggle = h("button", { class: "btn btn-outline", "aria-pressed": "false" }, "Edit layout");
  const status = h("p", { class: "caption muted", role: "status", "aria-live": "polite" });
  const say = (t) => { status.textContent = t; };
  const orders = groups.map((g) => normalize((layout || []).filter((e) => g.items.some((i) => i.id === e.id)), g.items));
  const save = () => onChange(orders.flat());
  const boards = groups.map((g, gi) => board(g.items, orders[gi], (l) => { orders[gi] = l; save(); }, say));
  let editing = false;
  toggle.onclick = () => {
    editing = !editing;
    toggle.textContent = editing ? "Done" : "Edit layout";
    toggle.className = `btn ${editing ? "btn-primary" : "btn-outline"}`;
    toggle.setAttribute("aria-pressed", String(editing));
    say(editing ? "Drag the handle, or use the arrow keys, to reorder within a category. Wide button resizes." : "");
    boards.forEach((b) => b.setEditing(editing));
  };
  const el = h("div", { class: "stack", style: "gap:var(--s-lg)" }, groups.map((g, gi) =>
    h("section", { class: "stack", "aria-labelledby": `bento-${g.id}` },
      h("h2", { id: `bento-${g.id}`, class: "caption-uppercase muted" }, g.title), boards[gi].grid)));
  return { toggle, status, el };
}
