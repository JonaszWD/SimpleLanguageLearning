// Activity terrain: a year of daily activity as a draggable 3D bar chart on a canvas.
// Vanilla port of Kokonut UI's activity-terrain (MIT, https://kokonutui.com).
import { h } from "./util.js";

const DAYS = 7;
const GAP = 0.18;
const MAX_HEIGHT = 4.2; // tallest column, in cells
const DEG = Math.PI / 180;
const PITCH_TERRAIN = 56 * DEG;
const YAW_TERRAIN = 18 * DEG;
const YAW_LIMIT = 38 * DEG;
const PITCH_LIMIT = 66 * DEG;
const DRAG_YAW = 0.32 * DEG;
const DRAG_PITCH = 0.36 * DEG;
const SPIN_HALF_LIFE = 0.16; // seconds
const SPIN_IN = (YAW_TERRAIN * Math.LN2) / SPIN_HALF_LIFE;
const PITCH_STIFFNESS = 140;
const PITCH_DAMPING = 2 * Math.sqrt(PITCH_STIFFNESS);
const EDGE_STIFFNESS = 180;
const BUMP_STIFFNESS = 400;
const BUMP_DAMPING = 2 * Math.sqrt(BUMP_STIFFNESS) * 0.7;
const BUMP = 0.45;
const WAVE = 0.7; // far end of the rise lags by this share
const PADDING = 20;
const REST_EPSILON = 0.0005;
const LABELS = ["Mon", "", "Wed", "", "Fri", "", ""];
const DAY_MS = 86_400_000;

const clamp = (v, min, max) => Math.min(max, Math.max(min, v));
const easeOutBack = (t) => { const u = t - 1; return 1 + 2.4 * u * u * u + 1.4 * u * u; };
function rubber(v, min, max) {
  if (v < min) return min - 0.18 * (1 - Math.exp((v - min) / 0.18));
  if (v > max) return max + 0.18 * (1 - Math.exp((max - v) / 0.18));
  return v;
}

const fmtDay = (d) => d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
const fmtMonth = (d) => d.toLocaleDateString(undefined, { month: "short", timeZone: "UTC" });

// counts: oldest first, one per day. endDate: "YYYY-MM-DD" of the last one.
function buildCells(counts, endDate) {
  const [y, m, d] = endDate.split("-").map(Number);
  const end = Date.UTC(y, m - 1, d);
  const start = end - (counts.length - 1) * DAY_MS;
  const offset = (new Date(start).getUTCDay() + 6) % 7; // rows run Mon..Sun
  const max = Math.max(1, ...counts);
  return counts.map((count, index) => {
    const slot = index + offset, norm = count / max;
    return { index, col: Math.floor(slot / DAYS), row: slot % DAYS, count,
      level: count === 0 ? 0 : Math.ceil(norm * 4),
      height: 0.06 + norm ** 0.85 * MAX_HEIGHT,
      date: new Date(start + index * DAY_MS) };
  });
}

