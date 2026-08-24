#/usr/bin/env bash
set -x

INPUT_DIR=${HOME}/c-work/8005-output

uv run advanced-ai-video-tools process \
   --input ${INPUT_DIR}/clip-01.mov \
   --input ${INPUT_DIR}/clip-02.mov \
   --output-dir ./output
