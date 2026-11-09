import { placeLevel, QUESTIONS, LEVELS } from "../js/placement.js";
const ok = (c, m) => { if (!c) { console.log("FAIL", m); process.exitCode = 1; } else console.log("ok  ", m); };

ok(placeLevel([]) === "A1", "no answers → A1");
ok(placeLevel([2]) === "A1", "failing A1 → A1");
ok(placeLevel([4, 3, 2]) === "A2", "stops at the first failed level");
ok(placeLevel([4, 4, 4, 3, 3]) === "C1", "passing everything → C1");
ok(placeLevel([4, 1, 4, 4]) === "A1", "later passes don't count after a failure");
ok(LEVELS.every((l) => QUESTIONS[l].length === 4), "four questions per level");
ok(Object.values(QUESTIONS).flat().every(([t, o, a]) => t.includes("____") && o.length === 4 && o[a] && new Set(o).size === 4), "questions well-formed");
