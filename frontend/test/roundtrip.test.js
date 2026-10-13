// Markdown -> editor -> Markdown over the shared dialect fixtures (tests/fixtures/dialect/, ADR 0007).

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { Editor } from "@tiptap/core";
import { afterEach, describe, expect, test } from "vitest";

import { buildExtensions, isAllowedHref } from "../src/schema.js";
import { slugify, uniqueIds } from "../src/slug.js";

const FIXTURES = join(__dirname, "../../tests/fixtures/dialect");
const editors = [];

function load(markdown) {
  const editor = new Editor({ extensions: buildExtensions(), content: markdown, contentType: "markdown" });
  editors.push(editor);
  return editor;
}

const serialise = (markdown) => load(markdown).getMarkdown();
// Tables are re-padded and blank lines may differ; neither changes what the renderers produce.
const normalise = (markdown) =>
  markdown
    .split("\n")
    .map((line) => {
      if (!line.startsWith("|")) return line;
      if (/^\|[\s:|-]+\|$/.test(line)) return line.replace(/\s+/g, "").replace(/-+/g, "---");
      return line.replace(/ {2,}/g, " ");
    })
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

afterEach(() => {
  while (editors.length) editors.pop().destroy();
});

describe.each(readdirSync(FIXTURES).filter((name) => name.endsWith(".md")))("fixture %s", (name) => {
  const source = readFileSync(join(FIXTURES, name), "utf8").replace(/\r\n/g, "\n");

  test("serialising is idempotent", () => {
    const once = serialise(source);
    expect(serialise(once)).toBe(once);
  });

  test("round trip keeps the text, apart from table padding and blank lines", () => {
    expect(normalise(serialise(source))).toBe(normalise(source));
  });
});

describe("dialect nodes", () => {
  test("image with caption, decorative image and embed", () => {
    const md = [
      '![Engineer at the panel](wagtail://image?id=42 "Every change needs a reviewer.")',
      '![](wagtail://image?id=7&decorative=1 "Plant overview")',
      "![MOC explained](wagtail://media?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc123)",
    ].join("\n\n");
    const editor = load(md);
    const types = editor.getJSON().content.map((node) => node.type);
    expect(types).toEqual(["wagtailImage", "wagtailImage", "embed"]);
    expect(editor.getJSON().content[0].attrs).toMatchObject({
      id: "42",
      alt: "Engineer at the panel",
      caption: "Every change needs a reviewer.",
      decorative: false,
    });
    expect(editor.getJSON().content[1].attrs.decorative).toBe(true);
    expect(editor.getJSON().content[2].attrs.url).toBe("https://www.youtube.com/watch?v=abc123");
    expect(normalise(editor.getMarkdown())).toBe(md);
  });

  test("quotes and brackets in alt text and captions are escaped", () => {
    const editor = load("# T");
    editor.commands.insertContentAt(editor.state.doc.content.size, {
      type: "wagtailImage",
      attrs: { id: "3", alt: "Valve [open]", caption: 'Say "stop"' },
    });
    expect(editor.getMarkdown()).toContain('![Valve \\[open\\]](wagtail://image?id=3 "Say \\"stop\\"")');
    const again = load(editor.getMarkdown());
    expect(again.getJSON().content[1].attrs).toMatchObject({ alt: "Valve [open]", caption: 'Say "stop"' });
  });

  test("[VERIFY] stays unescaped and becomes a chip, also when it was escaped", () => {
    const editor = load("Keep records for 30 years \\[VERIFY\\]. Check [verify] too.");
    const inline = editor.getJSON().content[0].content.filter((node) => node.type === "verify");
    expect(inline).toHaveLength(2);
    expect(editor.getMarkdown()).toBe("Keep records for 30 years [VERIFY]. Check [VERIFY] too.");
  });

  test("heading anchors are attributes and are written back", () => {
    const editor = load("## What counts {#what-counts}\n\n## Plain heading");
    const [first, second] = editor.getJSON().content;
    expect(first.attrs.anchor).toBe("what-counts");
    expect(first.content[0].text).toBe("What counts");
    expect(second.attrs.anchor).toBe(null);
    expect(editor.getMarkdown()).toBe("## What counts {#what-counts}\n\n## Plain heading");
  });

  test("FAQ is a container with questions and answers", () => {
    const md = ":::faq\n### Does a temporary change need MOC?\n\nYes, with an end date.\n:::";
    const editor = load(md);
    const faq = editor.getJSON().content[0];
    expect(faq.type).toBe("faq");
    expect(faq.content.map((node) => node.type)).toEqual(["heading", "paragraph"]);
    expect(editor.getMarkdown()).toBe(md);
  });

  test("underline, strike and internal links survive", () => {
    const md =
      "Some ++temporary bypasses++ and ~~old~~ rules. See [the SDS page](wagtail://page?id=3), " +
      "[the form](wagtail://document?id=7), [above](#what-counts) and [call](tel:+441234567890).";
    expect(serialise(md)).toBe(md);
  });

  test("&, < and > stay plain unless Markdown would misread them", () => {
    const md = "Procedural & organisational changes, 5 < 10 and 10 > 5. Write &amp;copy; and \\<b> literally.";
    const out = serialise(md);
    expect(out).toContain("Procedural & organisational changes, 5 < 10 and 10 > 5.");
    expect(serialise(out)).toBe(out);
    expect(load(out).getText()).toBe(load(md).getText());
  });

  test("code keeps its characters verbatim", () => {
    const md = "Run `a && b <c>` now.\n\n```\nif a < b && c:\n```";
    expect(serialise(md)).toBe(md);
  });

  test("an inline image the dialect doesn't model is kept verbatim", () => {
    const md = "Before ![logo](https://example.com/logo.png) after.";
    expect(serialise(md)).toBe(md);
  });
});

describe("links", () => {
  test.each([
    ["https://www.osha.gov/", true],
    ["mailto:safety@example.com", true],
    ["tel:+441234567890", true],
    ["#what-counts", true],
    ["wagtail://page?id=3", true],
    ["wagtail://document?id=7", true],
    ["javascript:alert(1)", false],
    ["wagtail://image?id=3", false],
    ["#", false],
    ["data:text/html,hi", false],
  ])("%s allowed: %s", (href, allowed) => {
    expect(isAllowedHref(href)).toBe(allowed);
  });
});

describe("slug (mirrors dialect.slugify)", () => {
  test.each([
    ["What counts as a change", "what-counts-as-a-change"],
    ["Café & Crème: 2026 rules!", "cafe-creme-2026-rules"],
    ["   ", "section"],
    ["Über—Straße", "uberstrae"], // same as Python: the dash is dropped, not replaced
  ])("%s -> %s", (text, slug) => {
    expect(slugify(text)).toBe(slug);
  });

  test("repeats get numbered", () => {
    expect(uniqueIds([{ text: "FAQ" }, { text: "FAQ" }, { text: "x", anchor: "faq" }])).toEqual([
      "faq",
      "faq-2",
      "faq-3",
    ]);
  });
});
