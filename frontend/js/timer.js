// Active-time tracker for a plan task. Counts only while the page is visible.
import * as db from "./db.js";
import { allTasks } from "./plan.js";
import { dateKey, flashCorners, fmtClock, h, toast } from "./util.js";

export async function taskTimer(taskId, onLeave) {
  const task = allTasks(new Date()).find((t) => t.id === taskId);
  if (!task) return null;
  const date = dateKey();
  let day = await db.getDay(date);
  const rec = (day.tasks[taskId] ??= { secs: 0, done: false });
  const target = (task.min || 0) * 60;

  const bar = h("i");
  const label = h("span", { class: "caption" });
  const el = h("div", { class: "timer" }, h("div", { class: "progress" }, bar), label);

  const paint = () => {
    bar.style.width = rec.done ? "100%" : target ? `${Math.min(100, (rec.secs / target) * 100)}%` : "0";
    label.textContent = target ? `${fmtClock(rec.secs)} / ${task.min}:00` : rec.done ? "Done" : "";
  };
  const save = () => db.saveDay(day);
  paint();

  // Completes the task once, with feedback; no-op if already done.
  const finish = (msg) => {
    if (rec.done) return;
    rec.done = true; paint(); toast(msg); flashCorners(); save();
  };

  let last = Date.now();
  const tick = () => {
    const now = Date.now();
    if (!document.hidden && target) {
      rec.secs += (now - last) / 1000;
      if (rec.secs >= target) finish(`${task.min} min done`);
      paint();
    }
    last = now;
  };
  const iv = setInterval(tick, 1000);
  const saver = setInterval(save, 5000);
  const flush = () => { tick(); save(); };
  document.addEventListener("visibilitychange", flush);
  addEventListener("pagehide", flush);
  onLeave(() => {
    clearInterval(iv); clearInterval(saver);
    document.removeEventListener("visibilitychange", flush);
    removeEventListener("pagehide", flush);
    flush();
  });

  return {
    el,
    task,
    done: () => rec.done,
    timed: !!target,
    // For tasks that can finish before the timer does (e.g. every Anki card answered).
    complete: () => finish("Task done"),
    // Timed tasks complete only when the timer reaches the target.
    async markDone() { if (target) return; rec.done = true; paint(); await save(); },
  };
}
