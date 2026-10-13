// Phase 5 helpers: link parsing, heading targets, slash menu filtering, upload checks.

import { Editor } from "@tiptap/core";
import { afterEach, describe, expect, test } from "vitest";

import { applyLink, headingTargets, parseHref } from "../src/links.js";
import { buildExtensions } from "../src/schema.js";
import { filterItems, slashItems } from "../src/slash.js";
import { checkImageFile } from "../src/wagtail.js";

const editors = [];
const load = (markdown) => {
  const editor = new Editor({ extensions: buildExtensions(), content: markdown, contentType: "markdown" });
  editors.push(editor);
  return editor;
};
afterEach(() => {
  while (editors.length) editors.pop().destroy();
});

describe("parseHref", () => {
  test.each([
    ["wagtail://page?id=12", { type: "page", id: "12" }],
    ["wagtail://document?id=7", { type: "document", id: "7" }],
    ["#what-counts", { type: "anchor", anchor: "what-counts" }],
    ["mailto:a@example.com", { type: "email", address: "a@example.com" }],
    ["tel:+441234", { type: "phone", number: "+441234" }],
    ["https://osha.gov", { type: "url", url: "https://osha.gov" }],
    ["", { type: "url", url: "" }],
  ])("%s", (href, expected) => {
    expect(parseHref(href)).toEqual(expected);
  });
});

test("heading targets use the server's ids: h2-h4 only, explicit anchors, numbered repeats", () => {
  const editor = load("# Title\n\n## FAQ\n\n### Who {#who}\n\n## FAQ\n\n##### Deep");
  expect(headingTargets(editor.state.doc)).toEqual([
    { text: "FAQ", anchor: null, id: "faq" },
    { text: "Who", anchor: "who", id: "who" },
    { text: "FAQ", anchor: null, id: "faq-2" },
  ]);
});

test("links to pages and documents are wagtail:// references in the Markdown", () => {
  const editor = load("See it.");
  editor.commands.setTextSelection({ from: 5, to: 7 });
  applyLink(editor, "wagtail://page?id=3", "SDS page");
  editor.commands.setTextSelection(editor.state.doc.content.size - 1);
  applyLink(editor, "wagtail://document?id=7", "the form");
  expect(editor.getMarkdown()).toBe("See [it](wagtail://page?id=3).[the form](wagtail://document?id=7)");
});

describe("slash menu", () => {
  const items = slashItems({ openImage() {}, openEmbed() {} });

  test("filters by title and keywords", () => {
    expect(filterItems(items, "").length).toBe(items.length);
    expect(filterItems(items, "youtube").map((i) => i.title)).toEqual(["Video"]);
    expect(filterItems(items, "h3").map((i) => i.title)).toEqual(["Heading 3"]);
    expect(filterItems(items, "zzz")).toEqual([]);
  });

  test("commands replace the typed /query", () => {
    const editor = load("/head");
    const heading = items.find((i) => i.title === "Heading 2");
    heading.command({ editor, range: { from: 1, to: 6 } });
    expect(editor.getJSON().content[0]).toMatchObject({ type: "heading", attrs: { level: 2 } });
  });
});

describe("upload checks", () => {
  const api = { uploadTypes: ["jpg", "png", "webp", "svg"], uploadMax: 10 * 1024 * 1024 };
  const file = (name, size) => ({ name, size });

  test("accepts allowed types under the limit", () => {
    expect(checkImageFile(file("a.WEBP", 1000), api)).toBe("");
    expect(checkImageFile(file("diagram.svg", 1000), api)).toBe("");
  });

  test("explains the type and size limits", () => {
    expect(checkImageFile(file("a.bmp", 1000), api)).toContain("JPG, PNG, WEBP, SVG");
    expect(checkImageFile(file("big.png", 11 * 1024 * 1024), api)).toContain("up to 10 MB");
  });
});
