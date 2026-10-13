// Rich-text editing of step output in the run workspace (M9 phases 4-5, docs/ui-ux-plan.md).
//
// Progressive enhancement: the page works without this bundle (a Markdown textarea in a disclosure).
// Markdown in the textarea stays the source of truth. The visual editor writes back to it only when you
// changed something visually, because Tiptap re-formats Markdown it reads (list markers, escapes).

import "./editor.css";

import { Editor } from "@tiptap/core";
import BubbleMenu from "@tiptap/extension-bubble-menu";
import FileHandler from "@tiptap/extension-file-handler";

import { openLinkDialog } from "./links.js";
import { editImageDetails, openEmbedDialog, openImageDialog, uploadFiles } from "./media.js";
import { buildExtensions } from "./schema.js";
import { SlashCommands } from "./slash.js";
import { el } from "./ui.js";
import { createApi } from "./wagtail.js";

const AUTOSAVE_MS = 800;
const PREFIX = "studio:draft:";

const storage = {
  get(key) {
    try {
      return JSON.parse(window.localStorage.getItem(key) || "null");
    } catch {
      return null;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* private mode or full: autosave is a convenience */
    }
  },
  remove(key) {
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },
  keys(prefix) {
    try {
      return Object.keys(window.localStorage).filter((key) => key.startsWith(prefix));
    } catch {
      return [];
    }
  },
};

const same = (a, b) => a.replace(/\r\n/g, "\n").trim() === b.replace(/\r\n/g, "\n").trim();
const formatTime = (iso) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function readRefs(id) {
  const node = id && document.getElementById(id);
  try {
    return node ? JSON.parse(node.textContent) : {};
  } catch {
    return {};
  }
}

// ---- toolbar ----

function toolbarButton(label, icon, run, { isActive, isEnabled, shortcut } = {}) {
  const button = el("button", {
    type: "button",
    class: "se-btn",
    title: shortcut ? `${label} (${shortcut})` : label,
    "aria-label": label,
    onclick: run,
  });
  button.innerHTML = icon;
  return { button, isActive, isEnabled };
}

const ICONS = {
  bold: "<b>B</b>",
  italic: "<i>I</i>",
  underline: "<u>U</u>",
  strike: "<s>S</s>",
  link: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>',
  bullet: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="7" r="1.2"/><circle cx="5" cy="12" r="1.2"/><circle cx="5" cy="17" r="1.2"/><path d="M9 7h11M9 12h11M9 17h11"/></svg>',
  ordered: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 7h10M10 12h10M10 17h10M4 5h1.5v4M4 9h3M4 14.5c0-1 2.5-1 2.5 0S4 16 4 17.5h3"/></svg>',
  quote: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6v12M10 9h9M10 13h9M10 17h6"/></svg>',
  table: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1.5"/><path d="M3.5 10h17M3.5 14.5h17M10 5v14"/></svg>',
  faq: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.2 9a2.8 2.8 0 1 1 3.8 2.6c-.6.3-1 .8-1 1.5v.4M12 17h.01"/><rect x="3.5" y="3.5" width="17" height="17" rx="2"/></svg>',
  rule: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12h16"/></svg>',
  image: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5" width="17" height="14" rx="1.5"/><circle cx="9" cy="10" r="1.5"/><path d="m4 17 5-4 4 3 3-2 4 3"/></svg>',
  video: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="6" width="12" height="12" rx="1.5"/><path d="m15.5 10.5 5-3v9l-5-3"/></svg>',
  undo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3"/></svg>',
  redo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 14 5-5-5-5M20 9H10a6 6 0 0 0 0 12h3"/></svg>',
};

