"""Local generative fill with LaMa (big-lama TorchScript model); runs on CUDA when available, else CPU.

Replaces the simple-lama-inpainting package, whose pins (numpy<2, pillow<10,
opencv<5) would downgrade the rest of the toolchain. Needs only PyTorch.

Model: big-lama.pt (~196 MB), the TorchScript export published with
simple-lama-inpainting (https://github.com/enesmsahin/simple-lama-inpainting),
from LaMa by Suvorov et al., Apache-2.0 (https://github.com/advimman/lama).
It is downloaded once to ~/.cache/sds-hero/ (outside the skill folder); set
SDS_LAMA_MODEL to use a copy elsewhere. The SHA-256 is checked; a mismatching file is refused.

    from lama import inpaint
    filled = inpaint(rgb_uint8_array, mask_bool_array)   # True = fill this pixel
"""
import hashlib
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np

MODEL_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
MODEL_SHA256 = "7ba7aa7ac37a4d41fdbbeba3a2af7ead18058552997e3a3cd1a3b2210c9e6b4c"
CACHE = Path(os.environ.get("SDS_LAMA_MODEL", Path.home() / ".cache" / "sds-hero" / "big-lama.pt"))
_model = None


def model_path():
    if CACHE.exists() and CACHE.stat().st_size > 100_000_000:
        return CACHE
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".part")
    sys.stderr.write(f"Downloading the LaMa model (~196 MB, once) to {CACHE}\n")
    with urllib.request.urlopen(urllib.request.Request(MODEL_URL, headers={"User-Agent": "sds-hero"}), timeout=60) as r, \
            open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        tmp.unlink()
        raise RuntimeError(f"LaMa model checksum mismatch ({digest}); download refused")
    tmp.replace(CACHE)
    return CACHE


def available():
    """True when PyTorch is installed (the model itself downloads on first use)."""
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def device():
    """'cuda' when a working CUDA build of torch sees a GPU (override: SDS_LAMA_DEVICE=cpu), else 'cpu'."""
    import torch
    want = os.environ.get("SDS_LAMA_DEVICE")
    if want:
        return want
    try:
        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")  # fails on wheels without kernels for this GPU
            return "cuda"
    except Exception:
        pass
    return "cpu"


def load():
    global _model
    if _model is None:
        import warnings
        import torch
        dev = device()
        with warnings.catch_warnings():  # torch.jit.load works; its deprecation notice is noise here
            warnings.simplefilter("ignore", FutureWarning)
            _model = torch.jit.load(str(model_path()), map_location=dev).eval()
    return _model


def inpaint(rgb, mask, max_side=1024):
    """Fill mask==True pixels of an RGB uint8 array; works at <= max_side px, returns full size."""
    import torch
    from PIL import Image
    h, w = mask.shape
    scale = min(1.0, max_side / max(h, w))
    sw, sh = int(round(w * scale)), int(round(h * scale))
    img = np.asarray(Image.fromarray(rgb).resize((sw, sh), Image.LANCZOS)).astype(np.float32) / 255
    m = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((sw, sh), Image.NEAREST)) > 127
    ph, pw = -sh % 8, -sw % 8  # the model needs sides divisible by 8
    img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="symmetric")
    m = np.pad(m, ((0, ph), (0, pw)), mode="symmetric")
    model = load()
    dev = device()
    x = torch.from_numpy(img.transpose(2, 0, 1)).unsqueeze(0).to(dev)
    mk = torch.from_numpy(m[None, None].astype(np.float32)).to(dev)
    with torch.inference_mode():
        out = model(x, mk)[0].permute(1, 2, 0).cpu().numpy()
    out = (np.clip(out, 0, 1) * 255).astype(np.uint8)[:sh, :sw]
    return np.asarray(Image.fromarray(out).resize((w, h), Image.LANCZOS))
