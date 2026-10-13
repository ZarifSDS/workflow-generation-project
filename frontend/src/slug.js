// Heading ids, mirroring apps/content/dialect.py slugify(): ASCII-folded, lowercase, every run of
// other characters becomes "-", trimmed; "section" if nothing is left. Repeats get -2, -3 (uniqueIds).

export function slugify(text) {
  const ascii = String(text).normalize("NFKD").replace(/[^\x00-\x7F]/g, "");
  return ascii.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "section";
}

/** Ids for a list of headings ({text, anchor}), in document order, as the server renders them. */
export function uniqueIds(headings) {
  const used = new Set();
  return headings.map(({ text, anchor }) => {
    const base = anchor || slugify(text);
    let id = base;
    for (let n = 2; used.has(id); n += 1) id = `${base}-${n}`;
    used.add(id);
    return id;
  });
}