function buildToolbar(ctx) {
  const { editor } = ctx;
  const block = el("select", { class: "se-block", "aria-label": "Text style" }, [
    el("option", { value: "p", text: "Paragraph" }),
    el("option", { value: "2", text: "Heading 2" }),
    el("option", { value: "3", text: "Heading 3" }),
    el("option", { value: "4", text: "Heading 4" }),
  ]);
  block.addEventListener("change", () => {
    const chain = editor.chain().focus();
    if (block.value === "p") chain.setParagraph().run();
    else chain.setHeading({ level: Number(block.value) }).run();
  });

  const can = () => editor.can().chain().focus();
  const groups = [
    [
      toolbarButton("Bold", ICONS.bold, () => editor.chain().focus().toggleBold().run(), { isActive: () => editor.isActive("bold"), shortcut: "Ctrl+B" }),
      toolbarButton("Italic", ICONS.italic, () => editor.chain().focus().toggleItalic().run(), { isActive: () => editor.isActive("italic"), shortcut: "Ctrl+I" }),
      toolbarButton("Underline", ICONS.underline, () => editor.chain().focus().toggleUnderline().run(), { isActive: () => editor.isActive("underline"), shortcut: "Ctrl+U" }),
      toolbarButton("Strikethrough", ICONS.strike, () => editor.chain().focus().toggleStrike().run(), { isActive: () => editor.isActive("strike"), shortcut: "Ctrl+Shift+S" }),
      toolbarButton("Link", ICONS.link, () => openLinkDialog(ctx), { isActive: () => editor.isActive("link"), shortcut: "Ctrl+K" }),
    ],
    [
      toolbarButton("Bulleted list", ICONS.bullet, () => editor.chain().focus().toggleBulletList().run(), { isActive: () => editor.isActive("bulletList") }),
      toolbarButton("Numbered list", ICONS.ordered, () => editor.chain().focus().toggleOrderedList().run(), { isActive: () => editor.isActive("orderedList") }),
      toolbarButton("Quote", ICONS.quote, () => editor.chain().focus().toggleBlockquote().run(), { isActive: () => editor.isActive("blockquote") }),
    ],
    [
      toolbarButton("Insert table", ICONS.table, () => editor.chain().focus().insertTable({ rows: 3, cols: 2, withHeaderRow: true }).run(), { isEnabled: () => can().insertTable({ rows: 3, cols: 2 }).run() }),
      toolbarButton("Insert FAQ", ICONS.faq, () => editor.chain().focus().insertFaq().run(), { isEnabled: () => !editor.isActive("faq") }),
      toolbarButton("Divider", ICONS.rule, () => editor.chain().focus().setHorizontalRule().run()),
      toolbarButton("Image", ICONS.image, () => openImageDialog(ctx), { isActive: () => editor.isActive("wagtailImage") }),
      toolbarButton("Video", ICONS.video, () => openEmbedDialog(ctx)),
    ],
    [
      toolbarButton("Undo", ICONS.undo, () => editor.chain().focus().undo().run(), { isEnabled: () => can().undo().run(), shortcut: "Ctrl+Z" }),
      toolbarButton("Redo", ICONS.redo, () => editor.chain().focus().redo().run(), { isEnabled: () => can().redo().run(), shortcut: "Ctrl+Shift+Z" }),
    ],
  ];

  const tableBar = el("div", { class: "se-tablebar", role: "group", "aria-label": "Table", hidden: true },
    [
      ["Add row", (c) => c.addRowAfter()],
      ["Add column", (c) => c.addColumnAfter()],
      ["Delete row", (c) => c.deleteRow()],
      ["Delete column", (c) => c.deleteColumn()],
      ["Delete table", (c) => c.deleteTable()],
    ].map(([label, command]) =>
      el("button", { type: "button", class: "se-chip", text: label, onclick: () => command(editor.chain().focus()).run() }),
    ),
  );

  const bar = el("div", { class: "se-toolbar", role: "toolbar", "aria-label": "Formatting" }, [
    block,
    ...groups.map((group) => el("div", { class: "se-group", role: "group" }, group.map((item) => item.button))),
  ]);

  // Roving focus: arrow keys move between toolbar controls.
  bar.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    const items = [...bar.querySelectorAll("button:not([disabled]), select")];
    const index = items.indexOf(document.activeElement);
    if (index < 0) return;
    event.preventDefault();
    items[(index + (event.key === "ArrowRight" ? 1 : items.length - 1)) % items.length].focus();
  });

  function refresh() {
    for (const item of groups.flat()) {
      if (item.isActive) item.button.setAttribute("aria-pressed", String(Boolean(item.isActive())));
      if (item.isEnabled) item.button.disabled = !item.isEnabled();
    }
    const heading = [2, 3, 4].find((level) => editor.isActive("heading", { level }));
    block.value = heading ? String(heading) : "p";
    tableBar.hidden = !editor.isActive("table");
  }

  return { bar, tableBar, refresh };
}

