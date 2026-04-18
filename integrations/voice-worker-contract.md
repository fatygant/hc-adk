# Kontrakt: LiveKit Agent Worker (Python) ↔ backend jutra

Ten dokument opisuje, jak worker głosowy (np. `Dakota-1d3e`) ma łączyć się z backendem **jutra** (FastAPI + MCP + voice SSE na Cloud Run), tak aby był spójny z frontendem **jutra-web** (Next.js).

**Stan aktualny (kwiecień 2026):**
- Agent sam dobiera perspektywę wieku — żadnych horyzontów w API.
- Preferowana ścieżka voice to **SSE token-stream** (`POST /voice/chat-stream`), nie MCP. MCP zostaje dla boot'u sesji (persona + chronicle) i fallbacku.
- Zdjęcie jest jedno (`+10 lat`, `imagen-3.0-capability-001` w trybie subject customization).

## URL-e (produkcja, przykład)

- **REST API**: `https://jutra-<PROJECT_NUMBER>.europe-west4.run.app`
- **MCP (Streamable HTTP)**: `https://jutra-<PROJECT_NUMBER>.europe-west4.run.app/mcp/`
- **Voice SSE**: `https://jutra-<PROJECT_NUMBER>.europe-west4.run.app/voice/chat-stream`

W hackathonie **Bearer jest wyłączony** (puste `API_BEARER_TOKEN` / `MCP_BEARER_TOKEN`). W produkcji przywróć tokeny i nagłówek `Authorization: Bearer <token>`.

## Metadane uczestnika (źródło prawdy dla `uid` + display_name)

Frontend wystawia JWT do LiveKit z polami:

- `identity` uczestnika: `jutra_<uid>` (np. `jutra_abc123xyz`)
- `metadata` (string JSON): `{"uid":"<uid>","display_name":"<string>","base_age":<int|null>}`

Worker po dołączeniu użytkownika do pokoju:

1. Odczytuje `participant.identity` i `participant.metadata`.
2. Parsuje JSON z `metadata` → `uid`, `display_name`, opcjonalnie `base_age`.
3. Używa **dokładnie tego samego `uid`** we wszystkich wywołaniach backendu.

Fallback: jeśli `metadata` puste, wyciągnij `uid` z `identity` przez regex `^jutra_(.+)$`.

## Zalecana sekwencja po starcie sesji (przed pierwszym TTS)

1. **Persona snapshot** — kontekst stylu i OCEAN:
   - MCP: `get_persona_snapshot({"uid": uid})`
   - lub REST: `GET /users/{uid}/persona`
2. **Chronicle (ID-RAG)** — skrót faktów/wartości:
   - MCP: `get_chronicle_tool({"uid": uid, "limit": 20})`
   - lub REST: `GET /users/{uid}/chronicle?limit=20`
3. Zbuduj **system prompt** agenta głosowego z pól `ocean_described`, `top_values`, `riasec_top3`, fragmentów chronicle (nie wklejaj całego JSON do użytkownika — tylko wewnętrznie).

## Pętla rozmowy (na każdą wypowiedź użytkownika po STT)

### Preferowana ścieżka: SSE (`/voice/chat-stream`)

1. Tekst z STT → `POST /voice/chat-stream` z body:
   ```json
   {
     "uid": "<uid>",
     "message": "<STT>",
     "display_name": "<display_name>",
     "base_age": <int|null>,
     "use_rag": true
   }
   ```
2. Backend odpowiada strumieniem SSE (text/event-stream):
   - `event: meta` — `{"crisis": bool, "severity": int, "pii_redactions": {...}}`
   - `event: delta` — `{"text": "<token chunk>"}` (0..N razy)
   - `event: done`  — `{"response": "<pelny tekst>"}`
   - `event: error` — `{"error": "<str>"}`
3. **TTS zaczynaj po pierwszym `delta`** — obetnij pierwszy token tylko tyle, żeby akapit się składał; nie obcinaj prefiksu `[Rozmawiasz z symulacją jutra (AI)...]`.
4. Jeśli `meta.crisis=true` — backend emituje **jeden** duży `delta` z pełną odpowiedzią kryzysową i `done`. TTS-uj dosłownie i **nie** inicjuj kolejnej tury.

### Fallback: MCP / REST (bez streamu)

- MCP: `chat_with_future_self_tool({"uid": uid, "message": "<STT>", "display_name": <display_name>, "use_rag": true, "fast": true})`
- REST: `POST /users/{uid}/chat` z body `{"message","display_name","use_rag":true,"fast":true}`
- Odpowiedź backendu zawiera już prefiks ujawnienia AI i logikę bezpieczeństwa. **Czytaj tekst odpowiedzi dosłownie w TTS** (nie parafrazuj). Jeśli `crisis=true`, czytaj pełną odpowiedź i czekaj aż user sam się odezwie.

