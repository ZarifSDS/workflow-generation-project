// The studio's Markdown dialect (ADR 0007) as Tiptap nodes: each one parses and writes back exactly
// the syntax apps/content/dialect.py reads.
//
//   ## Heading {#anchor}                       heading with an explicit anchor
//   ![Alt](wagtail://image?id=42 "Caption")    wagtailImage (block); &decorative=1 for decorative
//   ![Title](wagtail://media?url=<encoded>)    embed (block)
//   :::faq ... :::                             faq (container of headings and paragraphs)
//   [VERIFY]                                   verify (inline chip; never escaped)
//   ![alt](other-url)                          rawInline (kept verbatim; the dialect has no inline images)

import { Node, mergeAttributes } from "@tiptap/core";
import Heading from "@tiptap/extension-heading";

import { slugify } from "./slug.js";

const ANCHOR_RE = /\s*\{#([A-Za-z0-9][A-Za-z0-9_-]*)\}\s*$/;
// A block image or embed on its own line: ![alt](wagtail://kind?query "title")
const BLOCK_REF_RE = /^!\[((?:[^\]\\\n]|\\.)*)\]\((wagtail:\/\/(image|media)\?[^\s)]+)(?:[ \t]+"((?:[^"\\\n]|\\.)*)")?\)[ \t]*(?:\n+|$)/;

const unescapeMd = (text) => text.replace(/\\(.)/g, "$1");
const escapeAlt = (text) => text.replace(/[\\\]\[]/g, (c) => `\\${c}`);
const escapeTitle = (text) => text.replace(/[\\"]/g, (c) => `\\${c}`);

function params(url) {
  const query = url.slice(url.indexOf("?") + 1);
  return new URLSearchParams(query);
}

function blockRefTokenizer(name, kind) {
  return {
    name,
    level: "block",
    start: (src) => src.indexOf(`](wagtail://${kind}?`) >= 0 ? src.indexOf("![") : -1,
    tokenize(src) {
      const match = BLOCK_REF_RE.exec(src);
      if (!match || match[3] !== kind) return undefined;
      return {
        type: name,
        raw: match[0],
        alt: unescapeMd(match[1]),
        params: params(match[2]),
        title: match[4] === undefined ? "" : unescapeMd(match[4]),
      };
    },
  };
}

// ---- Headings: levels 1-6 kept (the step outputs start with "# Title"), {#anchor} as an attribute ----

export const AnchoredHeading = Heading.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      anchor: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-anchor"),
        renderHTML: (attrs) => (attrs.anchor ? { "data-anchor": attrs.anchor, id: attrs.anchor } : {}),
      },
    };
  },

  parseMarkdown(token, helpers) {
    let tokens = token.tokens || [];
    let anchor = null;
    const last = tokens[tokens.length - 1];
    if (last && last.type === "text" && ANCHOR_RE.test(last.text || "")) {
      anchor = ANCHOR_RE.exec(last.text)[1];
      const text = last.text.replace(ANCHOR_RE, "");
      tokens = text ? [...tokens.slice(0, -1), { ...last, text, raw: text }] : tokens.slice(0, -1);
    }
    return helpers.createNode("heading", { level: token.depth, anchor }, helpers.parseInline(tokens));
  },

  renderMarkdown(node, helpers) {
    if (!node.content) return "";
    const anchor = node.attrs?.anchor ? ` {#${node.attrs.anchor}}` : "";
    return `${"#".repeat(node.attrs?.level || 1)} ${helpers.renderChildren(node.content)}${anchor}`;
  },
});

// ---- Images from the Wagtail library ----

