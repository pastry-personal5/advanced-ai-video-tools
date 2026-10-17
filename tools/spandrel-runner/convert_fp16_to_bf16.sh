#!/usr/bin/env bash
# Convert one float16 PyTorch checkpoint to bfloat16 through the uv workspace.

set -euo pipefail

if [[ $# -ne 2 ]]; then
    printf 'Usage: %s INPUT.pth OUTPUT-bf16.pth\n' "$0" >&2
    exit 2
fi

exec uv run --package spandrel-runner python convert_fp16_to_bf16.py "$1" "$2"
