# Changelog

## [Unreleased] — Photo Aging Feature

### Dodano

#### Backend (`hc-backend`)

- **`jutra/infra/gcs.py`** — nowy moduł Google Cloud Storage: `upload_bytes()` i `download_bytes()` z automatycznym ADC (Application Default Credentials)
- **`jutra/services/photo_aging.py`** — serwis starzenia zdjęć oparty na Vertex AI Imagen (`imagen-3.0-capability-001`); generuje 4 wersje (+5/+10/+20/+30 lat) równolegle przez `asyncio.gather`
- **`jutra/api/photo_routes.py`** — nowy router z 4 endpointami:
  - `POST /users/{uid}/photo/upload` — upload JPEG/PNG/WEBP (max 10 MB), zapis do GCS, start background task
  - `GET  /users/{uid}/photo/status` — stan przetwarzania: `none / processing / done / error` per horyzont
  - `GET  /users/{uid}/photo/{horizon}/image` — serwuje postarzone zdjęcie jako JPEG z GCS
  - `GET  /users/{uid}/photo/original/image` — serwuje oryginalne zdjęcie z GCS
- **`jutra/memory/store.py`** — nowe funkcje Firestore dla metadanych zdjęć: `save_photo_original`, `set_aged_photo_done`, `set_overall_photo_status`, `get_photo_meta`; zapis w polu `photos` dokumentu użytkownika z dot-notation update
- **`jutra/settings.py`** — nowe pola konfiguracyjne: `gcs_bucket` (default: `hc-user-photos`), `image_location` (default: `us-central1`)
- **`jutra/api/main.py`** — rejestracja `photo_router`
- **`pyproject.toml`** — dodano zależność `google-cloud-storage>=2.18.0`
- **`scripts/deploy.sh`** — dodano `GCS_BUCKET` i `IMAGE_LOCATION` do zmiennych Cloud Run
- **`scripts/setup-photo-feature.sh`** — nowy skrypt jednorazowej konfiguracji GCP: włączenie API, tworzenie bucketu, CORS, IAM dla Service Account, aktualizacja Cloud Run env vars
- **`PHOTO_FEATURE_DEPLOY.md`** — instrukcja wdrożenia dla agenta na innym komputerze

#### Frontend (`hc`)

- **`components/app/photo-upload-step.tsx`** — nowy komponent UI: wybór zdjęcia z galerii lub aparatu, podgląd, polling statusu co 3,5 s, siatka 4 postarnych wersji z podświetleniem aktywnego horyzontu, obsługa stanów (uploading / processing / done / error), przycisk zmiany zdjęcia
- **`components/app/jutra-prefs-context.tsx`** — dodano `photoUrls: Record<number, string>` i `setPhotoUrls` do kontekstu; `photoUrls` przechowuje URL proxy per horyzont
- **`components/app/pre-session-view.tsx`** — wpięcie `PhotoUploadStep` jako Opcja C w ekranie pre-session; `onPhotosReady` aktualizuje `photoUrls` w kontekście
- **`app/api/jutra/photo/upload/route.ts`** — proxy Next.js dla multipart upload
- **`app/api/jutra/photo/status/route.ts`** — proxy Next.js dla statusu
- **`app/api/jutra/photo/image/route.ts`** — proxy Next.js serwujące bajty JPEG z backendu (bez signed URLs — backend jako jedyny punkt dostępu do GCS)

### Architektura

```
Użytkownik → PhotoUploadStep → POST /api/jutra/photo/upload
                                    → backend: GCS save + BackgroundTask
                             ← { status: "processing" }

Polling co 3.5s → GET /api/jutra/photo/status
                       → Firestore: stan per horyzont

Wyświetlanie → <img src="/api/jutra/photo/image?uid=...&horizon=10">
                    → backend → GCS download → JPEG bytes
```

### Schemat Firestore (pole `photos` w `users/{uid}`)

```json
{
  "photos": {
    "original_gcs": "{uid}/original.jpg",
    "overall_status": "done",
    "aged": {
      "5":  { "gcs_path": "{uid}/aged_5.jpg",  "status": "done" },
      "10": { "gcs_path": "{uid}/aged_10.jpg", "status": "done" },
      "20": { "gcs_path": "{uid}/aged_20.jpg", "status": "done" },
      "30": { "gcs_path": "{uid}/aged_30.jpg", "status": "done" }
    },
    "uploaded_at": "2026-04-18T..."
  }
}
```

---

## Poprzednie zmiany (z git log)

### Jutra integration — pre-session flow + backend support
- Dodano pre-session onboarding z horizon pickerem i ingestion tekstu
- Aktualizacja zmiennych środowiskowych i konfiguracji agenta
- Obsługa `participant_metadata` (uid, horizon, display_name) w tokenie LiveKit

### Audio source
- Zmiany konfiguracji źródła audio

### Init
- Inicjalny backend Jutra: ADK + Gemini 3 + Firestore + MCP na Cloud Run
