"""Local ComfyUI image generation through its HTTP API.

The "model" is the file name of a workflow you exported from ComfyUI in API format
(Workflow > Export (API)) and saved in settings.COMFYUI_WORKFLOWS_DIR. Before queueing it the
adapter patches the prompt text, the latent width/height and the seed, finding the nodes by class:

- prompt: the text node feeding the sampler's positive conditioning (KSampler `positive`,
  CFGGuider `positive` or BasicGuider `conditioning`, followed through nodes such as FluxGuidance);
  a node titled "Positive prompt" wins.
- size: every node with integer `width` and `height` inputs whose class contains "Latent".
- seed: every integer `seed` or `noise_seed` input.

The GPU has 8 GB, so Ollama's loaded models are unloaded first (keep_alive 0) and ComfyUI is
asked to free its memory afterwards.
"""

import json
import random
import time
import uuid
from pathlib import Path

import httpx
from django.conf import settings

from ..types import ImageResult, ProviderError
from .cloudflare import _mime_type

SAMPLER_INPUTS = {
    "KSampler": "positive",
    "KSamplerAdvanced": "positive",
    "CFGGuider": "positive",
    "BasicGuider": "conditioning",
}
SEED_INPUTS = ("seed", "noise_seed")


def load_workflow(name):
    folder = Path(settings.COMFYUI_WORKFLOWS_DIR)
    path = (folder / name).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise ProviderError(
            "not_configured",
            f"ComfyUI workflow '{name}' not found in {folder}. Export it from ComfyUI in API format "
            "(see docs/setup.md).",
        )
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProviderError("bad_request", f"ComfyUI workflow '{name}' isn't valid JSON: {error}") from error
    if not isinstance(workflow, dict) or not all(
        isinstance(node, dict) and "class_type" in node for node in workflow.values()
    ):
        raise ProviderError(
            "bad_request",
            f"ComfyUI workflow '{name}' isn't in API format. Use Workflow > Export (API) in ComfyUI.",
        )
    return workflow


def _is_link(value):
    return isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)


def _text_node_from(workflow, link):
    """Follow conditioning links back to the node with a `text` input."""
    seen = set()
    while _is_link(link) and link[0] not in seen:
        seen.add(link[0])
        node = workflow.get(link[0]) or {}
        inputs = node.get("inputs", {})
        if isinstance(inputs.get("text"), str):
            return link[0]
        link = inputs.get("conditioning")
    return None


def find_prompt_node(workflow):
    for node_id, node in workflow.items():
        title = (node.get("_meta") or {}).get("title", "")
        if "positive" in title.lower() and isinstance(node.get("inputs", {}).get("text"), str):
            return node_id
    for node in workflow.values():
        key = SAMPLER_INPUTS.get(node["class_type"])
        if key:
            found = _text_node_from(workflow, node.get("inputs", {}).get(key))
            if found:
                return found
    text_nodes = [
        node_id
        for node_id, node in workflow.items()
        if node["class_type"].startswith("CLIPTextEncode")
        and isinstance(node.get("inputs", {}).get("text"), str)
    ]
    if len(text_nodes) == 1:
        return text_nodes[0]
    raise ProviderError(
        "bad_request",
        "Couldn't tell which ComfyUI node holds the prompt. Rename it to “Positive prompt” in ComfyUI "
        "and export the workflow again.",
    )


def patch_workflow(workflow, prompt, options):
    """A copy of the workflow with the prompt, size and seed applied. Returns (workflow, seed)."""
    workflow = json.loads(json.dumps(workflow))
    workflow[find_prompt_node(workflow)]["inputs"]["text"] = prompt
    seed = options.get("seed")
    if seed is None:
        seed = random.randint(0, 2**31 - 1)
    for node in workflow.values():
        inputs = node.get("inputs", {})
        if (
            "Latent" in node["class_type"]
            and isinstance(inputs.get("width"), int)
            and isinstance(inputs.get("height"), int)
        ):
            inputs["width"] = options.get("width", inputs["width"])
            inputs["height"] = options.get("height", inputs["height"])
        for key in SEED_INPUTS:
            if isinstance(inputs.get(key), int):
                inputs[key] = seed
    return workflow, seed


