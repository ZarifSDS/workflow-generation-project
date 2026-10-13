// Small DOM helpers and native <dialog> forms (focus handling and Esc come from the browser).

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) if (child) node.append(child);
  return node;
}

const uid = () => `se-f-${Math.random().toString(36).slice(2, 9)}`;

/**
 * A modal form. `onApply(event)` runs when the main button is pressed; call `event.preventDefault()`
 * to keep the dialog open (e.g. after `showError`). The dialog removes itself when closed.
 */
export function formDialog(title, fields, { submitLabel = "Apply", extraButtons = [], onApply, onExtra, onClose } = {}) {
  const error = el("p", { class: "se-dialog__error", role: "alert", hidden: true });
  const body = el("div", { class: "se-dialog__fields" }, fields.map((field) => field.row || field));
  const apply = el("button", { type: "submit", class: "button button-small", text: submitLabel, value: "apply" });
  const footer = el("div", { class: "se-dialog__actions" }, [
    apply,
    ...extraButtons,
    el("button", { type: "submit", class: "button button-small button-secondary", text: "Cancel", value: "cancel", formnovalidate: true }),
  ]);
  const form = el("form", { method: "dialog" }, [el("h2", { class: "se-dialog__title", text: title }), body, error, footer]);
  const dialog = el("dialog", { class: "se-dialog", "aria-label": title }, form);
  document.body.append(dialog);
  // Finish once, however the dialog ends (button, Esc, close()). The "close" event alone isn't enough:
  // browsers fire it later, and some embedded views don't fire it at all.
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    dialog.remove();
    if (onClose) onClose();
  };
  const api = {
    dialog,
    form,
    apply,
    showError(message) {
      error.textContent = message;
      error.hidden = !message;
    },
    close() {
      if (dialog.open) dialog.close();
      finish();
    },
  };
  form.addEventListener("submit", (event) => {
    const action = event.submitter?.value;
    if (action === "apply" && onApply) onApply(event, api);
    else if (action && action !== "cancel" && onExtra) onExtra(action, event, api);
    setTimeout(() => {
      if (!dialog.open) finish();
    }, 0);
  });
  dialog.addEventListener("cancel", () => setTimeout(() => !dialog.open && finish(), 0));
  dialog.addEventListener("close", finish);
  dialog.showModal();
  return api;
}

export function textField(label, { value = "", hint = "", type = "text", required = false, placeholder } = {}) {
  const id = uid();
  const input = el("input", { id, type, required, placeholder, "aria-describedby": hint ? `${id}-hint` : null });
  input.value = value;
  const row = el("div", { class: "se-field" }, [
    el("label", { for: id, text: label }),
    input,
    hint ? el("p", { id: `${id}-hint`, class: "se-field__hint", text: hint }) : null,
  ]);
  return { row, input };
}

export function checkField(label, checked) {
  const id = uid();
  const input = el("input", { id, type: "checkbox" });
  input.checked = Boolean(checked);
  return { row: el("div", { class: "se-field se-field--check" }, [input, el("label", { for: id, text: label })]), input };
}

export function selectField(label, options, value) {
  const id = uid();
  const input = el(
    "select",
    { id },
    options.map(([optionValue, text]) => el("option", { value: optionValue, text })),
  );
  if (value !== undefined) input.value = value;
  return { row: el("div", { class: "se-field" }, [el("label", { for: id, text: label }), input]), input };
}

/** A one-line notice in a dialog-free spot (the editor's status line). */
export function announce(target, message) {
  if (target) target.textContent = message;
}