// Built before the editor (BubbleMenu needs its element up front), so it reaches the editor lazily.
function buildBubble(getCtx) {
  const getEditor = () => getCtx().editor;
  const items = [
    ["Bold", ICONS.bold, () => getEditor().chain().focus().toggleBold().run(), "bold"],
    ["Italic", ICONS.italic, () => getEditor().chain().focus().toggleItalic().run(), "italic"],
    ["Underline", ICONS.underline, () => getEditor().chain().focus().toggleUnderline().run(), "underline"],
    ["Link", ICONS.link, () => openLinkDialog(getCtx()), "link"],
  ].map(([label, icon, run, mark]) => ({ ...toolbarButton(label, icon, run), mark }));
  const menu = el("div", { class: "se-bubble", role: "toolbar", "aria-label": "Selected text" }, items.map((i) => i.button));
  const refresh = () =>
    items.forEach((i) => i.button.setAttribute("aria-pressed", String(getEditor().isActive(i.mark))));
  return { menu, refresh };
}

// ---- the editing session ----

function mount(form) {
  const root = form.closest("[data-editor-root]") || document;
  const textarea = form.querySelector("textarea[name=content]");
  const output = root.querySelector("[data-editor-output]");
  const details = form.closest("details");
  const openButton = root.querySelector("[data-editor-open]");
  if (!textarea) return;

  const original = textarea.value;
  const key = form.dataset.autosaveKey;
  const refs = readRefs(form.dataset.refsId);
  let mode = "visual";
  let visualDirty = false;
  let loaded = null; // the Markdown the visual editor last loaded
  let submitting = false;
  let timer = null;

  // Layout: toolbar, surface, the textarea (Markdown mode), status.
  const surface = el("div", { class: "se-surface" });
  const modeVisual = el("button", { type: "button", class: "se-mode", "aria-pressed": "true", text: "Visual" });
  const modeMarkdown = el("button", { type: "button", class: "se-mode", "aria-pressed": "false", text: "Markdown" });
  const status = el("p", { class: "se-status", "aria-live": "polite" });
  // Results of uploads, choosers and embeds; kept apart from the autosave line so neither hides the other.
  const notice = el("p", { class: "se-status se-notice", role: "status" });

  // Shared with the dialogs: the editor, the server API, reference data and a status line.
  const ctx = {
    editor: null,
    api: createApi(form),
    refs,
    notify: (message) => {
      notice.textContent = message;
    },
    openImage: () => openImageDialog(ctx),
    openEmbed: () => openEmbedDialog(ctx),
  };
  const bubble = buildBubble(() => ctx);
  const editor = new Editor({
    element: surface,
    extensions: [
      ...buildExtensions({
        // undefined: no reference data on the page; null: the image no longer exists.
        resolveImage: (id) => (refs.images ? (refs.images[id] ?? null) : undefined),
        placeholder: "Write here…",
      }),
      BubbleMenu.configure({
        element: bubble.menu,
        shouldShow: ({ editor: e, state }) =>
          !state.selection.empty && !state.selection.node && (e.isActive("paragraph") || e.isActive("heading")),
      }),
      // Images dropped or pasted into the text are uploaded to the library (with alt text).
      FileHandler.configure({
        allowedMimeTypes: ctx.api.uploadTypes.map((t) => (t === "svg" ? "image/svg+xml" : `image/${t === "jpg" ? "jpeg" : t}`)),
        onDrop: (_editor, files, pos) => uploadFiles(ctx, files, pos),
        onPaste: (_editor, files) => uploadFiles(ctx, files),
      }),
      SlashCommands.configure({ ctx }),
    ],
    editorProps: { attributes: { class: "se-prose s-output", "aria-label": "Edit the text", role: "textbox", "aria-multiline": "true" } },
    onUpdate: () => {
      if (loaded === null) return;
      visualDirty = true;
      scheduleAutosave();
      refreshAll();
    },
    onSelectionUpdate: () => refreshAll(),
  });

  ctx.editor = editor;
  form.studioEditor = editor; // for debugging in the browser console
  const toolbar = buildToolbar(ctx);
  function refreshAll() {
    toolbar.refresh();
    bubble.refresh();
  }

  const shell = el("div", { class: "se", "data-mode": "visual" }, [
    el("div", { class: "se-head" }, [
      toolbar.bar,
      el("div", { class: "se-modes", role: "group", "aria-label": "Editing mode" }, [modeVisual, modeMarkdown]),
    ]),
    toolbar.tableBar,
    surface,
  ]);
  textarea.before(shell);
  const header = document.querySelector(".w-slim-header");
  const measureHeader = () => shell.style.setProperty("--se-sticky-top", `${header ? header.offsetHeight : 0}px`);
  measureHeader();
  window.addEventListener("resize", measureHeader);
  textarea.classList.add("se-markdown");
  textarea.after(notice, status);
  bubble.menu.hidden = false;

  // Keyboard: Ctrl+K for links, double-click an image for its details.
  surface.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      openLinkDialog(ctx);
    }
  });
  surface.addEventListener("dblclick", (event) => {
    if (event.target.closest(".se-figure")) editImageDetails(ctx);
  });

  // ---- Markdown <-> visual ----

  // One trailing newline and no runs of blank lines (tables add one), outside fenced code.
  const toMarkdown = () => {
    const parts = editor.getMarkdown().split(/(^```[\s\S]*?^```)/m);
    const tidy = parts.map((part, i) => (i % 2 ? part : part.replace(/\n{3,}/g, "\n\n"))).join("");
    return `${tidy.replace(/\s+$/, "")}\n`;
  };

  function syncToTextarea() {
    if (mode === "visual" && visualDirty) {
      textarea.value = toMarkdown();
      loaded = textarea.value;
      visualDirty = false;
    }
  }

  function loadVisual(markdown) {
    if (loaded === markdown) return;
    loaded = null; // suppress onUpdate while loading
    editor.commands.setContent(markdown, { contentType: "markdown", emitUpdate: false });
    loaded = markdown;
    visualDirty = false;
  }

  function setMode(next) {
    if (next === mode) return;
    if (next === "markdown") {
      syncToTextarea();
      mode = "markdown";
      textarea.hidden = false;
      surface.hidden = true;
      toolbar.bar.inert = true;
      textarea.focus();
    } else {
      loadVisual(textarea.value);
      mode = "visual";
      textarea.hidden = true;
      surface.hidden = false;
      toolbar.bar.inert = false;
      editor.commands.focus();
    }
    shell.dataset.mode = mode;
    modeVisual.setAttribute("aria-pressed", String(mode === "visual"));
    modeMarkdown.setAttribute("aria-pressed", String(mode === "markdown"));
    refreshAll();
  }
  modeVisual.addEventListener("click", () => setMode("visual"));
  modeMarkdown.addEventListener("click", () => setMode("markdown"));
  textarea.addEventListener("input", scheduleAutosave);

  const current = () => (mode === "visual" && visualDirty ? toMarkdown() : textarea.value);
  const isDirty = () => !same(current(), original);

  // ---- autosave in this browser ----

  function scheduleAutosave() {
    if (!key) return;
    clearTimeout(timer);
    timer = setTimeout(() => {
      const content = current();
      if (same(content, original)) {
        storage.remove(key);
        status.textContent = "";
        return;
      }
      const savedAt = new Date().toISOString();
      storage.set(key, { content, savedAt });
      status.textContent = `Draft kept in this browser at ${formatTime(savedAt)}. Not saved to the studio yet.`;
    }, AUTOSAVE_MS);
  }

  // ---- open / cancel / submit ----

  function open(content) {
    if (details) {
      details.open = true;
      details.classList.add("is-editing");
    }
    if (root !== document) root.classList.add("is-editing");
    if (content !== undefined) textarea.value = content;
    if (output) output.hidden = true;
    if (openButton) openButton.hidden = true;
    textarea.hidden = true;
    surface.hidden = false;
    loadVisual(textarea.value);
    if (content !== undefined && !same(content, original)) scheduleAutosave();
    refreshAll();
    // Focus without ProseMirror's own scrolling, then bring the toolbar to the top of the page
    // (after Tiptap's deferred focus).
    editor.commands.focus("start", { scrollIntoView: false });
    setTimeout(() => shell.scrollIntoView({ block: "start" }), 50);
  }

  function close() {
    if (isDirty() && !window.confirm("Discard your changes?")) return;
    clearTimeout(timer);
    if (key) storage.remove(key);
    textarea.value = original;
    loadVisual(original);
    setMode("visual");
    status.textContent = "";
    if (output) output.hidden = false;
    if (openButton) {
      openButton.hidden = false;
      openButton.focus();
    }
    if (details) {
      details.open = false;
      details.classList.remove("is-editing");
    }
    if (root !== document) root.classList.remove("is-editing");
  }

  const cancel = el("button", { type: "button", class: "button button-secondary", text: "Cancel", onclick: close });
  form.querySelector("[data-editor-actions]")?.append(cancel);

  form.addEventListener("submit", () => {
    syncToTextarea();
    submitting = true;
    // Keep exactly what is sent: if the server saves it, the next page sees a match and drops it;
    // if the save is refused (a newer version), the latest text is what's offered back.
    clearTimeout(timer);
    if (key && !same(textarea.value, original)) {
      storage.set(key, { content: textarea.value, savedAt: new Date().toISOString() });
    }
  });
  window.addEventListener("beforeunload", (event) => {
    if (submitting || details?.open === false || !isDirty()) return;
    event.preventDefault();
    event.returnValue = "";
  });

  if (openButton) {
    openButton.hidden = false;
    openButton.addEventListener("click", () => open());
  }
  // Without the bundle the disclosure is the way in; with it, the Edit button is.
  details?.classList.add("is-enhanced");
  textarea.hidden = true;
  loadVisual(original);
  refreshAll();

  offerRestore(root, form, original, open);
}