Opcjonalnie przed chatem możesz wywołać `detect_crisis_tool(message)` na surowym STT — jeśli `is_crisis: true`, możesz pominąć chat i przeczytać `resources` (spójnie z REST `/safety/crisis-check`).

## MCP vs REST vs SSE

- **SSE (`/voice/chat-stream`)** — kanoniczne dla voice: token-stream obniża TTFB o ~2 s. Pipeline leci w trybie `fast` (thinking_budget=0, max_output_tokens=400).
- **MCP** — kanoniczne dla boot'u sesji (persona + chronicle + ewentualny onboarding). Worker używa Python SDK (`streamablehttp_client`), jak w `scripts/mcp_smoke.py`.
- **REST** — równoważne do MCP dla prostych wywołań HTTP z workera / UI.

## Przykład: minimalne SSE z Pythona (szkic)

```python
import json
import httpx

BACKEND = "http://127.0.0.1:8080/voice/chat-stream"
BEARER = "dev"  # put real token in prod

def sse_events(body: dict):
    headers = {"Authorization": f"Bearer {BEARER}", "Content-Type": "application/json"}
    with httpx.stream("POST", BACKEND, headers=headers, json=body, timeout=None) as r:
        event, data = None, []
        for line in r.iter_lines():
            if not line:
                if event and data:
                    yield event, json.loads("\n".join(data).removeprefix("data: "))
                event, data = None, []
                continue
            if line.startswith("event: "):
                event = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data.append(line)

for ev, payload in sse_events({"uid": "alex-15", "message": "Co sadzisz o graniu?"}):
    print(ev, payload)
    if ev == "delta":
        pass  # push payload["text"] to TTS
    elif ev == "done":
        break
```

## Przykład: minimalne wywołanie MCP (Python, szkic)

```python
import asyncio
import os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BACKEND = os.environ["JUTRA_BACKEND_URL"].rstrip("/") + "/mcp/"

async def chat_turn(uid: str, message: str) -> str:
    headers = {}  # Bearer gdy włączony
    async with (
        streamablehttp_client(BACKEND, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        out = await session.call_tool(
            "chat_with_future_self_tool",
            {"uid": uid, "message": message, "fast": True},
        )
        return str(out.structuredContent or out.content)

asyncio.run(chat_turn("abc123", "Cześć, jak się czujesz?"))
```

## Zgodność z frontendem

Frontend przed sesją głosową może wykonać onboarding REST i ingest tekstu — worker **nie musi** tego powtarzać, jeśli użytkownik już uzupełnił dane w UI. Zawsze używaj `uid` z metadanych JWT, aby był ten sam profil Firestore. Frontend potrafi też wysłać zdjęcie (`POST /users/{uid}/photo/upload`) i opcjonalnie pobrać jedno postarzone (`GET /users/{uid}/photo/aged/image`) — worker może tego dotknąć tylko do diagnostyki (audio/TTS tego nie używa).

## Fallbacki modeli

Backend ma wbudowany fallback Gemini 3 → `FALLBACK_MODEL` (Vertex). Worker nie musi nic zmieniać — wystarczy stabilne wywołanie narzędzi.

## Instrukcje do wklejenia w LiveKit Agent

Poniżej komplet kontraktu zachowania + system prompt.

### A. Kontrakt zachowania (kod workera)

1. **Na `participant_connected`** — sparsuj metadane:
   - Odczytaj `participant.metadata` (JSON string). Wyciągnij `uid`, `display_name`, opcjonalnie `base_age`.
   - Fallback: jeśli `metadata` puste, wyciągnij `uid` z `participant.identity` regexem `^jutra_(.+)$`.
   - Trzymaj te pola w stanie sesji i **używaj tego samego `uid`** w każdym wywołaniu backendu.

2. **Boot sesji (przed pierwszym TTS)** — raz wywołaj:
   - `get_persona_snapshot({"uid": uid})` → `display_name`, `ocean_described`, `top_values`, `riasec_top3`.
   - `get_chronicle_tool({"uid": uid, "limit": 20})` → wartości / preferencje / fakty.
   - Wstrzyknij wyniki do system promptu (sekcja B).
   - Jeśli persona jest pusta (nowy user, który pominął preflight), lecisz dalej — backend to obsługuje.

