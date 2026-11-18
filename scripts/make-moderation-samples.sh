#!/usr/bin/env bash
# Generate small deterministic MP4 samples for demonstrating video moderation (BE-29 / M9):
#   1. approved-sample.mp4: 6-second clean video with benign tone (passes duration + AI moderation)
#   2. rejected-too-long.mp4: 35-second video (rejected deterministically by ffprobe > 30 s check)
#
# Usage:
#   ./scripts/make-moderation-samples.sh [output_dir]
# Uses local ffmpeg if installed, otherwise runs ffmpeg inside the `worker` compose container.
set -euo pipefail

OUT_DIR="${1:-tmp/moderation-samples}"
mkdir -p "$OUT_DIR"

echo "Generating $OUT_DIR/approved-sample.mp4 (6 s)..."
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i color=c=0x1e3a5f:s=320x240:d=6 \
    -f lavfi -i sine=frequency=440:duration=6 \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart \
    "$OUT_DIR/approved-sample.mp4"
  echo "Generating $OUT_DIR/rejected-too-long.mp4 (35 s)..."
  ffmpeg -y -hide_banner -loglevel error \
    -f lavfi -i color=c=0x7f1d1d:s=320x240:d=35 \
    -f lavfi -i sine=frequency=330:duration=35 \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart \
    "$OUT_DIR/rejected-too-long.mp4"
else
  docker compose run --rm --no-deps -v "$(cd "$OUT_DIR" && pwd):/out" worker \
    sh -c 'ffmpeg -y -hide_banner -loglevel error \
      -f lavfi -i color=c=0x1e3a5f:s=320x240:d=6 \
      -f lavfi -i sine=frequency=440:duration=6 \
      -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart \
      /out/approved-sample.mp4 \
    && ffmpeg -y -hide_banner -loglevel error \
      -f lavfi -i color=c=0x7f1d1d:s=320x240:d=35 \
      -f lavfi -i sine=frequency=330:duration=35 \
      -c:v libx264 -pix_fmt yuv420p -c:a aac -b:a 64k -movflags +faststart \
      /out/rejected-too-long.mp4'
fi

echo "Done:"
ls -lh "$OUT_DIR/approved-sample.mp4" "$OUT_DIR/rejected-too-long.mp4"
echo ""
echo "Defense note: for an OpenAI-flagged rejection demo with OPENAI_API_KEY set,"
echo "record a short clip speaking policy-violating text (or upload rejected-too-long.mp4"
echo "to verify server-side ffprobe duration rejection)."
