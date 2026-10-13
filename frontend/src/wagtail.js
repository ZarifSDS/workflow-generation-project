// The studio's editor endpoints (apps/studio/views/editor_api.py) and Wagtail's own chooser modals.
// URLs and limits come from data attributes on the editor form (run_workspace.html).

const CHOOSERS = {
  page: ["PageChooserModal", "chooserPage"],
  image: ["ImageChooserModal", "chooserImage"],
  document: ["DocumentChooserModal", "chooserDocument"],
};

// PageChooserModal needs the page types; any page can be linked.
const OPTIONS = { page: { modelNames: ["wagtailcore.page"] } };

async function json(response) {
  let body = {};
  try {
    body = await response.json();
  } catch {
    /* not JSON: e.g. a proxy error page */
  }
  if (!response.ok) {
    const fallback = response.status === 413 ? "The file is too large." : `The server said ${response.status}.`;
    throw new Error(body.error || fallback);
  }
  return body;
}

export function createApi(form) {
  const data = form.dataset;
  const csrf = form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const headers = { "X-CSRFToken": csrf, "X-Requested-With": "fetch" };

  return {
    uploadMax: Number(data.uploadMax) || 0,
    uploadTypes: (data.uploadTypes || "").split(",").filter(Boolean),

    async references({ images = [], pages = [], documents = [] }) {
      if (!data.apiRefs) return {};
      const params = new URLSearchParams({ image: images.join(","), page: pages.join(","), document: documents.join(",") });
      return json(await fetch(`${data.apiRefs}?${params}`, { headers, credentials: "same-origin" }));
    },

    async upload(file, { alt = "", decorative = false, brand = true, logoCorner = "auto" } = {}) {
      const body = new FormData();
      body.append("file", file);
      body.append("alt", alt);
      body.append("decorative", decorative ? "1" : "0");
      body.append("brand", brand ? "1" : "0");
      body.append("logo_corner", logoCorner);
      return json(await fetch(data.apiUpload, { method: "POST", body, headers, credentials: "same-origin" }));
    },

    async embed(url) {
      const params = new URLSearchParams({ url });
      return json(await fetch(`${data.apiEmbed}?${params}`, { headers, credentials: "same-origin" }));
    },

    canChoose(kind) {
      const [global, attr] = CHOOSERS[kind];
      return Boolean(window[global] && data[attr]);
    },

    /** Opens Wagtail's chooser; resolves with {id, title, ...} when something is chosen (never on cancel). */
    choose(kind) {
      const [global, attr] = CHOOSERS[kind];
      const Modal = window[global];
      return new Promise((resolve, reject) => {
        if (!Modal || !data[attr]) {
          reject(new Error("The chooser isn't available on this page."));
          return;
        }
        new Modal(data[attr]).open(OPTIONS[kind] || {}, (result) => {
          const preview = result.preview || {};
          resolve({
            id: String(result.id),
            title: result.adminTitle || result.title || "",
            url: result.url || preview.url || "",
            width: preview.width,
            height: preview.height,
          });
        });
      });
    },
  };
}

/** Is this file an image the server accepts? Returns an error message or "". */
export function checkImageFile(file, api) {
  const extension = (file.name.split(".").pop() || "").toLowerCase();
  if (api.uploadTypes.length && !api.uploadTypes.includes(extension)) {
    return `${file.name}: use ${api.uploadTypes.map((t) => t.toUpperCase()).join(", ")}.`;
  }
  if (api.uploadMax && file.size > api.uploadMax) {
    return `${file.name} is ${(file.size / 1048576).toFixed(1)} MB; images can be up to ${Math.round(api.uploadMax / 1048576)} MB.`;
  }
  return "";
}
