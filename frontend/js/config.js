// Where content packs (deck + audio) are downloaded from.
// "" = this server (/packs). For static hosting set the GitHub Pages URL, e.g.
//   export const PACKS_BASE = "https://<user>.github.io/<repo>";
export const PACKS_BASE = "https://jonaszwd.github.io/SimpleLanguageLearning";

export const packsUrl = (path = "") => `${PACKS_BASE || "/packs"}${path}`;
