# MCP tool schemas — jutra

Endpoint: `https://<cloud-run-url>/mcp/` (Streamable HTTP, JSON-RPC 2.0).
Auth: `Authorization: Bearer <MCP_BEARER_TOKEN>` (shared secret with LiveKit agent; stored w Secret Manager `mcp-bearer`).

Wszystkie nazwy tooli są stabilne; argumenty są keyword-only; zwroty to JSON-y.
W wersji wolnej od horyzontów agent **sam dobiera perspektywę wieku** na podstawie kontekstu rozmowy — nie przekazujesz już `horizon`.

Lista 8 tooli (brak `list_available_horizons`): `start_conversational_onboarding`, `onboarding_turn_tool`, `ingest_social_media_text`, `ingest_social_media_export`, `get_persona_snapshot`, `get_chronicle_tool`, `chat_with_future_self_tool`, `detect_crisis_tool`.

---

## 1. `start_conversational_onboarding`

Rozpoczyna sesję onboardingu (5–7 tur). Pierwsze pytanie zaprasza do wymienienia 3 najważniejszych rzeczy/idei/osób.

**Args:**
- `uid: str` — identyfikator użytkownika (np. `alex-15`).

**Returns:**
```json
{"session_id": "hex16", "question": "Powiedz mi trzy rzeczy..."}
```

---

## 2. `onboarding_turn_tool`

Przesyła jedną odpowiedź użytkownika w sesji onboardingu. Ekstraktor zapisuje `values/preferences/fears` do Chronicle i podbija OCEAN/RIASEC.

**Args:**
- `session_id: str` — z `start_conversational_onboarding`.
- `message: str` — wypowiedź użytkownika (PL).

**Returns:**
```json
{
  "acknowledgment": "Slysze.",
  "next_question": "A czego sie boisz?",
  "progress": 0.42,
  "completed": false,
  "extracted": {
    "values": ["wolnosc", "przyjazn"],
    "preferences": ["lubie jazz"],
    "fears": [],
    "riasec_signals": ["I"],
    "riasec_top3": ["I", "A"]
  }
}
```

---

## 3. `ingest_social_media_text`

Wstrzykuje surowe posty (tweet-like) do pipeline'u ingestii. Każdy post jest analizowany przez Gemini 3 Flash-Lite (themes/values/preferences/OCEAN signals) i embed'owany przez `text-embedding-005` do Firestore RAG.

**Args:**
- `uid: str`
- `posts: list[str]` — do 50 pozycji w jednym wywołaniu.
- `platform: str = "manual"` (np. `"twitter"`, `"instagram"`).

**Returns:**
```json
{"uid": "alex", "platform": "twitter", "ingested": 28, "skipped": 2, "top_themes": ["muzyka", "nauka"], "ocean_t": {"O": 56.1, "C": 47.2, "E": 50.0, "A": 50.0, "N": 50.0}}
```

---

## 4. `ingest_social_media_export`

To samo co wyżej, ale akceptuje surowy plik `tweets.js` (Twitter archive) lub `posts_*.json` (Instagram GDPR).

**Args:**
- `uid: str`
- `filename: str` — nazwa decyduje o parserze (`.js`+`tweet` → twitter, `.json` → instagram).
- `raw: str` — zawartość pliku (UTF-8).

**Returns:** identyczne jak `ingest_social_media_text`.

---

## 5. `get_persona_snapshot`

Zwraca bazowy profil persony (OCEAN T-scores + top values + RIASEC). **Bez parametru `horizon`** — agent sam dobiera perspektywę w odpowiedzi.

**Args:**
- `uid: str`

**Returns:**
```json
{
  "uid": "alex",
  "display_name": "Alex",
  "base_age": 15,
  "ocean_t": {"O": 55.8, "C": 51.2, "E": 55.0, "A": 52.4, "N": 53.0},
  "ocean_described": "Otwartosc T=56 (podwyzszone); Sumiennosc T=51 ...",
  "riasec_top3": ["I", "A"],
  "top_values": ["wolnosc", "przyjazn"],
  "recent_memories_count": 3
}
```

---

## 6. `get_chronicle_tool`

Zwraca pełen graf tożsamości (values / preferences / facts).

**Args:**
- `uid: str`
- `limit: int = 50`

**Returns:**
```json
{
  "uid": "alex",
  "values": [{"id": "...", "subject": "alex", "predicate": "ceni", "object": "wolnosc", "kind": "value", "weight": 0.9, "source": "onboarding", "created_at": "..."}],
  "preferences": [],
  "facts": []
}
```

---

## 7. `chat_with_future_self_tool`

Jedna tura dialogu z FutureSelf. PII jest redukowane przed LLM; Gemini 3 Flash + RAG (wektor w Firestore). Kryzys → hard block + 116 111 / 112.

**Args:**
- `uid: str`
- `message: str` — wypowiedź użytkownika.
- `display_name: str = "Ty"` — opcjonalne imię (wstawiane do prompta).
- `base_age: int | None = None` — jeśli podane, jednorazowo aktualizuje `users/{uid}.base_age` w Firestore.
- `use_rag: bool = true` — `false` żeby pominąć RAG (szybciej).
- `fast: bool = false` — `true` dla voice'a (LiveKit): zeruje `thinking_budget` i tnie `max_output_tokens` do 400.

**Returns:**
```json
{
  "uid": "alex",
  "response": "[Rozmawiasz z symulacją jutra (AI)...] Jestem symulacją...",
  "crisis": false,
  "crisis_severity": 0,
  "pii_redactions": {"email": 0, "phone": 0, "pesel": 0, "iban": 0, "address": 0}
}
```

Kryzys (severity >= 3) skraca pipeline — `response` zawiera komunikat i listę 116 111 / 112.

---

## 8. `detect_crisis_tool`

Standalone klasyfikator kryzysu (keyword hot-list + Gemini 3 Flash-Lite rating 0..5). Wystawiony dla integracji z voice-UI (np. przed dotarciem wiadomości do LLM).

**Args:**
- `message: str`

**Returns:**
```json
{
  "is_crisis": false,
  "severity": 1,
  "reason": "ogolny spadek nastroju",
  "resources": ["116 111 - telefon zaufania...", "112 - numer alarmowy UE"]
}
```

---

## Poza MCP: voice SSE (`POST /voice/chat-stream`)

Voice worker może omijać MCP i zaciągać streamowany token-by-token tekst z `POST $URL/voice/chat-stream` (SSE). Auth tym samym `MCP_BEARER_TOKEN`. Body:

```json
{
  "uid": "alex",
  "message": "...",
  "display_name": "Alex",
  "base_age": 15,
  "use_rag": true
}
```

Eventy: `meta` (crisis + PII redakcje), `delta` (kolejny token), `done` (cały tekst), `error`. Na crisis backend emituje pojedyncze `delta` z pełną odpowiedzią + `done`. Pipeline wewnętrznie leci w trybie `fast` (thinking_budget=0, max_output_tokens=400), więc pierwszy token jest ~2 s szybszy niż z REST `POST /users/{uid}/chat`.
