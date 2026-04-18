# Wdrożenie funkcji starzenia zdjęć

## Wymagania

- `gcloud` CLI zalogowane (`gcloud auth login`)
- Dostęp do projektu `jutra-493710`
- Sklonowane repozytoria `hc` i `hc-backend`

Sprawdź dostęp:
```bash
gcloud projects describe jutra-493710
```

---

## Krok 1 — Setup infrastruktury GCP (jednorazowo)

```bash
cd hc-backend
PROJECT=jutra-493710 bash scripts/setup-photo-feature.sh
```

Skrypt tworzy bucket GCS, ustawia uprawnienia IAM i aktualizuje zmienne Cloud Run. Zajmuje ~1 min.

---

## Krok 2 — Deploy backendu

```bash
cd hc-backend
bash scripts/deploy.sh
```

---

## Krok 3 — Deploy frontendu

```bash
cd hc

export LIVEKIT_URL=...
export LIVEKIT_API_KEY=...
export LIVEKIT_API_SECRET=...
export JUTRA_BACKEND_URL=...

bash scripts/deploy.sh
```

Wartości zmiennych znajdziesz w pliku `.env.local` lub w Cloud Run → jutra-web → Variables.

---

## Weryfikacja

Po deploy sprawdź status endpointu:
```bash
curl https://jutra-<PROJECT_NUMBER>.europe-west4.run.app/users/test-uid/photo/status
# Oczekiwana odpowiedź: {"overall_status":"none","aged":{}}
```

---

## Jeśli coś nie działa

**Błąd `403` przy upload obrazu do GCS:**
```bash
gsutil iam get gs://hc-user-photos
# sprawdź czy jutra-689@jutra-493710.iam.gserviceaccount.com ma storage.objectAdmin
```

**Błąd `aiplatform` przy generowaniu:**
```bash
gcloud projects get-iam-policy jutra-493710 \
  --flatten="bindings[].members" \
  --filter="bindings.members:jutra-689@jutra-493710.iam.gserviceaccount.com"
# sprawdź czy jest roles/aiplatform.user
```

**Zmienna `GCS_BUCKET` nie ustawiona w Cloud Run:**
```bash
gcloud run services describe jutra \
  --region=europe-west4 \
  --project=jutra-493710 \
  --format="value(spec.template.spec.containers[0].env)"
```