// A draft kept in this browser for this step: offer it back, unless it was saved meanwhile.
function offerRestore(root, form, original, open) {
  const key = form.dataset.autosaveKey;
  if (!key) return;
  const base = key.slice(key.lastIndexOf(":") + 1);
  const stepPrefix = key.slice(0, key.lastIndexOf(":") + 1);
  const drafts = storage
    .keys(stepPrefix)
    .map((k) => ({ key: k, base: k.slice(stepPrefix.length), ...(storage.get(k) || {}) }))
    .filter((draft) => {
      if (!draft.content || same(draft.content, original)) {
        storage.remove(draft.key); // saved already, or nothing changed
        return false;
      }
      return true;
    })
    .sort((a, b) => String(b.savedAt).localeCompare(String(a.savedAt)));
  const draft = drafts[0];
  if (!draft) return;
  const older = draft.base !== base;
  const banner = el("div", { class: "s-callout s-callout--info se-restore", role: "status" }, [
    el("p", {
      text: older
        ? `You have an edit kept in this browser (${formatTime(draft.savedAt)}) that started from version ${draft.base}. Version ${base} has been saved since; restoring puts your text over it, so compare before saving.`
        : `You have an edit kept in this browser from ${formatTime(draft.savedAt)} that isn't saved yet.`,
    }),
    el("div", { class: "se-restore__actions" }, [
      el("button", {
        type: "button",
        class: "button button-small",
        text: "Restore my edit",
        onclick: () => {
          drafts.forEach((d) => d.key !== form.dataset.autosaveKey && storage.remove(d.key));
          banner.remove();
          open(draft.content);
        },
      }),
      el("button", {
        type: "button",
        class: "button button-small button-secondary",
        text: "Discard it",
        onclick: () => {
          drafts.forEach((d) => storage.remove(d.key));
          banner.remove();
        },
      }),
    ]),
  ]);
  (root.querySelector("[data-editor-output]") || form).before(banner);
}

// Drafts for steps that are no longer editable (approved, rejected) are cleared.
function clearStale() {
  document.querySelectorAll("[data-editor-clear]").forEach((node) => {
    storage.keys(`${PREFIX}${node.dataset.editorClear}:`).forEach((key) => storage.remove(key));
  });
}

function init() {
  clearStale();
  document.querySelectorAll("form[data-editor-form]").forEach(mount);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