export const WagtailImage = Node.create({
  name: "wagtailImage",
  group: "block",
  atom: true,
  draggable: true,

  addOptions() {
    // resolve(id) -> {url, width, height, title} or null; filled from the page's reference data.
    return { resolve: () => null };
  },

  addAttributes() {
    return {
      id: { default: null },
      alt: { default: "" },
      caption: { default: "" },
      decorative: { default: false },
    };
  },

  parseHTML() {
    return [
      {
        tag: "figure[data-wagtail-image]",
        getAttrs: (el) => ({
          id: el.getAttribute("data-wagtail-image"),
          alt: el.getAttribute("data-alt") || "",
          caption: el.getAttribute("data-caption") || "",
          decorative: el.hasAttribute("data-decorative"),
        }),
      },
    ];
  },

  renderHTML({ node }) {
    const { id, alt, caption, decorative } = node.attrs;
    return [
      "figure",
      mergeAttributes({
        "data-wagtail-image": id,
        "data-alt": alt,
        "data-caption": caption,
        ...(decorative ? { "data-decorative": "" } : {}),
      }),
    ];
  },

  addNodeView() {
    const resolve = this.options.resolve;
    return ({ node }) => {
      const dom = document.createElement("figure");
      dom.className = "se-figure";
      dom.contentEditable = "false";
      const render = (current) => {
        const { id, alt, caption, decorative } = current.attrs;
        const found = resolve(id);
        dom.replaceChildren();
        if (found && found.url) {
          const img = document.createElement("img");
          img.src = found.url;
          img.alt = decorative ? "" : alt;
          if (found.width) img.width = found.width;
          if (found.height) img.height = found.height;
          dom.append(img);
        } else {
          const missing = document.createElement("div");
          missing.className = "se-figure__missing";
          missing.textContent = found === undefined ? `Image ${id}` : `Image ${id} no longer exists`;
          dom.append(missing);
        }
        const meta = document.createElement("figcaption");
        const altLine = document.createElement("span");
        altLine.className = "se-figure__alt";
        altLine.textContent = decorative ? "Decorative (no alt text)" : alt ? `Alt: ${alt}` : "No alt text";
        if (!decorative && !alt) altLine.classList.add("is-missing");
        meta.append(altLine);
        if (caption) {
          const cap = document.createElement("span");
          cap.textContent = caption;
          meta.append(cap);
        }
        dom.append(meta);
      };
      render(node);
      return {
        dom,
        update(updated) {
          if (updated.type.name !== "wagtailImage") return false;
          render(updated);
          return true;
        },
      };
    };
  },

  markdownTokenizer: blockRefTokenizer("wagtailImage", "image"),

  parseMarkdown(token, helpers) {
    return helpers.createNode("wagtailImage", {
      id: token.params.get("id"),
      alt: token.alt,
      caption: token.title,
      decorative: token.params.get("decorative") === "1",
    });
  },

  renderMarkdown(node) {
    const { id, alt, caption, decorative } = node.attrs;
    const url = `wagtail://image?id=${id}${decorative ? "&decorative=1" : ""}`;
    const title = caption ? ` "${escapeTitle(caption)}"` : "";
    return `![${decorative ? "" : escapeAlt(alt || "")}](${url}${title})`;
  },
});

// ---- Embeds (YouTube, Vimeo) ----

export const Embed = Node.create({
  name: "embed",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return { url: { default: "" }, title: { default: "" } };
  },

  parseHTML() {
    return [
      {
        tag: "figure[data-embed]",
        getAttrs: (el) => ({ url: el.getAttribute("data-embed"), title: el.getAttribute("data-title") || "" }),
      },
    ];
  },

  renderHTML({ node }) {
    const label = node.attrs.title || node.attrs.url;
    return [
      "figure",
      { "data-embed": node.attrs.url, "data-title": node.attrs.title, class: "se-embed", contenteditable: "false" },
      ["span", { class: "se-embed__kind" }, "Embed"],
      ["a", { href: node.attrs.url, target: "_blank", rel: "noopener noreferrer" }, label],
    ];
  },

  markdownTokenizer: blockRefTokenizer("embed", "media"),

  parseMarkdown(token, helpers) {
    return helpers.createNode("embed", { url: token.params.get("url") || "", title: token.alt });
  },

  renderMarkdown(node) {
    return `![${escapeAlt(node.attrs.title || "")}](wagtail://media?url=${encodeURIComponent(node.attrs.url)})`;
  },
});