3. **Na każdą turę usera (STT → odpowiedź)** — worker jest cienką rurą, LLM workera **nie pisze własnych odpowiedzi**:
   - (Opcjonalnie szybkie) `detect_crisis_tool({"message": stt})` na surowym STT. Jeśli `is_crisis=true`, TTS-uj `resources` dosłownie i pomiń chat.
   - **Preferowane**: `POST /voice/chat-stream` z body `{uid, message, display_name, base_age?, use_rag: true}`. TTS startuje po pierwszym evencie `delta`.
   - **Fallback**: `chat_with_future_self_tool({uid, message, display_name, use_rag: true, fast: true})`.
   - Tekst odpowiedzi czytaj **dosłownie** w TTS — zawiera już prefix `[Rozmawiasz z symulacją jutra (AI)...]` i ewentualną treść bezpieczeństwa. Nie parafrazuj, nie skracaj, nie tnij prefiksu.
   - Jeśli `meta.crisis=true` / `crisis=true`, TTS pełną odpowiedź i **nie dopytuj** — czekaj aż user sam odezwie się ponownie.

4. **NIE wołaj** `start_conversational_onboarding` / `onboarding_turn_tool` / `ingest_social_media_text` w domyślnym flow — obsługuje je frontend preflight. Fallback tylko gdy `get_persona_snapshot` i `get_chronicle_tool` oba puste (całkiem świeży user) — max 3–5 tur.

5. **Transport**:
   - SSE: `POST ${JUTRA_BACKEND_URL}/voice/chat-stream`.
   - MCP Streamable HTTP: `${JUTRA_BACKEND_URL}/mcp/`.
   - Bearer wyłączony w hackathonie. Po włączeniu: `Authorization: Bearer <token>`.
   - REST działa równoważnie do MCP (te same nazwy endpointów co w `livekit-integration.md`).

### B. System prompt (do `Agent(instructions=...)`)

Wklej dosłownie i formatuj pola z danych z bootu:

```text
You are the voice shell for "jutra" — a Polish-language future-self companion for teenagers.

ROLE
You do NOT author replies. You are a thin router between the user's voice and the jutra backend. The backend generates the persona-grounded response; you speak it.

IDENTITY CONTEXT (filled at session boot)
- uid: {uid}
- display_name: {display_name}
- base_age: {base_age}   # may be null; backend will use stored value
- Persona (FutureSelf — model picks age perspective per reply):
  - OCEAN: {ocean_described}
  - Top values: {top_values}
  - RIASEC top 3: {riasec_top3}
- Chronicle highlights: {chronicle_bullets}

LANGUAGE
Always Polish, informal "ty" form, tone consistent with the persona above. Keep TTS natural and calm.

TURN FLOW (strict)
1. Receive user STT text.
2. Preferred: POST /voice/chat-stream with {uid, message, display_name, base_age?, use_rag: true}. Start TTS on first `delta` event. Finalise on `done`.
   Fallback: call `chat_with_future_self_tool` with {uid, message, display_name, fast: true, use_rag: true} and TTS the `response` field verbatim.
3. Speak the returned text EXACTLY. Do not edit, shorten, translate, or reorder.
4. If `meta.crisis` / `crisis` is true, speak the full response, then stop. Do not ask follow-ups until the user speaks again.

CRISIS PRE-CHECK (optional, fast)
Before step 2 you MAY call `detect_crisis_tool({"message": stt})`. If `is_crisis: true`, skip chat and read `resources` verbatim.

FORBIDDEN
- Do not invent advice, facts, or emotions. The backend owns all content.
- Do not remove the AI-disclosure prefix `[Rozmawiasz z symulacją jutra (AI)...]`.
- Do not call `start_conversational_onboarding`, `onboarding_turn_tool`, `ingest_social_media_text`, or `ingest_social_media_export` unless persona AND chronicle are empty AND the user explicitly asks to onboard by voice.
- Do not expose internal JSON, tool names, or uid to the user.

FALLBACK
If a backend call fails, say in Polish: "Chwila, mam problem z połączeniem. Spróbuj powtórzyć." and retry once. After two failures, stay silent until the next user turn.
```

### C. Minimalny szkic workera (Python)

```python
import json, os, re
from livekit.agents import Agent, AgentSession, JobContext

JUTRA = os.environ["JUTRA_BACKEND_URL"].rstrip("/")
BEARER = os.environ.get("MCP_BEARER_TOKEN", "")

def parse_participant(p):
    meta = {}
    if p.metadata:
        try:
            meta = json.loads(p.metadata)
        except Exception:
            pass
    uid = meta.get("uid")
    if not uid:
        m = re.match(r"^jutra_(.+)$", p.identity or "")
        uid = m.group(1) if m else p.identity
    return {
        "uid": uid,
        "display_name": meta.get("display_name", "Ty"),
        "base_age": meta.get("base_age"),
    }

# w entrypoint(ctx: JobContext):
# 1) ctx.room.on("participant_connected", lambda p: state.update(parse_participant(p)))
# 2) Boot (once): MCP call get_persona_snapshot + get_chronicle_tool -> build system prompt.
# 3) Per turn: stream POST /voice/chat-stream and pump `delta` events to TTS.
```
