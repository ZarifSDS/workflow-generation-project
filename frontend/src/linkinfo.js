// Shows where a link goes when you hover it (or move the cursor into it): the page or document title for
// wagtail:// links, the heading for #anchors, the address otherwise. The tooltip lives outside the
// editable area, so ProseMirror's DOM is never touched.

import { headingTargets, parseHref } from "./links.js";
import { el } from "./ui.js";

export function describeLink(href, refs, doc) {
  const target = parseHref(href);
  const lookup = (kind) => (refs[`${kind}s`] || {})[target.id];
  switch (target.type) {
    case "page":
      return lookup("page") ? `Page: ${lookup("page").title}` : `Page ${target.id}`;
    case "document":
      return lookup("document") ? `Document: ${lookup("document").title}` : `Document ${target.id}`;
    case "anchor": {
      const heading = doc ? headingTargets(doc).find((h) => h.id === target.anchor) : null;
      return heading ? `Heading: ${heading.text}` : `#${target.anchor} (no heading with this id)`;
    }
    case "email":
      return `Email: ${target.address}`;
    case "phone":
      return `Phone: ${target.number}`;
    default:
      return target.url;
  }
}

export function attachLinkInfo(ctx, surface) {
  const tip = el("div", { class: "se-linktip", role: "tooltip", hidden: true });
  document.body.append(tip);
  const asked = new Set();

  async function fetchMissing(href) {
    const target = parseHref(href);
    if (!["page", "document"].includes(target.type)) return;
    const known = (ctx.refs[`${target.type}s`] || {})[target.id];
    const key = `${target.type}:${target.id}`;
    if (known || asked.has(key)) return;
    asked.add(key);
    try {
      const data = await ctx.api.references({ [`${target.type}s`]: [target.id] });
      ctx.refs[`${target.type}s`] = { ...(ctx.refs[`${target.type}s`] || {}), ...(data[`${target.type}s`] || {}) };
    } catch {
      /* the tooltip keeps the id */
    }
  }

  function show(link) {
    const href = link.getAttribute("href") || "";
    tip.textContent = describeLink(href, ctx.refs, ctx.editor.state.doc);
    const rect = link.getBoundingClientRect();
    tip.hidden = false;
    tip.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - tip.offsetWidth - 8))}px`;
    tip.style.top = `${rect.bottom + 6}px`;
    fetchMissing(href).then(() => {
      if (!tip.hidden) tip.textContent = describeLink(href, ctx.refs, ctx.editor.state.doc);
    });
  }

  surface.addEventListener("mouseover", (event) => {
    const link = event.target.closest("a[href]");
    if (link && surface.contains(link)) show(link);
  });
  surface.addEventListener("mouseout", (event) => {
    if (event.target.closest("a[href]")) tip.hidden = true;
  });
  surface.addEventListener("keyup", () => {
    // Keyboard users: describe the link the cursor is in.
    const node = window.getSelection()?.anchorNode;
    const link = node && (node.nodeType === 1 ? node : node.parentElement)?.closest("a[href]");
    if (link && surface.contains(link)) show(link);
    else tip.hidden = true;
  });
  surface.addEventListener("focusout", () => {
    tip.hidden = true;
  });
}
