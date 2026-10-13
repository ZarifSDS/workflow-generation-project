// Images (library chooser, upload, drag and drop, paste) and video embeds for the editor.
// Uploads go through apps/studio/views/editor_api.py, so Wagtail's type and size limits apply.

import { checkImageFile } from "./wagtail.js";
import { checkField, el, formDialog, textField } from "./ui.js";

const ALT_HINT = "Describe what the image shows, for people who can't see it.";

/** Asks for alt text (required unless decorative) and a caption. Resolves with the values, or null. */
export function askImageDetails({ title, previewUrl, alt = "", decorative = false, caption = "", submitLabel = "Insert" }) {
  return new Promise((resolve) => {
    const altField = textField("Alt text", { value: alt, hint: ALT_HINT });
    const decorativeField = checkField("Decorative image (no alt text)", decorative);
    const captionField = textField("Caption (optional)", { value: caption });
    const preview = previewUrl ? el("img", { class: "se-dialog__preview", src: previewUrl, alt: "" }) : null;
    const sync = () => {
      altField.input.disabled = decorativeField.input.checked;
    };
    decorativeField.input.addEventListener("change", sync);
    sync();
    let result = null;
    formDialog(title, [preview, altField, decorativeField, captionField].filter(Boolean), {
      submitLabel,
      onClose: () => resolve(result),
      onApply: (event, d) => {
        if (!decorativeField.input.checked && !altField.input.value.trim()) {
          event.preventDefault();
          d.showError("Add alt text, or mark the image as decorative.");
          altField.input.focus();
          return;
        }
        result = {
          alt: decorativeField.input.checked ? "" : altField.input.value.trim(),
          decorative: decorativeField.input.checked,
          caption: captionField.input.value.trim(),
        };
      },
    });
  });
}

function insertImage(ctx, image, details, pos) {
  ctx.refs.images = { ...(ctx.refs.images || {}), [image.id]: { url: image.url, width: image.width, height: image.height } };
  const node = { type: "wagtailImage", attrs: { id: String(image.id), ...details } };
  const chain = ctx.editor.chain().focus();
  (pos === undefined ? chain.insertContent(node) : chain.insertContentAt(pos, node)).run();
}

/** Double-click or the image button on a selected image: change its alt text, decorative flag, caption. */
export async function editImageDetails(ctx) {
  const { editor } = ctx;
  const { selection } = editor.state;
  const node = selection.node;
  if (!node || node.type.name !== "wagtailImage") return;
  const pos = selection.from;
  const preview = (ctx.refs.images || {})[node.attrs.id];
  const details = await askImageDetails({
    title: "Image details",
    previewUrl: preview?.url,
    submitLabel: "Apply",
    ...node.attrs,
  });
  if (!details) return;
  editor
    .chain()
    .focus()
    .command(({ tr }) => {
      tr.setNodeMarkup(pos, undefined, { ...node.attrs, ...details });
      return true;
    })
    .run();
}

async function chooseFromLibrary(ctx) {
  const chosen = await ctx.api.choose("image").catch((error) => {
    ctx.notify(error.message);
    return null;
  });
  if (!chosen) return;
  // The library's description is a good first alt text; fetch it with a sized preview.
  const data = await ctx.api.references({ images: [chosen.id] }).catch(() => ({}));
  const image = (data.images || {})[chosen.id] || chosen;
  const details = await askImageDetails({ title: `Insert “${chosen.title}”`, previewUrl: image.url, alt: image.description || "" });
  if (details) insertImage(ctx, image, details);
}

/** Uploads image files (from the picker, a drop or a paste), asking for alt text for each. */
export async function uploadFiles(ctx, files, pos) {
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    const problem = checkImageFile(file, ctx.api);
    if (problem) {
      ctx.notify(problem);
      continue;
    }
    const localUrl = URL.createObjectURL(file);
    const details = await askImageDetails({ title: `Upload ${file.name}`, previewUrl: localUrl, submitLabel: "Upload and insert" });
    URL.revokeObjectURL(localUrl);
    if (!details) continue;
    ctx.notify(`Uploading ${file.name}…`);
    try {
      const image = await ctx.api.upload(file, details);
      insertImage(ctx, image, details, pos);
      ctx.notify(`Uploaded ${file.name} to the image library.`);
    } catch (error) {
      ctx.notify(`${file.name} wasn't uploaded: ${error.message}`);
    }
  }
}

/** The image button: edit the selected image, or insert one from the library or the computer. */
export function openImageDialog(ctx) {
  if (ctx.editor.isActive("wagtailImage")) {
    editImageDetails(ctx);
    return;
  }
  const types = ctx.api.uploadTypes.map((t) => t.toUpperCase()).join(", ");
  const limit = ctx.api.uploadMax ? `up to ${Math.round(ctx.api.uploadMax / 1048576)} MB` : "";
  const file = el("input", { type: "file", accept: ctx.api.uploadTypes.map((t) => `.${t}`).join(","), multiple: true, hidden: true });
  const library = el("button", { type: "button", class: "button button-small button-secondary", text: "Choose from the image library…" });
  const upload = el("button", { type: "button", class: "button button-small button-secondary", text: "Upload from your computer…" });
  const dialog = formDialog(
    "Insert an image",
    [
      el("div", { class: "se-field se-choice" }, [ctx.api.canChoose("image") ? library : null, upload]),
      el("p", { class: "se-field__hint", text: `${types}${limit ? `, ${limit} each` : ""}. You can also drag images into the text or paste them.` }),
      file,
    ],
    { submitLabel: "Close" },
  );
  dialog.apply.hidden = true;
  library.addEventListener("click", () => {
    dialog.close();
    chooseFromLibrary(ctx);
  });
  upload.addEventListener("click", () => file.click());
  file.addEventListener("change", () => {
    const files = [...file.files];
    dialog.close();
    uploadFiles(ctx, files);
  });
}

/** YouTube or Vimeo, checked by the server (it fetches the title). */
export function openEmbedDialog(ctx) {
  const url = textField("Video link", { type: "url", placeholder: "https://www.youtube.com/watch?v=…", hint: "YouTube or Vimeo." });
  const preview = el("p", { class: "se-field__chosen", hidden: true });
  let checked = null;
  formDialog("Embed a video", [url, preview], {
    submitLabel: "Insert",
    onApply: (event, d) => {
      const value = url.input.value.trim();
      if (checked && checked.url === value) {
        ctx.editor.chain().focus().insertContent({ type: "embed", attrs: { url: value, title: checked.title } }).run();
        return;
      }
      event.preventDefault(); // check the link first, then insert on the next press
      d.showError("");
      d.apply.disabled = true;
      ctx.api
        .embed(value)
        .then((info) => {
          checked = info;
          preview.textContent = `${info.provider ? `${info.provider}: ` : ""}${info.title || value}`;
          preview.hidden = false;
          d.apply.textContent = "Insert this video";
        })
        .catch((error) => d.showError(error.message))
        .finally(() => {
          d.apply.disabled = false;
        });
    },
  });
}