// ---- FAQ ----

// m flag: the closing ::: is a line of its own. tokenize() only accepts a match at the start.
const FAQ_RE = /^:::faq[ \t]*\n([\s\S]*?)^:::[ \t]*(?:\n+|$)/m;

export const Faq = Node.create({
  name: "faq",
  group: "block",
  content: "(heading | paragraph | bulletList | orderedList)+",
  defining: true,

  parseHTML() {
    return [{ tag: "section[data-block=faq]" }];
  },

  renderHTML() {
    return ["section", { "data-block": "faq", class: "se-faq" }, 0];
  },

  markdownTokenizer: {
    name: "faq",
    level: "block",
    start: (src) => src.indexOf(":::faq"),
    tokenize(src, _tokens, lexer) {
      const match = FAQ_RE.exec(src);
      if (!match || match.index !== 0) return undefined;
      return { type: "faq", raw: match[0], tokens: lexer.blockTokens(match[1]) };
    },
  },

  parseMarkdown(token, helpers) {
    const content = helpers.parseChildren(token.tokens || []);
    return helpers.createNode("faq", {}, content.length ? content : [helpers.createNode("paragraph")]);
  },

  renderMarkdown(node, helpers) {
    return `:::faq\n${helpers.renderChildren(node.content || [], "\n\n")}\n:::`;
  },

  addCommands() {
    return {
      insertFaq:
        () =>
        ({ commands }) =>
          commands.insertContent({
            type: "faq",
            content: [
              { type: "heading", attrs: { level: 3 }, content: [{ type: "text", text: "Question?" }] },
              { type: "paragraph", content: [{ type: "text", text: "Answer." }] },
            ],
          }),
    };
  },
});

// ---- [VERIFY] chips ----

const VERIFY_RE = /^\\?\[VERIFY\\?\]/i;

export const Verify = Node.create({
  name: "verify",
  group: "inline",
  inline: true,
  atom: true,

  parseHTML() {
    return [{ tag: "span[data-verify]" }];
  },

  renderHTML() {
    return ["span", { "data-verify": "", class: "se-verify", title: "Claim to check before publishing" }, "VERIFY"];
  },

  renderText() {
    return "[VERIFY]";
  },

  markdownTokenizer: {
    name: "verify",
    level: "inline",
    start: (src) => src.search(/\\?\[VERIFY/i),
    tokenize(src) {
      const match = VERIFY_RE.exec(src);
      return match ? { type: "verify", raw: match[0] } : undefined;
    },
  },

  parseMarkdown(_token, helpers) {
    return helpers.createNode("verify");
  },

  renderMarkdown() {
    return "[VERIFY]";
  },
});

// ---- Anything inline the dialect doesn't model (e.g. an image inside a sentence): kept verbatim ----

export const RawInline = Node.create({
  name: "rawInline",
  group: "inline",
  inline: true,
  atom: true,
  markdownTokenName: "image",

  addAttributes() {
    return { raw: { default: "" } };
  },

  parseHTML() {
    return [{ tag: "span[data-raw]", getAttrs: (el) => ({ raw: el.getAttribute("data-raw") }) }];
  },

  renderHTML({ node }) {
    return ["span", { "data-raw": node.attrs.raw, class: "se-raw", title: "Kept as written" }, node.attrs.raw];
  },

  renderText({ node }) {
    return node.attrs.raw;
  },

  parseMarkdown(token, helpers) {
    return helpers.createNode("rawInline", { raw: token.raw });
  },

  renderMarkdown(node) {
    return node.attrs.raw;
  },
});

export { slugify };
