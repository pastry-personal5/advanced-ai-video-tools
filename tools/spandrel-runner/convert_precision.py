#!/usr/bin/env python3
"""Convert spandrel-loadable SR weights to fp16 or bf16 .safetensors.

  python convert_precision.py MODEL [MODEL ...] [--dtype auto|fp16|bf16] [-o OUTDIR]

auto = fp16 if spandrel supports fp16 for the architecture (ESRGAN, Compact,
SPAN, ...), otherwise bf16 (DAT, HAT, SwinIR, ...). Integer buffers are kept.
Each output is reloaded with spandrel to confirm architecture and scale.
"""
import argparse
import sys
from pathlib import Path

import torch
from safetensors.torch import save_file
from spandrel import ModelLoader, canonicalize_state_dict

DT = {"fp16": torch.float16, "bf16": torch.bfloat16}

ap = argparse.ArgumentParser()
ap.add_argument("models", nargs="+")
ap.add_argument("--dtype", default="auto", choices=["auto", "fp16", "bf16"])
ap.add_argument("-o", "--outdir", default=None, help="default: next to each input")
a = ap.parse_args()

loader = ModelLoader()
failed = 0
for path in map(Path, a.models):
    try:
        sd = canonicalize_state_dict(loader.load_state_dict_from_file(path))
        desc = loader.load_from_state_dict(sd)
        name, scale = desc.architecture.name, desc.scale
        tag = a.dtype if a.dtype != "auto" else ("fp16" if desc.supports_half else "bf16")
        if tag == "fp16" and not desc.supports_half:
            raise ValueError(f"spandrel does not support fp16 for {name}; use --dtype bf16")
        if tag == "bf16" and not desc.supports_bfloat16:
            raise ValueError(f"spandrel does not support bf16 for {name}; use --dtype fp16")
        out = {k: (v.to(DT[tag]) if v.is_floating_point() else v).contiguous() for k, v in sd.items()}
        dst = Path(a.outdir or path.parent) / f"{path.stem}_{tag}.safetensors"
        dst.parent.mkdir(parents=True, exist_ok=True)
        save_file(out, str(dst))
        chk = loader.load_from_file(dst)
        assert (chk.architecture.name, chk.scale) == (name, scale), "reload mismatch"
        print(f"OK  {path.name} -> {dst.name}  [{name} {scale}x {tag}, "
              f"{path.stat().st_size / 1e6:.0f} -> {dst.stat().st_size / 1e6:.0f} MB]")
    except Exception as e:  # keep going with the other files
        failed += 1
        print(f"ERR {path.name}: {e}", file=sys.stderr)
sys.exit(1 if failed else 0)
