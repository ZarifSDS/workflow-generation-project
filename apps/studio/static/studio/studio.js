// Content Studio: brief wizard behaviour (progressive enhancement; the form works without it).
(function () {
  const form = document.querySelector("[data-studio-wizard]");
  if (!form) return;

  const typeInputs = form.querySelectorAll('input[name="content_type"]');
  const presetSelect = form.querySelector('select[name="preset"]');
  const presets = JSON.parse(document.getElementById("studio-presets")?.textContent || "{}");

  function currentType() {
    const checked = form.querySelector('input[name="content_type"]:checked');
    return checked ? checked.value : "seo_blog";
  }

  // Show only the fields and pipeline steps that apply to the chosen content type.
  function applyType() {
    const type = currentType();
    form.querySelectorAll("[data-types]").forEach((el) => {
      const show = el.dataset.types.split(" ").includes(type);
      el.hidden = !show;
      el.querySelectorAll("input, select, textarea").forEach((field) => { field.disabled = !show; });
    });
  }

  function setField(name, value) {
    const field = form.elements.namedItem(name);
    if (!field || value === undefined || value === null) return;
    if (field instanceof RadioNodeList) {
      field.forEach((radio) => { radio.checked = radio.value === String(value); });
    } else {
      field.value = value;
    }
  }

  // Fill fields and step models from the chosen preset; every field stays editable.
  function applyPreset() {
    const preset = presets[presetSelect.value];
    if (!preset) return;
    ["content_type", "region", "fkgl", "wordcount", "audience", "comprehension", "cta_style", "narrative_mode"]
      .forEach((name) => setField(name, preset[name]));
    Object.entries(preset.step_models || {}).forEach(([step, key]) => {
      const select = form.querySelector(`select[data-step-model="${step}"]`);
      if (select && [...select.options].some((o) => o.value === key && !o.disabled)) select.value = key;
    });
    applyType();
  }

  // A region's audience profile fills audience and reading grade, unless you've changed them yourself.
  const audiences = JSON.parse(document.getElementById("studio-audiences")?.textContent || "{}");
  const regionSelect = form.elements.namedItem("region");
  let lastRegion = regionSelect ? regionSelect.value : "";
  function applyAudience() {
    const previous = audiences[lastRegion] || {};
    const next = audiences[regionSelect.value];
    lastRegion = regionSelect.value;
    if (!next) return;
    [["audience", "audience"], ["fkgl", "fkgl"]].forEach(([field, key]) => {
      const input = form.elements.namedItem(field);
      if (input && (!input.value || input.value === previous[key] || Number(input.value) === Number(previous[key]))) {
        input.value = next[key];
      }
    });
  }
  if (regionSelect && regionSelect.tagName === "SELECT") regionSelect.addEventListener("change", applyAudience);

  // Autopilot: every text step self-reviews and nothing waits for approval; "Review each step" restores
  // the default gates. Boxes stay editable either way (the server reads the boxes, not the mode).
  const modeInputs = form.querySelectorAll('input[name="mode"]');
  const defaultGates = new Map([...form.querySelectorAll("[data-gate]")].map((box) => [box, box.checked]));
  function applyMode() {
    const checked = form.querySelector('input[name="mode"]:checked');
    const autopilot = checked && checked.value === "autopilot";
    form.querySelectorAll("[data-self-review]").forEach((box) => { box.checked = autopilot; });
    defaultGates.forEach((wasChecked, box) => { box.checked = autopilot ? false : wasChecked; });
  }
  modeInputs.forEach((input) => input.addEventListener("change", applyMode));

  typeInputs.forEach((input) => input.addEventListener("change", applyType));
  if (presetSelect) presetSelect.addEventListener("change", applyPreset);
  applyType();
})();
