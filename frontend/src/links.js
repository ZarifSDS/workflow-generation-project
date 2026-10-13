// The link dialog: web address, page or document from Wagtail (chooser modal), a heading in this text,
// email or phone. Internal links are stored as wagtail:// references (ADR 0007).

import { isAllowedHref } from "./schema.js";
import { uniqueIds } from "./slug.js";
import { el, formDialog, selectField, textField } from "./ui.js";

const TYPES = [
  ["url", "Web address"],
  ["page", "Page on this site"],
  ["document", "Document"],
  ["anchor", "Heading in this text"],
  ["email", "Email address"],
  ["phone", "Phone number"],
];

export function parseHref(href) {
  const value = href || "";
  const ref = /^wagtail:\/\/(page|document)\?id=(\d+)$/.exec(value);
  if (ref) return { type: ref[1], id: ref[2] };
  if (value.startsWith("#")) return { type: "anchor", anchor: value.slice(1) };
  if (value.startsWith("mailto:")) return { type: "email", address: value.slice(7) };
  if (value.startsWith("tel:")) return { type: "phone", number: value.slice(4) };
  return { type: "url", url: value };
}

/** The headings links can point to (h2–h4, as the server gives them ids), with their ids. */
export function headingTargets(doc) {
  const headings = [];
  doc.descendants((node) => {
    if (node.type.name === "heading" && node.attrs.level >= 2 && node.attrs.level <= 4) {
      headings.push({ text: node.textContent, anchor: node.attrs.anchor });
    }
  });
  const ids = uniqueIds(headings);
  return headings.map((heading, index) => ({ ...heading, id: ids[index] }));
}

export function applyLink(editor, href, text) {
  const chain = editor.chain().focus();
  if (editor.state.selection.empty && !editor.isActive("link")) {
    chain.insertContent({ type: "text", text: text || href, marks: [{ type: "link", attrs: { href } }] }).run();
  } else {
    chain.extendMarkRange("link").setLink({ href }).run();
  }
}

export function openLinkDialog(ctx) {
  const { editor, api, refs } = ctx;
  const current = editor.getAttributes("link").href || "";
  const parsed = parseHref(current);
  const types = TYPES.filter(([type]) => !["page", "document"].includes(type) || api.canChoose(type));
  const type = selectField("Link to", types, parsed.type);

  const url = textField("Web address", { value: parsed.url || "", placeholder: "https://", type: "url" });
  const email = textField("Email address", { value: parsed.address || "", type: "email" });
  const phone = textField("Phone number", { value: parsed.number || "", hint: "With the country code, e.g. +44 1234 567890" });
  const headings = headingTargets(editor.state.doc);
  const anchor = selectField(
    "Heading",
    headings.length ? headings.map((h) => [h.id, h.text]) : [["", "This text has no headings yet"]],
    parsed.anchor,
  );
  const choosers = {};
  for (const kind of ["page", "document"]) {
    const chosenTitle =
      parsed.type === kind ? (refs[`${kind}s`] || {})[parsed.id]?.title || `${kind === "page" ? "Page" : "Document"} ${parsed.id}` : "";
    const button = el("button", {
      type: "button",
      class: "button button-small button-secondary",
      text: chosenTitle ? `Change ${kind}…` : `Choose a ${kind}…`,
    });
    choosers[kind] = {
      row: el("div", { class: "se-field" }, [
        chosenTitle ? el("p", { class: "se-field__chosen", text: `Linked to: ${chosenTitle}` }) : null,
        button,
        el("p", { class: "se-field__hint", text: `Opens Wagtail's ${kind} chooser; the link is added when you pick one.` }),
      ]),
      button,
    };
  }
  const panels = { url, email, phone, anchor, page: choosers.page, document: choosers.document };

  const removeButton = current
    ? el("button", { type: "submit", class: "button button-small button-secondary", text: "Remove link", value: "remove" })
    : null;

  const sync = () => {
    for (const [key, panel] of Object.entries(panels)) if (panel) panel.row.hidden = key !== type.input.value;
    dialog.apply.hidden = ["page", "document"].includes(type.input.value);
  };

  const dialog = formDialog(current ? "Edit link" : "Add link", [type, ...Object.values(panels).filter(Boolean)], {
    extraButtons: removeButton ? [removeButton] : [],
    onExtra: (action) => {
      if (action === "remove") editor.chain().focus().extendMarkRange("link").unsetLink().run();
    },
    onApply: (event, d) => {
      const values = {
        url: url.input.value.trim(),
        email: email.input.value.trim() && `mailto:${email.input.value.trim()}`,
        phone: phone.input.value.trim() && `tel:${phone.input.value.replace(/[^\d+]/g, "")}`,
        anchor: anchor.input.value && `#${anchor.input.value}`,
      };
      const href = values[type.input.value];
      if (!href || !isAllowedHref(href)) {
        event.preventDefault();
        d.showError(
          {
            url: "Enter a full web address starting with https://.",
            email: "Enter an email address.",
            phone: "Enter a phone number.",
            anchor: "Pick a heading.",
          }[type.input.value],
        );
        return;
      }
      applyLink(editor, href, type.input.value === "anchor" ? anchor.input.selectedOptions[0]?.text : undefined);
    },
  });

  for (const kind of ["page", "document"]) {
    if (!choosers[kind]) continue;
    choosers[kind].button.addEventListener("click", async () => {
      dialog.close(); // Wagtail's modal can't sit on top of a modal <dialog>
      const chosen = await api.choose(kind).catch((error) => {
        ctx.notify(error.message);
        return null;
      });
      if (!chosen) return;
      refs[`${kind}s`] = { ...(refs[`${kind}s`] || {}), [chosen.id]: { title: chosen.title, url: chosen.url } };
      applyLink(editor, `wagtail://${kind}?id=${chosen.id}`, chosen.title);
      ctx.notify(`Linked to ${chosen.title}.`);
    });
  }
  type.input.addEventListener("change", sync);
  sync();
}
