#!/bin/sh
# Compress exported avatars for the web: textures to 1024px WebP; geometry, skin and morph
# targets (visemes, ARKit face units) untouched. ~9MB per character, ~3.5MB over gzip.
#
# Usage (from the repo root):  sh blender/compress_avatars.sh [name ...]   (default: all)
set -e
cd "$(dirname "$0")/.."
names="${*:-$(cd tools/avatars && ls *.glb | sed 's/\.glb$//')}"
mkdir -p frontend/avatars
for name in $names; do
  npx --yes @gltf-transform/cli@4 optimize "tools/avatars/$name.glb" "frontend/avatars/$name.glb" \
    --compress false --texture-compress webp --texture-size 1024 \
    --simplify false --join false --flatten false --weld false --instance false --palette false
done
