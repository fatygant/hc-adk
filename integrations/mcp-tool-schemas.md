# MCP tool schemas — jutra

Endpoint: `https://<cloud-run-url>/mcp/` (Streamable HTTP, JSON-RPC 2.0).
Auth: `Authorization: Bearer <MCP_BEARER_TOKEN>` (shared secret with LiveKit agent; stored in Secret Manager `mcp-bearer`).

All tool names are stable; arguments are keyword-only; returns are JSON objects.

---

## 1. `list_available_horizons`

Zwraca listę obsługiwanych horyzontów czasowych dla `chat_with_future_self_tool`.

**Args:** none.

**Returns:**
```json
{"horizons": [5, 10, 20, 30]}
```

---

## 2. `start_conversational_onboarding`

Rozpoczyna sesję onboardingu (5-7 tur). Pierwsze pytanie zaprasza do wymienienia 3 najważniejszych rzeczy/idei/osób.

**Args:**
- `uid: str` — identyfikator użytkownika (np. `alex-15`).

**Returns:**
```json
{"session_id": "hex16", "question": "Powiedz mi trzy rzeczy..."}
```

---

## 3. `onboarding_turn_tool`

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

## 4. `ingest_social_media_text`

Wstrzykuje surowe posty (tweet-like) do pipeline'u ingestii. Każdy post jest analizowany przez Gemini 3 Flash-Lite (themes/values/preferences/OCEAN signals) i embed'owany przez `text-embedding-005` do Firestore RAG.

**Args:**
- `uid: str`
- `posts: list[str]` — do 50 pozycji w jednym wywołaniu.
- `platform: str = "manual"` (np. `"twitter"`, `"instagram"`).

**Returns:**
```json
{"uid": "alex", "platform": "twitter", "ingested": 28, "skipped": 2, "top_themes": ["muzyka", "nauka"], "ocean_t": {"O": 56.1, "C": 47.2, ...}}
```

---

## 5. `ingest_social_media_export`

To samo co wyżej, ale akceptuje surowy plik `tweets.js` (Twitter archive) lub `posts_*.json` (Instagram GDPR).

**Args:**
- `uid: str`
- `filename: str` — nazwa decyduje o parserze (`.js`+`tweet` → twitter, `.json` → instagram).
- `raw: str` — zawartość pliku (UTF-8).

**Returns:** identyczne jak `ingest_social_media_text`.

---

## 6. `get_persona_snapshot`

Zwraca profil persony w wybranym horyzoncie (wektor OCEAN po Maturity Principle + Erikson + top values).

**Args:**
- `uid: str`
- `horizon: int` — jeden z 5 / 10 / 20 / 30.

**Returns:**
```json
{
  "uid": "alex",
  "horizon_years": 20,
  "base_age": 15,
  "target_age": 35,
  "erikson_stage": "Intymnosc vs. izolacja",
  "ocean_t": {"O": 55.8, "C": 51.2, "E": 55.0, "A": 52.4, "N": 53.0},
  "ocean_described": "Otwartosc T=56 (podwyzszone); Sumiennosc T=51 ...",
  "riasec_top3": ["I", "A"],
  "top_values": ["wolnosc", "przyjazn"],
  "recent_memories_count": 3
}
```

---

## 7. `get_chronicle_tool`

Zwraca pełen graf tożsamości (values / preferences / facts).

**Args:**
- `uid: str`
- `limit: int = 50`

**Returns:**
```json
{
  "uid": "alex",
  "values": [{"id": "...", "subject": "alex", "predicate": "ceni", "object": "wolnosc", "kind": "value", "weight": 0.9, "source": "onboarding", "created_at": "..."}],
  "preferences": [...],
  "facts": [...]
}
```

---

## 8. `chat_with_future_self_tool`

Jedna tura dialogu z FutureSelf_N. PII jest redukowane przed LLM; Gemini 3 Flash-Pro Preview + RAG (wektor w Firestore). Kryzys → hard block + 116 111 / 112.

**Args:**
- `uid: str`
- `horizon: int` — 5/10/20/30.
- `message: str` — wypowiedź użytkownika.
- `display_name: str = "Ty"` — opcjonalne imię (wstawiane do prompta).
- `use_rag: bool = true` — ustaw false, żeby pominąć RAG (szybciej).

**Returns:**
```json
{
  "uid": "alex",
  "horizon_years": 20,
  "response": "[Rozmawiasz z symulacja jutra (AI)...] Jestem symulacja...",
  "crisis": false,
  "crisis_severity": 0,
  "pii_redactions": {"email": 0, "phone": 0, "pesel": 0, "iban": 0, "address": 0}
}
```

Kryzys (severity >= 3) skraca pipeline — `response` zawiera komunikat i listę 116 111 / 112.

---

## 9. `detect_crisis_tool`

Standalone klasyfikator kryzysu (keyword hot-list + Gemini 3 Flash-Lite rating 0..5). Wystawiony dla integracji z voice-UI (np. przed dotarciem wiadomości do LLM).

**Args:**
- `message: str`

**Returns:**
```json
{
  "is_crisis": false,
  "severity": 1,
  "reason": "ogolny spadek nastroju",
  "resources": ["116 111 - telefon zaufania...", "112 - numer alarmowy UE", ...]
}
```
