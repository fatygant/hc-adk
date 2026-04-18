# Changelog

## [Unreleased] — Voice Streaming + Identity-Preserving Photo Aging

### Dodano

- **SSE voice streaming (`POST /voice/chat-stream`)** — nowy router `jutra/api/voice.py` wystawia stream tokenów Gemini jako Server-Sent Events (`meta` / `delta` / `done` / `error`). LiveKit worker dostaje pierwszy token ~2 s szybciej niż na klasycznym `POST /users/{uid}/chat`, bo TTS może zacząć mówić zanim backend skończy całą turę. Auth: ten sam `MCP_BEARER_TOKEN` co MCP (żeby worker nie musiał znać dwóch sekretów).
- **`fast: bool` na chat** (REST + MCP) — `fast=True` wyłącza `thinking_budget` i tnie `max_output_tokens` do 400. Stream voice zawsze leci w trybie `fast`; REST wystawia flagę dla testów.
- **`jutra/services/profile_gaps.py`** — heurystyka liczy brakujące "sloty" persony (wartości, preferencje, RIASEC, relacje, plany, hobby, szkoła, kariera, lęki) i wstrzykuje je do system prompta `FutureSelf`, dzięki czemu agent sam dobiera, o co dopytać w emergent onboardingu.
- **Historia rozmowy w prompcie** — `memory.store.append_chat_turn` + `recent_chat_turns` trzymają ostatnie 8 tur w Firestore i wstrzykują do prompta `future_self.md`, więc agent widzi poprzednie wypowiedzi bez RAG.
- **`memory.store.get_context_notes` / `append_context_notes`** — `save_turn` zapisuje 0–3 krótkich obserwacji kontekstowych (styl życia, nastrój) po każdej turze i kolejne rozmowy je czytają.

### Zmienione

- **Imagen 3 w trybie subject customization** (`imagen-3.0-capability-001` + `SubjectReferenceImage` z `SUBJECT_TYPE_PERSON`). Poprzednia wersja generowała niemal kopię oryginału — teraz prompt wymusza widoczne zmiany (kurze łapki, zmarszczki nosowo-wargowe, ~5% siwych włosów na skroniach) bez utraty tożsamości. Usunięto `FACE_MESH` (zbyt sztywno przykuwał geometrię twarzy). Seed deterministyczny (`10_010`).
- **`chat_with_future_self_tool`** przyjmuje teraz `base_age: int | None` i `fast: bool = False`. `base_age` jednorazowo aktualizuje profil Firestore (np. gdy UI zna prawdziwy wiek ucznia), `fast` przekazywany przez LiveKit worker.
- **Test suite** 53 testy (poprzednio 56; usunięto testy horizonów/Erikson/Maturity, dodano `test_profile_gaps.py` i `test_save_turn.py`).

## Previous — Free-form Age Perspective + Single Aged Photo

### Zmienione

- **Koniec sztywnych horyzontów (5/10/20/30)**. Agent sam — na podstawie kontekstu rozmowy — dobiera, z jak wielkim dystansem czasowym odpowiada. Usunięto:
  - `jutra/personas/horizons.py`, `jutra/personas/maturity.py`, `jutra/personas/erikson.py` oraz `HorizonProfile`
  - `GET /horizons`, `GET /users/{uid}/persona/{delta}` → teraz `GET /users/{uid}/persona`
  - `POST /users/{uid}/chat/{horizon}` → teraz `POST /users/{uid}/chat`
  - `horizon` z `VoiceChatRequest` (SSE), z `participant_metadata` (LiveKit), z `MemoryItem` oraz z narzędzi MCP (`list_available_horizons` usunięte; `get_persona_snapshot`, `chat_with_future_self_tool` bez parametru `horizon`)
- **Zdjęcia: jedna wersja zamiast czterech**. `photo_aging.age_photo_once` generuje jedno zdjęcie "trochę starsze ja" (fixed +10 lat). Endpointy:
  - `GET /users/{uid}/photo/aged/image` (zamiast `.../{horizon}/image`)
  - `GET /users/{uid}/photo/status` zwraca pojedynczy obiekt `aged: { status, gcs_path }`
- **Frontend**: usunięty horizon picker; `PhotoUploadStep` jest jedno-kafelkowy; `view-controller` i `tile-view` wyświetlają jedno zdjęcie, a w widoku `chatOpen` foto + wizualizator są renderowane obok siebie (brak zakrycia).
- **Prompt `future_self.md`** wyraźnie instruuje, by nie ogłaszać różnicy wieku.

## Previous — Photo Aging Feature

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
