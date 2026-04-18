#!/usr/bin/env bash
# Roll Cloud Run traffic back from the latest ready revision to the previous one.
# Safe to re-run: if already pointing at the previous revision, it exits cleanly.

set -euo pipefail

PROJECT="${PROJECT:-jutra-493710}"
REGION="${REGION:-europe-west4}"
SERVICE="${SERVICE:-jutra}"

CURRENT="$(gcloud run services describe "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" \
  --format='value(status.latestReadyRevisionName)')"

PREV="$(gcloud run revisions list \
  --project="${PROJECT}" --region="${REGION}" \
  --service="${SERVICE}" \
  --filter="status.conditions.type=Ready AND status.conditions.status=True" \
  --sort-by="~metadata.creationTimestamp" \
  --limit=2 --format='value(metadata.name)' | sed -n '2p')"

if [[ -z "${PREV}" ]]; then
  echo "FATAL: no previous ready revision to roll back to" >&2
  exit 1
fi

echo "==> Current: ${CURRENT}"
echo "==> Rolling back to: ${PREV}"

gcloud run services update-traffic "${SERVICE}" \
  --project="${PROJECT}" --region="${REGION}" \
  --to-revisions="${PREV}=100"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"

echo "==> Traffic now at ${PREV} on ${URL}"
echo "==> Post-rollback readyz"
curl -fsS "${URL}/readyz" && echo
