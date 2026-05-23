#!/usr/bin/env bash
set -euo pipefail

source .env

REGISTRY_IMAGE="${REGISTRY_IMAGE:-ghcr.io/mlahr/pii-scout}"
MODEL_TAG="models-latest"
SHA_TAG="models-$(git rev-parse --short HEAD 2>/dev/null || echo manual)"

echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin

# Build the model image (amd64 for GitHub Actions runners)
docker build --platform linux/amd64 -f Dockerfile.models -t "${REGISTRY_IMAGE}:${MODEL_TAG}" .

# Tag with a versioned tag as well
# (useful for pinning exact model contents)
docker tag "${REGISTRY_IMAGE}:${MODEL_TAG}" "${REGISTRY_IMAGE}:${SHA_TAG}"

# Push both tags

docker push "${REGISTRY_IMAGE}:${MODEL_TAG}"
docker push "${REGISTRY_IMAGE}:${SHA_TAG}"

printf 'Pushed: %s:%s and %s:%s\n' "${REGISTRY_IMAGE}" "${MODEL_TAG}" "${REGISTRY_IMAGE}" "${SHA_TAG}"
