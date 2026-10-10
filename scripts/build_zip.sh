#!/usr/bin/env bash
# Crea lo ZIP del plugin da un riferimento git (default HEAD).
# Uso: scripts/build_zip.sh [riferimento] [cartella_output]
set -euo pipefail

REF="${1:-HEAD}"
OUT="${2:-.}"
NAME="raster_auto_style"

cd "$(git rev-parse --show-toplevel)"
VERSION="$(git show "$REF:metadata.txt" | sed -n 's/^version=//p' | tr -d '\r')"
[ -n "$VERSION" ] || { echo "version non trovata in metadata.txt" >&2; exit 1; }

mkdir -p "$OUT"
ZIP="$OUT/${NAME}-v${VERSION}.zip"
# --prefix crea la cartella radice con il nome del plugin; gli esclusi sono in .gitattributes
git archive --format=zip --prefix="${NAME}/" "$REF" -o "$ZIP"
echo "$ZIP"
