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

  typeInputs.forEach((input) => input.addEventListener("change", applyType));
  if (presetSelect) presetSelect.addEventListener("change", applyPreset);
  applyType();
})();
