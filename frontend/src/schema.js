// The editor's extensions, shared by the browser bundle and the round-trip tests.

import { Extension } from "@tiptap/core";
import { TableKit } from "@tiptap/extension-table";
import { Placeholder } from "@tiptap/extensions";
import { Markdown } from "@tiptap/markdown";
import StarterKit from "@tiptap/starter-kit";

import { AnchoredHeading, Embed, Faq, RawInline, Verify, WagtailImage } from "./nodes.js";

// Links the dialect allows (ADR 0007): web, mail, phone, in-page anchors and Wagtail references.
export function isAllowedHref(href) {
  const value = String(href || "").trim();
  if (value.startsWith("#")) return /^#[A-Za-z0-9][A-Za-z0-9_-]*$/.test(value);
  if (value.startsWith("wagtail://")) return /^wagtail:\/\/(page|document)\?id=\d+$/.test(value);
  return /^(https?:\/\/|mailto:|tel:)\S+$/i.test(value);
}

// @tiptap/markdown writes every &, < and > in text as &amp; &lt; &gt;. The stored Markdown is read by
// models and people, so only encode where Markdown would misread the character: & that would start an
// entity, < that would start a tag, > that would start a blockquote. Markdown escapes stay as they are.
export function encodeText(text, atStart) {
  const encoded = text.replace(/&(?=#?[A-Za-z0-9]+;)/g, "&amp;").replace(/<(?=[A-Za-z/!?])/g, "&lt;");
  return (atStart ? encoded.replace(/^>/, "&gt;") : encoded).replace(/([\\`*_[\]~])/g, "\\$1");
}

export const PlainTextEncoding = Extension.create({
  name: "plainTextEncoding",
  priority: 50, // after Markdown (100) has created its manager in onBeforeCreate; "create" fires too late
  onBeforeCreate() {
    const manager = this.editor.markdown;
    if (!manager || typeof manager.encodeTextForMarkdown !== "function") return;
    const original = manager.encodeTextForMarkdown.bind(manager);
    manager.encodeTextForMarkdown = (text, node, parentNode) => {
      // The original leaves text in code untouched; that's how we tell code apart.
      if (original("&", node, parentNode) === "&") return text;
      return encodeText(text, parentNode?.content?.[0] === node);
    };
  },
});

export function buildExtensions({ resolveImage = () => undefined, placeholder = "" } = {}) {
  return [
    StarterKit.configure({
      heading: false,
      link: {
        openOnClick: false,
        autolink: true,
        // isAllowedUri decides; registering protocols with linkify only warns on every new editor.
        isAllowedUri: (url) => isAllowedHref(url),
      },
    }),
    AnchoredHeading.configure({ levels: [1, 2, 3, 4, 5, 6] }),
    TableKit.configure({ table: { resizable: false } }),
    WagtailImage.configure({ resolve: resolveImage }),
    Embed,
    Faq,
    Verify,
    RawInline,
    Placeholder.configure({ placeholder }),
    Markdown,
    PlainTextEncoding,
  ];
}