def unload_ollama():
    """Free the GPU for ComfyUI: ask Ollama to unload every loaded model. Best effort."""
    try:
        with httpx.Client(
            base_url=settings.OLLAMA_BASE_URL, headers={"User-Agent": settings.AI_USER_AGENT}, timeout=30
        ) as client:
            loaded = client.get("/api/ps").json().get("models", [])
            for model in loaded:
                client.post("/api/generate", json={"model": model["name"], "keep_alive": 0})
            return [model["name"] for model in loaded]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


def _raise_for_status(response, what):
    if response.status_code >= 500:
        raise ProviderError(
            "server", f"ComfyUI {what} {response.status_code}: {response.text[:300]}", response.status_code
        )
    if response.status_code >= 400:
        raise ProviderError(
            "bad_request",
            f"ComfyUI {what} {response.status_code}: {response.text[:300]}",
            response.status_code,
        )


def _first_image(history_entry):
    """The first saved image (SaveImage, type "output"), else the first preview."""
    images = [
        image
        for output in (history_entry.get("outputs") or {}).values()
        for image in output.get("images") or []
    ]
    return next((image for image in images if image.get("type") == "output"), images[0] if images else None)


def _wait_for_image(client, prompt_id, timeout, poll):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/history/{prompt_id}")
        _raise_for_status(response, "history")
        entry = response.json().get(prompt_id)
        if entry:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                messages = [m for m in status.get("messages", []) if m and m[0] == "execution_error"]
                detail = messages[0][1].get("exception_message", "") if messages else ""
                raise ProviderError("server", f"ComfyUI workflow failed: {detail}"[:400])
            image = _first_image(entry)
            if image:
                return image
            if status.get("completed"):
                raise ProviderError("bad_request", "The ComfyUI workflow finished without an image output.")
        time.sleep(poll)
    raise ProviderError("network", f"ComfyUI didn't finish within {timeout} s")


def generate(spec, model, prompt, options):
    workflow, seed = patch_workflow(load_workflow(model), prompt, options)
    unloaded = unload_ollama() if options.get("unload_ollama", True) else []
    started = time.monotonic()
    try:
        with httpx.Client(base_url=spec.base_url, headers=spec.headers, timeout=60) as client:
            try:
                response = client.post("/prompt", json={"prompt": workflow, "client_id": uuid.uuid4().hex})
                _raise_for_status(response, "prompt")
                prompt_id = response.json()["prompt_id"]
                image = _wait_for_image(
                    client, prompt_id, options.get("timeout", 600), options.get("poll_seconds", 1.0)
                )
                response = client.get(
                    "/view",
                    params={
                        "filename": image["filename"],
                        "subfolder": image.get("subfolder", ""),
                        "type": image.get("type", "output"),
                    },
                )
                _raise_for_status(response, "view")
                data = response.content
            finally:
                try:
                    client.post("/free", json={"unload_models": True, "free_memory": True})
                except httpx.HTTPError:
                    pass
    except httpx.TimeoutException as error:
        raise ProviderError("network", f"ComfyUI timed out: {error}") from error
    except httpx.TransportError as error:
        raise ProviderError(
            "network", f"Cannot reach ComfyUI at {spec.base_url}. Is it running? ({error})"
        ) from error
    except (KeyError, ValueError) as error:
        raise ProviderError("unknown", f"Unexpected ComfyUI response: {error}") from error

    return ImageResult(
        provider=spec.name,
        model=model,
        data=data,
        mime_type=_mime_type(data),
        total_time=time.monotonic() - started,
        stats={"seed": seed, "unloaded_ollama_models": unloaded},
    )