function hexToRgb(value) {
  let hex = value.trim().replace("#", "");
  if (hex.length === 3) hex = hex.replace(/./g, "$&$&");
  const n = parseInt(hex, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const shade = ([r, g, b], a) => { const k = 1 - a; return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})`; };

function readPalette(node) {
  const st = getComputedStyle(node);
  const read = (n) => st.getPropertyValue(n) || "#888888";
  return { levels: [0, 1, 2, 3, 4].map((l) => hexToRgb(read(`--terrain-${l}`))), accent: hexToRgb(read("--terrain-accent")), text: read("--terrain-text").trim(), font: st.fontFamily };
}

function project(pose, x, y, z) {
  const cos = Math.cos(pose.yaw), sin = Math.sin(pose.yaw);
  return [pose.cx + (x * cos - z * sin) * pose.scale,
    pose.cy + ((x * sin + z * cos) * Math.cos(pose.pitch) - y * Math.sin(pose.pitch)) * pose.scale];
}

// Faces of one column that face the camera, top last.
function visibleFaces(pose, x0, z0, hgt) {
  const x1 = x0 + 1 - GAP, z1 = z0 + 1 - GAP;
  const p = (x, y, z) => project(pose, x, y, z);
  const faces = [], sin = Math.sin(pose.yaw), cos = Math.cos(pose.yaw);
  if (hgt > 0.02 && pose.pitch > 0.01) {
    const z = cos > 0 ? z1 : z0;
    faces.push({ points: [p(x0, 0, z), p(x1, 0, z), p(x1, hgt, z), p(x0, hgt, z)], tone: 0.22 });
    if (sin > 0.001) faces.push({ points: [p(x1, 0, z0), p(x1, 0, z1), p(x1, hgt, z1), p(x1, hgt, z0)], tone: 0.38 });
    else if (sin < -0.001) faces.push({ points: [p(x0, 0, z0), p(x0, 0, z1), p(x0, hgt, z1), p(x0, hgt, z0)], tone: 0.38 });
  }
  faces.push({ points: [p(x0, hgt, z0), p(x1, hgt, z0), p(x1, hgt, z1), p(x0, hgt, z1)], tone: 0 });
  return faces;
}

function inside(points, x, y) {
  let hit = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [xi, yi] = points[i], [xj, yj] = points[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function polygon(ctx, pts) {
  ctx.beginPath();
  ctx.moveTo(pts[0][0], pts[0][1]);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
  ctx.closePath();
}

// ranges: [{ label: "Week", span: "week", counts, endDate }, ...]; the first is shown at start.
export function activityTerrain({ ranges, unit = "activity", title = "Activity" }) {
  let range = ranges[0];
  let cells, weeks, total, defaultReadout;
  const load = (r) => {
    range = r;
    cells = buildCells(r.counts, r.endDate);
    weeks = cells[cells.length - 1].col + 1;
    total = r.counts.reduce((a, b) => a + b, 0);
    defaultReadout = `${total.toLocaleString()} ${unit} in the last ${r.span}`;
  };
  load(range);

  const canvas = h("canvas", { class: "terrain-canvas", role: "img", tabindex: "0" });
  const describe = () => canvas.setAttribute("aria-label", `${title}: ${total} ${unit} over the last ${range.span}. Use the arrow keys to read each day.`);
  describe();
  const readout = h("p", { class: "caption muted", "aria-live": "polite" }, defaultReadout);
  const toggles = [["Flat", true], ["Terrain", false]].map(([name, value]) =>
    h("button", { type: "button", class: "terrain-toggle", "aria-pressed": String(!value), onClick: () => value !== flat && setView(value) }, name));
  const rangeBtns = ranges.map((r) =>
    h("button", { type: "button", class: "terrain-toggle", "aria-pressed": String(r === range), onClick: () => r !== range && setRange(r) }, r.label));
  const root = h("div", { class: "stack terrain" },
    h("div", { class: "stack", style: "gap:2px;min-width:0" }, h("span", { class: "caption-uppercase muted" }, title), readout),
    h("div", { class: "row between" },
      h("div", { class: "terrain-toggles" }, rangeBtns),
      h("div", { class: "terrain-toggles" }, toggles)),
    canvas,
    h("div", { class: "terrain-legend caption muted" }, "Less",
      [0, 1, 2, 3, 4].map((l) => h("i", { style: `background:var(--terrain-${l})` })), "More"));

  let flat = false, palette = null;
  const s = { yaw: 0, yawSpeed: 0, pitch: 0, pitchSpeed: 0, pitchTarget: PITCH_TERRAIN,
    bumps: new Float64Array(cells.length), bumpSpeeds: new Float64Array(cells.length),
    hovered: -1, origin: { col: 0, row: 3 }, width: 0, height: 0, dpr: 1, drag: null,
    raf: 0, last: 0, visible: false, started: false, reduceMotion: false };

  const columnHeight = (cell, lift) => {
    const span = Math.hypot(weeks, DAYS) || 1;
    const d = Math.hypot(cell.col - s.origin.col, cell.row - s.origin.row) / span;
    return cell.height * easeOutBack(clamp(lift * (1 + WAVE) - d * WAVE, 0, 1)) + s.bumps[cell.index];
  };

  const pose = () => {
    const lift = clamp(s.pitch / PITCH_TERRAIN, 0, 1.2);
    const probe = { yaw: s.yaw, pitch: s.pitch, scale: 1, cx: 0, cy: 0 };
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const [x, z] of [[0, 0], [weeks, 0], [0, DAYS], [weeks, DAYS]]) {
      for (const y of [0, MAX_HEIGHT * Math.min(lift, 1)]) {
        const [px, py] = project(probe, x - weeks / 2, y, z - DAYS / 2);
        minX = Math.min(minX, px); maxX = Math.max(maxX, px); minY = Math.min(minY, py); maxY = Math.max(maxY, py);
      }
    }
    const scale = Math.min((s.width - PADDING * 2) / (maxX - minX), (s.height - PADDING * 2) / (maxY - minY));
    return { yaw: s.yaw, pitch: s.pitch, scale, cx: s.width / 2 - ((minX + maxX) / 2) * scale,
      cy: s.height / 2 - ((minY + maxY) / 2) * scale + 6, lift };
  };

  const ordered = (p) => {
    const sin = Math.sin(p.yaw), cos = Math.cos(p.yaw);
    const depth = (c) => (c.col + 0.5 - weeks / 2) * sin + (c.row + 0.5 - DAYS / 2) * cos;
    return [...cells].sort((a, b) => depth(a) - depth(b));
  };

  function drawLabels(ctx, p, lift) {
    const alpha = clamp(1 - lift * 1.6, 0, 1);
    if (alpha === 0) return;
    ctx.globalAlpha = alpha;
    ctx.fillStyle = palette.text;
    ctx.font = `11px ${palette.font}`;
    ctx.textBaseline = "middle";
    ctx.textAlign = "left";
    let month = -1;
    for (const cell of cells) {
      if (cell.row !== 0 && cell.index !== 0) continue;
      const m = cell.date.getUTCMonth();
      if (m !== month && cell.col < weeks - 1) {
        month = m;
        const [x, y] = project(p, cell.col - weeks / 2, 0, -0.75 - DAYS / 2);
        ctx.fillText(fmtMonth(cell.date), x, y);
      }
    }
    ctx.textAlign = "right";
    for (let row = 0; row < DAYS; row++) {
      if (!LABELS[row]) continue;
      const [x, y] = project(p, -0.35 - weeks / 2, 0, row + 0.4 - DAYS / 2);
      ctx.fillText(LABELS[row], x, y);
    }
    ctx.globalAlpha = 1;
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    if (!ctx || !s.width) return;
    palette ??= readPalette(canvas);
    const p = pose();
    ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
    ctx.clearRect(0, 0, s.width, s.height);
    drawLabels(ctx, p, p.lift);
    ctx.lineJoin = "round";
    for (const cell of ordered(p)) {
      const color = cell.index === s.hovered ? palette.accent : palette.levels[cell.level];
      for (const face of visibleFaces(p, cell.col - weeks / 2, cell.row - DAYS / 2, columnHeight(cell, p.lift))) {
        polygon(ctx, face.points);
        const fill = shade(color, face.tone);
        ctx.fillStyle = fill; ctx.fill();
        ctx.strokeStyle = fill; ctx.lineWidth = 0.6; ctx.stroke(); // closes seams
      }
    }
  }

  function hitTest(x, y) {
    const p = pose(), list = ordered(p);
    for (let i = list.length - 1; i >= 0; i--) {
      const cell = list[i];
      for (const face of visibleFaces(p, cell.col - weeks / 2, cell.row - DAYS / 2, columnHeight(cell, p.lift)))
        if (inside(face.points, x, y)) return cell;
    }
    return null;
  }

  function stepSprings(dt) {
    let energy = 0;
    if (!s.drag) {
      s.yawSpeed *= 0.5 ** (dt / SPIN_HALF_LIFE);
      let target = s.yaw;
      if (s.pitchTarget === 0) target = 0;
      else if (s.yaw > YAW_LIMIT) target = YAW_LIMIT;
      else if (s.yaw < -YAW_LIMIT) target = -YAW_LIMIT;
      if (target !== s.yaw) s.yawSpeed += ((target - s.yaw) * EDGE_STIFFNESS - s.yawSpeed * 2 * Math.sqrt(EDGE_STIFFNESS)) * dt;
      s.yaw += s.yawSpeed * dt;
      energy = Math.max(energy, Math.abs(s.yawSpeed), Math.abs(target - s.yaw));
      s.pitchSpeed += ((s.pitchTarget - s.pitch) * PITCH_STIFFNESS - s.pitchSpeed * PITCH_DAMPING) * dt;
      s.pitch += s.pitchSpeed * dt;
      energy = Math.max(energy, Math.abs(s.pitchSpeed), Math.abs(s.pitchTarget - s.pitch));
    }
    for (let i = 0; i < s.bumps.length; i++) {
      const target = i === s.hovered && s.pitch > 0.1 ? BUMP : 0;
      s.bumpSpeeds[i] += ((target - s.bumps[i]) * BUMP_STIFFNESS - s.bumpSpeeds[i] * BUMP_DAMPING) * dt;
      s.bumps[i] += s.bumpSpeeds[i] * dt;
      energy = Math.max(energy, Math.abs(s.bumpSpeeds[i]) * 0.1, Math.abs(target - s.bumps[i]));
    }
    return energy;
  }

  function tick(now) {
    s.raf = 0;
    if (!canvas.isConnected) return; // view was replaced
    const dt = s.last ? Math.min((now - s.last) / 1000, 1 / 30) : 1 / 60;
    s.last = now;
    const energy = stepSprings(dt);
    draw();
    if ((s.drag || energy > REST_EPSILON) && s.visible) s.raf = requestAnimationFrame(tick);
    else s.last = 0;
  }

  function turnIn() {
    if (Math.abs(s.yaw) > 2 * DEG) return;
    if (s.reduceMotion) s.yaw = YAW_TERRAIN; else s.yawSpeed = SPIN_IN;
  }

  function wake() {
    if (s.reduceMotion) {
      s.pitch = s.pitchTarget; s.yaw = clamp(s.yaw, -YAW_LIMIT, YAW_LIMIT);
      s.pitchSpeed = 0; s.yawSpeed = 0; s.bumps.fill(0);
      draw();
      return;
    }
    if (!s.raf && s.visible) s.raf = requestAnimationFrame(tick);
  }

  function syncToggles() { toggles.forEach((b, i) => b.setAttribute("aria-pressed", String(flat === (i === 0)))); }
  function setView(nextFlat) {
    flat = nextFlat; syncToggles();
    s.origin = { col: nextFlat ? weeks : 0, row: 3 };
    s.pitchTarget = nextFlat ? 0 : PITCH_TERRAIN;
    s.yawSpeed = 0;
    if (!nextFlat) turnIn();
    wake();
  }

  function setRange(r) {
    load(r);
    rangeBtns.forEach((b, i) => b.setAttribute("aria-pressed", String(ranges[i] === r)));
    s.bumps = new Float64Array(cells.length); s.bumpSpeeds = new Float64Array(cells.length);
    s.hovered = -1; s.origin = { col: flat ? weeks : 0, row: 3 };
    readout.textContent = defaultReadout; describe();
    if (!flat) { s.pitch = 0; s.pitchSpeed = 0; s.yaw = 0; turnIn(); } // replay the rise
    wake();
  }

  function hover(cell) {
    const index = cell ? cell.index : -1;
    if (index === s.hovered) return;
    s.hovered = index;
    readout.textContent = cell ? `${cell.count} ${unit} on ${fmtDay(cell.date)}` : defaultReadout;
    if (s.reduceMotion) draw(); else wake();
  }

  const local = (e) => { const r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };

  canvas.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const { x, y } = local(e);
    canvas.setPointerCapture(e.pointerId);
    const cell = hitTest(x, y);
    if (cell) s.origin = { col: cell.col, row: cell.row };
    s.drag = { id: e.pointerId, x: e.clientX, y: e.clientY, yaw: s.yaw, pitch: s.pitch, moved: false,
      samples: [{ t: e.timeStamp, x: e.clientX, y: e.clientY }] };
    s.yawSpeed = 0; s.pitchSpeed = 0;
    canvas.classList.add("dragging");
    hover(cell); wake();
  });

  canvas.addEventListener("pointermove", (e) => {
    const drag = s.drag;
    if (!drag || drag.id !== e.pointerId) {
      if (e.pointerType === "mouse") { const { x, y } = local(e); hover(hitTest(x, y)); }
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) > 4) drag.moved = true;
    if (!drag.moved) return;
    s.yaw = rubber(drag.yaw + dx * DRAG_YAW, -YAW_LIMIT, YAW_LIMIT);
    s.pitch = rubber(drag.pitch + dy * DRAG_PITCH, 0, PITCH_LIMIT);
    drag.samples.push({ t: e.timeStamp, x: e.clientX, y: e.clientY });
    if (drag.samples.length > 5) drag.samples.shift();
    if (s.reduceMotion) draw(); else wake();
  });

  const release = (e) => {
    const drag = s.drag;
    if (!drag || drag.id !== e.pointerId) return;
    s.drag = null;
    canvas.classList.remove("dragging");
    if (!drag.moved) return wake();
    const first = drag.samples[0], last = drag.samples[drag.samples.length - 1] || first;
    const dt = Math.max((last.t - first.t) / 1000, 0.016);
    const recent = e.timeStamp - last.t < 80;
    s.yawSpeed = recent ? ((last.x - first.x) / dt) * DRAG_YAW : 0;
    s.pitchSpeed = recent ? ((last.y - first.y) / dt) * DRAG_PITCH : 0;
    flat = s.pitch + s.pitchSpeed * 0.15 < PITCH_TERRAIN / 2; // land on the view the throw heads for
    s.pitchTarget = flat ? 0 : PITCH_TERRAIN;
    syncToggles(); wake();
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
  canvas.addEventListener("lostpointercapture", release);
  canvas.addEventListener("pointerleave", (e) => { if (!s.drag && e.pointerType === "mouse") hover(null); });
  canvas.addEventListener("blur", () => { if (!s.drag) hover(null); });

  canvas.addEventListener("keydown", (e) => {
    const move = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!move) return;
    e.preventDefault();
    const cur = cells[s.hovered] ?? cells[cells.length - 1];
    hover(cells.find((c) => c.col === cur.col + move[0] && c.row === cur.row + move[1]) ?? cur);
  });

  // Needs the canvas laid out and on screen, so wire observers once mounted.
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  s.reduceMotion = motion.matches;
  let onScreen = false;
  const update = () => {
    s.visible = onScreen && !document.hidden && canvas.isConnected;
    if (s.visible) {
      if (!s.started) { s.started = true; if (s.pitchTarget > 0) turnIn(); }
      wake();
    } else if (s.raf) { cancelAnimationFrame(s.raf); s.raf = 0; s.last = 0; }
  };
  new ResizeObserver(([entry]) => {
    s.width = entry.contentRect.width; s.height = entry.contentRect.height;
    s.dpr = Math.min(devicePixelRatio || 1, 2);
    canvas.width = Math.round(s.width * s.dpr); canvas.height = Math.round(s.height * s.dpr);
    draw();
  }).observe(canvas);
  new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; update(); }).observe(canvas);
  document.addEventListener("visibilitychange", update);
  const repaint = () => { palette = null; draw(); };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", repaint);

  return root;
}
