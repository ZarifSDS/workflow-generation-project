// The keyboard-shortcut list (toolbar "?" button, or Ctrl+/ in the text).

import { el, formDialog } from "./ui.js";

const MOD = /Mac|iPhone|iPad/.test(navigator.platform || "") ? "⌘" : "Ctrl";

export const SHORTCUTS = [
  ["Formatting", [
    [`${MOD}+B`, "Bold"],
    [`${MOD}+I`, "Italic"],
    [`${MOD}+U`, "Underline"],
    [`${MOD}+Shift+S`, "Strikethrough"],
    [`${MOD}+K`, "Add or edit a link"],
  ]],
  ["Blocks", [
    ["/", "Insert menu (at the start of an empty line)"],
    [`${MOD}+Alt+2 to 4`, "Heading 2 to 4"],
    [`${MOD}+Alt+0`, "Paragraph"],
    [`${MOD}+Shift+8`, "Bulleted list"],
    [`${MOD}+Shift+7`, "Numbered list"],
    [`${MOD}+Shift+B`, "Quote"],
    ["Tab / Shift+Tab", "Indent or outdent a list item; next or previous table cell"],
  ]],
  ["Editing", [
    [`${MOD}+Z`, "Undo"],
    [`${MOD}+Shift+Z`, "Redo"],
    ["Shift+Enter", "Line break within a paragraph"],
    ["Double-click an image", "Alt text and caption"],
    [`${MOD}+/`, "This list"],
  ]],
];

export function openShortcuts() {
  const sections = SHORTCUTS.map(([title, rows]) =>
    el("section", { class: "se-keys" }, [
      el("h3", { class: "se-keys__title", text: title }),
      el(
        "dl",
        { class: "se-keys__list" },
        rows.flatMap(([keys, what]) => [
          el("dt", {}, keys.split(/(\+|\s\/\s|\sto\s)/).map((part) => (/^(\+|\s\/\s|\sto\s)$/.test(part) ? part : el("kbd", { text: part })))),
          el("dd", { text: what }),
        ]),
      ),
    ]),
  );
  const dialog = formDialog("Keyboard shortcuts", sections, { submitLabel: "Close" });
  dialog.form.querySelector('button[value="cancel"]')?.remove();
}
