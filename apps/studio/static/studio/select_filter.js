// A filter box above long model dropdowns (Settings › Default models, the run screen, the brief wizard):
// with every model a provider lists for your key, a dropdown can hold hundreds of options. Typing narrows
// the options to those containing every word; the chosen option always stays.
(function () {
    "use strict";
    var MIN_OPTIONS = 40;

    function enhance(select) {
        if (select.multiple || select.dataset.filterReady || select.dataset.noFilter) return;
        var options = select.querySelectorAll("option[value]:not([value=''])");
        if (options.length < MIN_OPTIONS) return;
        select.dataset.filterReady = "1";
        var box = document.createElement("input");
        box.type = "search";
        box.className = "s-select-filter";
        box.placeholder = "Filter " + options.length + " models";
        box.setAttribute("aria-label", "Filter the options of the next list");
        box.autocomplete = "off";
        select.parentNode.insertBefore(box, select);
        box.addEventListener("input", function () {
            var words = box.value.toLowerCase().split(/\s+/).filter(Boolean);
            select.querySelectorAll("option").forEach(function (option) {
                if (!option.value) return;
                var text = option.textContent.toLowerCase();
                option.hidden = !option.selected && !words.every(function (w) { return text.indexOf(w) !== -1; });
            });
            select.querySelectorAll("optgroup").forEach(function (group) {
                group.hidden = !group.querySelector("option:not([hidden])");
            });
        });
    }

    function run() {
        document.querySelectorAll(".studio select").forEach(enhance);
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
    else run();
})();
