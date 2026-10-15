// The infographic content editor (Image generator, plan page, job page).
//
// Each <div data-infographic-editor> builds a form from the template's schema (EDITOR_SCHEMA in
// apps/quality/infographic.py, embedded as #infographic-schema) and keeps its JSON <textarea> (the field
// the server reads) in step on every change. Without JavaScript the textarea is the editor. "Edit as JSON"
// shows the textarea; leaving it rebuilds the form from the JSON. "Preview" draws the infographic on the
// server (no job is made) and shows it with its checks.
//
// data-target: the id of the JSON textarea; data-template: the template, or data-template-select: the id
// of a <select> that chooses it; data-preview-url; data-plan: a plan id, so figures are checked against
// its article.
(function () {
    "use strict";

    function el(tag, attrs, children) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (key) {
            if (key === "text") node.textContent = attrs[key];
            else if (key === "className") node.className = attrs[key];
            else node.setAttribute(key, attrs[key]);
        });
        (children || []).forEach(function (child) { if (child) node.appendChild(child); });
        return node;
    }

    var counter = 0;
    function uid(prefix) { counter += 1; return prefix + "-" + counter; }

    function parse(text) {
        if (!text || !text.trim()) return {};
        try { var value = JSON.parse(text); return value && typeof value === "object" && !Array.isArray(value) ? value : null; }
        catch (e) { return null; }
    }

    // ---- Reading the form back into a spec ----

    function readField(field, container) {
        // Only this block's own fields: a column's "title" is never the graphic's title.
        var input = container.querySelector(":scope > .s-ig__field > [data-key='" + field.key + "'], " +
            ":scope > .s-ig__list > [data-key='" + field.key + "']");
        if (!input) return undefined;
        if (field.type === "list") {
            var rows = Array.prototype.slice.call(input.querySelectorAll(":scope > [data-row]"));
            var items = rows.map(function (row) { return readObject(field.fields, row); })
                .filter(function (item) { return Object.keys(item).length; });
            return items.length ? items : undefined;
        }
        if (field.type === "lines") {
            var lines = input.value.split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
            return lines.length ? lines : undefined;
        }
        if (field.type === "number") {
            var raw = input.value.trim();
            return raw === "" ? undefined : Number(raw);
        }
        if (field.type === "bracket") {
            var text = input.querySelector("[data-part='text']").value.trim();
            var segment = Number(input.querySelector("[data-part='segment']").value);
            return text ? {segment: segment - 1, text: text} : undefined;
        }
        if (field.type === "widget") {
            var type = input.querySelector("[data-part='type']").value;
            var items = input.querySelector("[data-part='items']").value.split(",")
                .map(function (s) { return s.trim(); }).filter(Boolean);
            return type ? {type: type, items: items} : undefined;
        }
        var value = input.value.trim();
        return value === "" ? undefined : value;
    }

    function readObject(fields, container) {
        var out = {};
        fields.forEach(function (field) {
            var value = readField(field, container);
            if (value !== undefined) out[field.key] = value;
        });
        return out;
    }

    // ---- Building the form from a spec ----

    function fieldInput(field, value, onChange) {
        var id = uid("ig");
        var label = el("label", {for: id, text: field.label + (field.required ? " *" : "")});
        var input;
        if (field.type === "textarea" || field.type === "lines") {
            input = el("textarea", {id: id, rows: field.type === "lines" ? 4 : 2});
            input.value = field.type === "lines" ? (value || []).join("\n") : (value || "");
        } else if (field.type === "number") {
            input = el("input", {id: id, type: "number", step: "any"});
            input.value = value === undefined || value === null ? "" : value;
        } else if (field.type === "bracket") {
            input = el("span", {className: "s-cluster"});
            var segment = el("input", {type: "number", min: "1", max: "4", "data-part": "segment", "aria-label": "Over share number", id: id});
            segment.value = value && value.segment !== undefined ? Number(value.segment) + 1 : 1;
            var text = el("input", {type: "text", "data-part": "text", "aria-label": "Bracket label", placeholder: "e.g. What the FLHA catches"});
            text.value = (value && value.text) || "";
            input.appendChild(el("span", {className: "s-muted s-small", text: "Share no."}));
            input.appendChild(segment);
            input.appendChild(text);
        } else if (field.type === "widget") {
            input = el("span", {className: "s-cluster"});
            var type = el("select", {"data-part": "type", id: id, "aria-label": "What is drawn inside"});
            [["", "Lines only"], ["chips", "Chips (e.g. L, M, H)"], ["split", "Two columns"]].forEach(function (pair) {
                var option = el("option", {value: pair[0], text: pair[1]});
                if (value && value.type === pair[0]) option.selected = true;
                type.appendChild(option);
            });
            var items = el("input", {type: "text", "data-part": "items", "aria-label": "Their labels, separated by commas", placeholder: "Labels, comma separated"});
            items.value = value && value.items ? value.items.join(", ") : "";
            input.appendChild(type);
            input.appendChild(items);
        } else {
            input = el("input", {id: id, type: "text"});
            input.value = value || "";
        }
        input.setAttribute("data-key", field.key);
        input.addEventListener("input", onChange);
        input.addEventListener("change", onChange);
        var wrap = el("div", {className: "s-keys__field s-ig__field"}, [label, input]);
        if (field.hint) wrap.appendChild(el("p", {className: "s-muted s-small s-m0", text: field.hint}));
        return wrap;
    }

    function listInput(field, value, onChange) {
        var rows = el("div", {className: "s-ig__rows", "data-key": field.key});
        var count = el("span", {className: "s-muted s-small"});
        var add = el("button", {type: "button", className: "button button-small button-secondary", text: "Add " + field.item});

        function refresh() {
            var n = rows.querySelectorAll(":scope > [data-row]").length;
            count.textContent = n + " of " + field.min + (field.min === field.max ? "" : " to " + field.max);
            add.disabled = n >= field.max;
            rows.querySelectorAll("[data-remove]").forEach(function (b) { b.disabled = n <= field.min; });
            Array.prototype.forEach.call(rows.querySelectorAll(":scope > [data-row] > legend"), function (legend, i) {
                legend.textContent = field.item.charAt(0).toUpperCase() + field.item.slice(1) + " " + (i + 1);
            });
        }

        function addRow(item) {
            var row = el("fieldset", {className: "s-ig__row", "data-row": "1"}, [el("legend", {})]);
            field.fields.forEach(function (sub) { row.appendChild(fieldInput(sub, (item || {})[sub.key], onChange)); });
            var remove = el("button", {type: "button", className: "button button-small button-secondary no", text: "Remove", "data-remove": "1"});
            remove.addEventListener("click", function () { row.remove(); refresh(); onChange(); });
            row.appendChild(remove);
            rows.appendChild(row);
            refresh();
        }

        (value && value.length ? value : []).forEach(addRow);
        while (rows.querySelectorAll(":scope > [data-row]").length < field.min) addRow({});
        add.addEventListener("click", function () { addRow({}); onChange(); });
        var head = el("div", {className: "s-row-actions"}, [el("strong", {text: field.label}), count, el("span", {className: "s-spacer"}), add]);
        return el("div", {className: "s-ig__list"}, [head, rows]);
    }

    // ---- One editor ----

    function Editor(root, schemas) {
        var target = document.getElementById(root.dataset.target);
        var select = root.dataset.templateSelect ? document.getElementById(root.dataset.templateSelect) : null;
        var form = el("div", {className: "s-ig__form"});
        var preview = el("div", {className: "s-ig__preview", "aria-live": "polite"});
        var toggle = el("button", {type: "button", className: "button button-small button-secondary", text: "Edit as JSON"});
        var previewButton = el("button", {type: "button", className: "button button-small", text: "Preview"});
        var jsonMode = false;
        var extras = {};  // keys of the spec the form doesn't show (e.g. "highlight"), kept as they were

        function template() { return select ? select.value : root.dataset.template; }

        function sync() {
            var fields = schemas[template()];
            if (!fields || jsonMode) return;
            var spec = readObject(fields, form);
            if (Object.keys(spec).length) spec = Object.assign({}, extras, spec);
            target.value = Object.keys(spec).length ? JSON.stringify(spec, null, 2) : "";
        }

        function build() {
            form.innerHTML = "";
            var fields = schemas[template()];
            if (!fields) {
                form.appendChild(el("p", {className: "s-muted", text: "Choose a template to edit its content here."}));
                return;
            }
            var spec = parse(target.value);
            if (spec === null) {
                form.appendChild(el("p", {className: "s-callout", text: "The JSON below can't be read, so the form is empty. Fix it, or start again in the form."}));
                spec = {};
            }
            var known = fields.map(function (field) { return field.key; });
            extras = {};
            Object.keys(spec).forEach(function (key) { if (known.indexOf(key) === -1) extras[key] = spec[key]; });
            fields.forEach(function (field) {
                form.appendChild(field.type === "list" ? listInput(field, spec[field.key], sync) : fieldInput(field, spec[field.key], sync));
            });
        }

        toggle.addEventListener("click", function () {
            jsonMode = !jsonMode;
            target.hidden = !jsonMode;
            form.hidden = jsonMode;
            toggle.textContent = jsonMode ? "Back to the form" : "Edit as JSON";
            if (!jsonMode) build();
        });

        previewButton.addEventListener("click", function () {
            sync();
            var csrf = (root.closest("form") || document).querySelector("[name=csrfmiddlewaretoken]");
            preview.innerHTML = "";
            preview.appendChild(el("p", {className: "s-muted", text: "Drawing the preview..."}));
            fetch(root.dataset.previewUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": csrf ? csrf.value : ""},
                body: JSON.stringify({template: template(), spec: parse(target.value) || {}, plan: root.dataset.plan || null}),
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    preview.innerHTML = "";
                    if (data.error) { preview.appendChild(el("p", {className: "s-callout", text: data.error})); return; }
                    var tag = data.blocked ? "warn" : "ok";
                    preview.appendChild(el("p", {className: "s-m0"}, [el("span", {className: "s-tag s-tag--" + tag, text: data.blocked ? "Needs edits" : "Passes its checks"})]));
                    if (data.problems.length) {
                        var list = el("ul", {className: "s-small"});
                        data.problems.forEach(function (p) { list.appendChild(el("li", {text: (p.level === "block" ? "Fix: " : "Note: ") + p.text})); });
                        preview.appendChild(list);
                    }
                    if (data.image) preview.appendChild(el("img", {src: data.image, alt: data.alt || "Infographic preview", className: "s-image"}));
                })
                .catch(function () {
                    preview.innerHTML = "";
                    preview.appendChild(el("p", {className: "s-callout", text: "The preview couldn't be drawn; try again."}));
                });
        });

        if (select) select.addEventListener("change", function () { target.value = ""; build(); });
        target.hidden = true;
        root.appendChild(form);
        var actions = el("div", {className: "s-row-actions"}, [toggle]);
        if (root.dataset.previewUrl) actions.insertBefore(previewButton, toggle);
        root.appendChild(actions);
        root.appendChild(preview);
        build();
    }

    // Wagtail renders extra_js before the page content, and this file is deferred: start once the page is
    // parsed.
    function start() {
        var source = document.getElementById("infographic-schema");
        if (!source) return;
        var schemas = JSON.parse(source.textContent);
        document.querySelectorAll("[data-infographic-editor]").forEach(function (root) {
            if (!root.dataset.ready) { root.dataset.ready = "1"; new Editor(root, schemas); }
        });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
