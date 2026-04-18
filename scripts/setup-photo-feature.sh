#!/usr/bin/env bash
# =============================================================================
# setup-photo-feature.sh
#
# Jednorazowy skrypt konfiguracji infrastruktury GCP dla funkcji starzenia zdjęć.
# Uruchom na dowolnym komputerze z zalogowanym gcloud CLI.
#
# Wymaga:
#   gcloud CLI zalogowane i z poprawnym projektem
#   gsutil (wchodzi w skład gcloud SDK)
#
# Użycie:
#   PROJECT=jutra-493710 bash scripts/setup-photo-feature.sh
# =============================================================================

set -euo pipefail

PROJECT="${PROJECT:-jutra-493710}"
REGION="${REGION:-europe-west4}"
BUCKET="${BUCKET:-hc-user-photos}"
SA="${SA:-jutra-689@${PROJECT}.iam.gserviceaccount.com}"

echo ""
echo "============================================================"
echo "  HC Photo Feature — GCP Infrastructure Setup"
echo "  Project : ${PROJECT}"
echo "  Region  : ${REGION}"
echo "  Bucket  : ${BUCKET}"
echo "  SA      : ${SA}"
echo "============================================================"
echo ""

# ── 1. Wymagane API ──────────────────────────────────────────────────────────
echo "==> [1/6] Włączanie wymaganych API..."
gcloud services enable \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT}"
echo "    OK"

# ── 2. GCS Bucket ────────────────────────────────────────────────────────────
echo "==> [2/6] Tworzenie bucketu GCS: gs://${BUCKET}"
if gsutil ls -p "${PROJECT}" "gs://${BUCKET}" >/dev/null 2>&1; then
  echo "    Bucket już istnieje — pomijam tworzenie"
else
  gsutil mb \
    -p "${PROJECT}" \
    -l "${REGION}" \
    -b on \
    "gs://${BUCKET}"
  echo "    Bucket utworzony"
fi

# ── 3. CORS dla bucketu (Next.js może serwować obrazy przez proxy, ale na wszelki wypadek) ──
echo "==> [3/6] Konfiguracja CORS bucketu..."
cat > /tmp/gcs_cors.json << 'CORS_EOF'
[
  {
    "origin": ["*"],
    "method": ["GET"],
    "responseHeader": ["Content-Type", "Cache-Control"],
    "maxAgeSeconds": 3600
  }
]
CORS_EOF
gsutil cors set /tmp/gcs_cors.json "gs://${BUCKET}"
rm /tmp/gcs_cors.json
echo "    CORS ustawiony"

# ── 4. IAM — Service Account → Storage ───────────────────────────────────────
echo "==> [4/6] Przyznawanie SA dostępu do bucketu..."

# Pełny dostęp do obiektów w buckecie (upload + download)
gsutil iam ch \
  "serviceAccount:${SA}:roles/storage.objectAdmin" \
  "gs://${BUCKET}"
echo "    storage.objectAdmin → gs://${BUCKET}"

# ── 5. IAM — Service Account → Vertex AI Imagen ──────────────────────────────
echo "==> [5/6] Przyznawanie SA dostępu do Vertex AI..."

gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA}" \
  --role="roles/aiplatform.user" \
  --condition=None \
  --quiet
echo "    aiplatform.user → ${SA}"

# ── 6. Aktualizacja Cloud Run — dodanie zmiennych środowiskowych ─────────────
echo "==> [6/6] Aktualizacja zmiennych env Cloud Run service: jutra"
gcloud run services update jutra \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --update-env-vars="GCS_BUCKET=${BUCKET}" \
  --update-env-vars="IMAGE_LOCATION=us-central1" \
  --quiet
echo "    GCS_BUCKET=${BUCKET}"
echo "    IMAGE_LOCATION=us-central1"

echo ""
echo "============================================================"
echo "  Konfiguracja zakończona pomyślnie!"
echo ""
echo "  Następny krok: re-deploy backendu:"
echo "    cd hc-backend && bash scripts/deploy.sh"
echo ""
echo "  Następny krok: re-deploy frontendu:"
echo "    cd hc && bash scripts/deploy.sh"
echo "============================================================"
