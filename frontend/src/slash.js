// "/" at the start of a line opens a menu of blocks to insert (keyboard: arrows, Enter, Esc).

import { Extension } from "@tiptap/core";
import Suggestion from "@tiptap/suggestion";

import { el } from "./ui.js";

export function slashItems(ctx) {
  const run = (callback) => ({ editor, range }) => callback(editor.chain().focus().deleteRange(range), editor);
  return [
    { title: "Heading 2", keywords: "h2 title section", command: run((c) => c.setNode("heading", { level: 2 }).run()) },
    { title: "Heading 3", keywords: "h3 subsection", command: run((c) => c.setNode("heading", { level: 3 }).run()) },
    { title: "Heading 4", keywords: "h4", command: run((c) => c.setNode("heading", { level: 4 }).run()) },
    { title: "Bulleted list", keywords: "ul unordered", command: run((c) => c.toggleBulletList().run()) },
    { title: "Numbered list", keywords: "ol ordered steps", command: run((c) => c.toggleOrderedList().run()) },
    { title: "Quote", keywords: "blockquote", command: run((c) => c.toggleBlockquote().run()) },
    { title: "Table", keywords: "grid", command: run((c) => c.insertTable({ rows: 3, cols: 2, withHeaderRow: true }).run()) },
    { title: "FAQ", keywords: "questions answers", command: run((c) => c.insertFaq().run()) },
    { title: "Image", keywords: "picture photo upload", command: run((c) => (c.run(), ctx.openImage())) },
    { title: "Video", keywords: "embed youtube vimeo", command: run((c) => (c.run(), ctx.openEmbed())) },
    { title: "Divider", keywords: "hr rule line", command: run((c) => c.setHorizontalRule().run()) },
  ];
}

export function filterItems(items, query) {
  const q = query.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => `${item.title} ${item.keywords}`.toLowerCase().includes(q));
}

function renderMenu() {
  let menu = null;
  let items = [];
  let active = 0;
  let pick = null;

  const draw = () => {
    menu.replaceChildren(
      ...(items.length
        ? items.map((item, index) =>
            el("button", {
              type: "button",
              role: "option",
              class: "se-slash__item",
              "aria-selected": String(index === active),
              text: item.title,
              onmousedown: (event) => {
                event.preventDefault(); // keep the editor's selection
                pick(item);
              },
            }),
          )
        : [el("p", { class: "se-slash__empty", text: "No matching block" })]),
    );
  };
  const place = (rect) => {
    if (!rect) return;
    menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 240))}px`;
    menu.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 280)}px`;
  };

  return {
    onStart(props) {
      menu = el("div", { class: "se-slash", role: "listbox", "aria-label": "Insert a block" });
      document.body.append(menu);
      items = props.items;
      active = 0;
      pick = (item) => props.command(item);
      draw();
      place(props.clientRect?.());
    },
    onUpdate(props) {
      items = props.items;
      active = Math.min(active, Math.max(items.length - 1, 0));
      pick = (item) => props.command(item);
      draw();
      place(props.clientRect?.());
    },
    onKeyDown({ event }) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (items.length) active = (active + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        draw();
        return true;
      }
      if (event.key === "Enter" && items[active]) {
        pick(items[active]);
        return true;
      }
      return event.key === "Escape";
    },
    onExit() {
      menu?.remove();
      menu = null;
    },
  };
}

export const SlashCommands = Extension.create({
  name: "slashCommands",

  addOptions() {
    return { ctx: null };
  },

  addProseMirrorPlugins() {
    const all = slashItems(this.options.ctx);
    return [
      Suggestion({
        editor: this.editor,
        char: "/",
        startOfLine: true,
        allow: ({ state, range }) => state.doc.resolve(range.from).parent.type.name === "paragraph",
        items: ({ query }) => filterItems(all, query),
        command: ({ editor, range, props }) => props.command({ editor, range }),
        render: renderMenu,
      }),
    ];
  },
});
