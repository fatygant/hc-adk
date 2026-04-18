#!/usr/bin/env bash
# Deploy jutra to Cloud Run (europe-west4). Idempotent: re-runs just push a new revision.
#
# Uses build-from-source via Cloud Build. REST/MCP bearer is disabled (empty env).
# Exits non-zero on any failing gcloud step or on a failed post-deploy smoke test.

set -euo pipefail

PROJECT="${PROJECT:-jutra-493710}"
REGION="${REGION:-europe-west4}"
SERVICE="${SERVICE:-jutra}"
SA="${SA:-jutra-689@${PROJECT}.iam.gserviceaccount.com}"
echo "==> Deploying ${SERVICE} to ${PROJECT}/${REGION} as ${SA}"

echo "==> Ensuring required APIs are enabled (idempotent)"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  --project="${PROJECT}"

echo "==> gcloud run deploy (build from source)"
# Hackathon: disable REST/MCP bearer auth (empty env vars).
# If the service previously bound MCP_BEARER_TOKEN/API_BEARER_TOKEN from Secret Manager,
# run once: gcloud run services update "${SERVICE}" --project="${PROJECT}" --region="${REGION}" \
#   --remove-secrets=MCP_BEARER_TOKEN,API_BEARER_TOKEN
gcloud run deploy "${SERVICE}" \
  --quiet \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --source="$(git rev-parse --show-toplevel)" \
  --service-account="${SA}" \
  --allow-unauthenticated \
  --port=8080 \
  --min-instances=1 \
  --max-instances=3 \
  --memory=1Gi \
  --cpu=1 \
  --concurrency=40 \
  --timeout=300 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=true" \
  --set-env-vars="LLM_LOCATION=global" \
  --set-env-vars="EMBED_LOCATION=europe-west4" \
  --set-env-vars="MODEL_REASONING=gemini-3-flash-preview" \
  --set-env-vars="MODEL_CHAT=gemini-3-flash-preview" \
  --set-env-vars="MODEL_EXTRACT=gemini-3.1-flash-lite-preview" \
  --set-env-vars="EMBED_MODEL=text-embedding-005" \
  --set-env-vars="FALLBACK_MODEL=gemini-2.5-flash" \
  --set-env-vars="LOG_LEVEL=INFO" \
  --set-env-vars="GCS_BUCKET=${GCS_BUCKET:-hc-user-photos}" \
  --set-env-vars="IMAGE_LOCATION=${IMAGE_LOCATION:-us-central1}" \
  --set-env-vars="MCP_BEARER_TOKEN=" \
  --set-env-vars="API_BEARER_TOKEN="

# `status.url` still returns the legacy `{hash}-{zone}.a.run.app` address which
# increasingly returns 421 (Misdirected Request). The canonical per-region URL
# is `{service}-{project-number}.{region}.run.app` so we build that directly.
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
echo "==> Deployed at ${URL}"

echo "==> Health check"
# Cloud Run GFE reserves /healthz, so we probe /readyz which is our canonical
# readiness endpoint.
if ! curl -fsS "${URL}/readyz" >/tmp/jutra_health.json; then
  echo "FATAL: /readyz failed" >&2
  exit 1
fi
cat /tmp/jutra_health.json; echo

echo "==> Live MCP smoke (9 tools + detect_crisis_tool, no bearer)"
MCP_BEARER_TOKEN="" python3 "$(git rev-parse --show-toplevel)/scripts/mcp_smoke.py" "${URL}/mcp/"

echo "==> OK: ${URL}"
echo "URL=${URL}" > "$(git rev-parse --show-toplevel)/.deploy_url"
