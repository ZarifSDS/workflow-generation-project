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

  // Run estimate next to Start run: time, money and context, from the chosen models (apps/studio/estimates.py
  // works it out the same way). Prices are what this key is billed per million tokens: free-tier,
  // subscription and local models carry 0, models without a known price carry nothing.
  const estimateLine = form.querySelector("[data-run-estimate]");
  function money(value) {
    if (value === 0) return "$0";
    if (value < 0.01) return "under $0.01";
    return "$" + value.toFixed(2);
  }
  function minutes(seconds) {
    return seconds < 90 ? `${Math.max(1, Math.round(seconds))} s` : `${Math.round(seconds / 60)} min`;
  }
  function estimate() {
    if (!estimateLine) return;
    let seconds = 0, cost = 0, paid = 0, unknown = 0, small = [];
    form.querySelectorAll("tr[data-types]").forEach((row) => {
      if (row.hidden) return;
      const enabled = row.querySelector('input[name$="_enabled"]');
      if (enabled && !enabled.checked) return;
      const select = row.querySelector("select[data-step-model]");
      const option = select && select.options[select.selectedIndex];
      if (!option) return;
      seconds += Number(option.dataset.secs || 60);
      if (!row.dataset.stepIn) return;
      const sop = row.querySelector("[data-self-review]");
      const tokensIn = Number(row.dataset.stepIn) + (sop && sop.checked ? Number(row.dataset.sopIn || 0) : 0);
      const tokensOut = Number(row.dataset.stepOut) + (sop && sop.checked ? Number(row.dataset.sopOut || 0) : 0);
      if (option.dataset.ctx && Number(row.dataset.need) > Number(option.dataset.ctx)) {
        small.push(row.querySelector("th").textContent.trim());
      }
      if (option.dataset.in === undefined) { unknown += 1; return; }
      const stepCost = (tokensIn * Number(option.dataset.in) + tokensOut * Number(option.dataset.out)) / 1e6;
      if (stepCost > 0) paid += 1;
      cost += stepCost;
    });
    const parts = [`About ${minutes(seconds)}`];
    parts.push(paid ? `about ${money(cost)} (${paid} paid step${paid > 1 ? "s" : ""})` : unknown ? "free models where the price is known" : "free");
    if (unknown) parts.push(`price unknown for ${unknown} step${unknown > 1 ? "s" : ""}`);
    if (small.length) parts.push(`context too small: ${small.join(", ")}`);
    estimateLine.textContent = parts.join(" · ");
    estimateLine.classList.toggle("s-run-estimate--warn", small.length > 0);
  }
  form.addEventListener("change", estimate);

  typeInputs.forEach((input) => input.addEventListener("change", applyType));
  if (presetSelect) presetSelect.addEventListener("change", applyPreset);
  applyType();
  estimate();
})();
