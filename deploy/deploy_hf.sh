#!/usr/bin/env sh
# Deploy the read-only API to a Hugging Face Space (free, Docker SDK).
#   prerequisites: `hf auth login`; the commit to serve is pushed to GitHub (public repo)
#   usage: sh deploy/deploy_hf.sh <hf-user>/<space-name> [git-ref]   (default ref: HEAD's commit)
set -eu
SPACE="${1:?usage: deploy_hf.sh <hf-user>/<space-name> [git-ref]}"
REF="${2:-$(git rev-parse HEAD)}"

if ! git branch -r --contains "$REF" | grep -q "origin/"; then
  echo "commit $REF is not on GitHub yet; push it first (the Space clones the public repo)" >&2
  exit 1
fi

TMP="$(mktemp -d)"
cp deploy/hf-space/README.md "$TMP/README.md"
sed "s|^ARG REF=.*|ARG REF=$REF|" deploy/hf-space/Dockerfile > "$TMP/Dockerfile"

hf repo create "$SPACE" --repo-type space --space-sdk docker --exist-ok
hf upload "$SPACE" "$TMP" . --repo-type space --commit-message "Deploy $REF"
echo "Space: https://huggingface.co/spaces/$SPACE  (API: https://$(echo "$SPACE" | tr '/' '-' | tr '[:upper:]' '[:lower:]').hf.space)"
echo "Then set the Space variable NAVIGATOR_CORS_ORIGINS to the Vercel URL (Settings > Variables)."
rm -rf "$TMP"
