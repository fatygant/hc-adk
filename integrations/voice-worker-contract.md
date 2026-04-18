# Kontrakt: LiveKit Agent Worker (Python) ↔ backend jutra

Ten dokument opisuje, jak worker głosowy (np. `Dakota-1d3e`) ma łączyć się z backendem **jutra** (FastAPI + MCP na Cloud Run), tak aby był spójny z frontendem **jutra-web** (Next.js).

## URL-e (produkcja, przykład)

- **REST API**: `https://jutra-<PROJECT_NUMBER>.europe-west4.run.app`
- **MCP (Streamable HTTP)**: `https://jutra-<PROJECT_NUMBER>.europe-west4.run.app/mcp/`

W hackathonie **Bearer jest wyłączony** (puste `API_BEARER_TOKEN` / `MCP_BEARER_TOKEN`). W produkcji przywróć tokeny i nagłówek `Authorization: Bearer <token>`.

## Metadane uczestnika (źródło prawdy dla `uid` + horyzontu)

Frontend wystawia JWT do LiveKit z polami:

- `identity` uczestnika: `jutra_<uid>` (np. `jutra_abc123xyz`)
- `metadata` (string JSON):  
  `{"uid":"<uid>","horizon":<5|10|20|30>,"display_name":"<string>"}`

Worker po dołączeniu użytkownika do pokoju powinien:

1. Odczytać `participant.identity` i/lub `participant.metadata`.
2. Sparsować JSON z `metadata` i wyciągnąć `uid`, `horizon`, `display_name`.
3. Używać **dokładnie tego samego `uid`** we wszystkich wywołaniach narzędzi i REST względem backendu.

Jeśli `metadata` jest puste, fallback: wyciągnij `uid` z `identity` przez regex `^jutra_(.+)$`.

## Zalecana sekwencja po starcie sesji (przed pierwszym TTS)

1. **Persona snapshot** — kontekst stylu i OCEAN dla wybranego horyzontu:
   - MCP: `get_persona_snapshot` z argumentami `{ "uid", "horizon": horizon }`  
   - lub REST: `GET /users/{uid}/persona/{horizon}`
2. **Chronicle (ID-RAG)** — skrót faktów/wartości:
   - MCP: `get_chronicle_tool` z `{ "uid", "limit": 20 }`  
   - lub REST: `GET /users/{uid}/chronicle?limit=20`
3. Zbuduj **system prompt** agenta głosowego z pól `ocean_described`, `erikson_stage`, `top_values`, fragmentów chronicle (nie wklejaj całego JSON do użytkownika — tylko wewnętrznie).

## Pętla rozmowy (na każdą wypowiedź użytkownika po STT)

1. Tekst z STT → **jedno** wywołanie:
   - MCP: `chat_with_future_self_tool` z `{ "uid", "horizon", "message": "<STT>" }`
   - lub REST: `POST /users/{uid}/chat/{horizon}` z body `{ "message", "display_name", "use_rag": true }`
2. Odpowiedź backendu zawiera już prefiks ujawnienia AI i logikę bezpieczeństwa. **Czytaj tekst odpowiedzi dosłownie w TTS** (nie parafrazuj), chyba że pole `crisis` / `is_crisis` wymaga odczytu zasobów — wtedy też pierwszeństwo ma treść z backendu.
3. Opcjonalnie przed chatem: `detect_crisis_tool` na surowym tekście STT — jeśli `is_crisis: true`, możesz **pominąć** `chat_with_future_self` i przeczytać `resources` / komunikat bezpieczeństwa z backendu (spójnie z REST `/safety/crisis-check`).

## MCP vs REST

- **MCP** jest kanoniczne dla agentów (narzędzia są już zdefiniowane w backendzie). Worker może użyć klienta Streamable HTTP (`mcp` Python SDK), jak w `scripts/mcp_smoke.py`.
- **REST** jest równoważne dla prostych wywołań HTTP z workera.

## Przykład: minimalne wywołanie MCP (Python, szkic)

```python
import asyncio
import os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BACKEND = os.environ["JUTRA_BACKEND_URL"].rstrip("/") + "/mcp/"

async def chat_turn(uid: str, horizon: int, message: str) -> str:
    headers = {}  # Bearer gdy włączony
    async with (
        streamablehttp_client(BACKEND, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        out = await session.call_tool(
            "chat_with_future_self_tool",
            {"uid": uid, "horizon": horizon, "message": message},
        )
        # Zwróć tekst z structuredContent / content wg waszego parsera
        return str(out.structuredContent or out.content)

asyncio.run(chat_turn("abc123", 20, "Cześć, jak się czujesz za 20 lat?"))
```

## Zgodność z frontendem

Frontend przed sesją głosową może wykonać onboarding REST i ingest tekstu — worker **nie musi** tego powtarzać, jeśli użytkownik już uzupełnił dane w UI. Zawsze używaj `uid` z metadanych JWT, aby był ten sam profil Firestore.

## Fallbacki modeli

Backend ma wbudowany fallback Gemini 3 → `FALLBACK_MODEL` (Vertex). Worker nie musi nic zmieniać — wystarczy stabilne wywołanie narzędzi.

## Instrukcje do wklejenia w LiveKit Agent

Poniżej komplet kontraktu zachowania + system prompt, który kolega ma zaimplementować w workerze `Dakota-1d3e`.

### A. Kontrakt zachowania (kod workera)

1. **Na `participant_connected`** — sparsuj metadane:
   - Odczytaj `participant.metadata` (JSON string). Wyciągnij `uid`, `horizon`, `display_name`.
   - Fallback: jeśli `metadata` puste, wyciągnij `uid` z `participant.identity` regexem `^jutra_(.+)$`.
   - Trzymaj te pola w stanie sesji i **używaj tego samego `uid`** w każdym wywołaniu backendu.

2. **Boot sesji (przed pierwszym TTS)** — raz wywołaj:
   - `get_persona_snapshot(uid, horizon)` → `ocean_described`, `erikson_stage`, `top_values`, `writing_style`.
   - `get_chronicle_tool(uid, limit=20)` → wartości / preferencje / fakty.
   - Wstrzyknij wyniki do system promptu (sekcja B).
   - Jeśli persona jest pusta (nowy user, który pominął preflight), lecisz dalej — backend to obsługuje.

3. **Na każdą turę usera (STT → odpowiedź)** — worker jest cienką rurą, LLM workera **nie pisze własnych odpowiedzi**:
   - (Opcjonalnie szybkie) `detect_crisis_tool(message)` na surowym STT. Jeśli `is_crisis=true`, TTS-uj `resources` dosłownie i pomiń chat.
   - `chat_with_future_self_tool(uid, horizon, message=<STT>, display_name=<display_name>, use_rag=true)`.
   - Zwrócone pole `response` czytaj **dosłownie** w TTS — zawiera już prefix `[Rozmawiasz z symulacją jutra (AI)...]` i ewentualną treść bezpieczeństwa. Nie parafrazuj, nie skracaj, nie tnij prefiksu.
   - Jeśli wynik ma `crisis=true`, TTS pełną odpowiedź i **nie dopytuj** — czekaj aż user sam odezwie się ponownie.

4. **Zmiana horyzontu w trakcie sesji** (gdy UI to wyśle data-messagem): ponów `get_persona_snapshot(uid, new_horizon)` i zaktualizuj prompt.

5. **NIE wołaj** `start_conversational_onboarding` / `onboarding_turn_tool` / `ingest_social_media_text` w domyślnym flow — obsługuje je frontend preflight. Fallback tylko gdy `get_persona_snapshot` i `get_chronicle_tool` oba puste (całkiem świeży user) — max 3–5 tur.

6. **Transport**:
   - MCP Streamable HTTP: `${JUTRA_BACKEND_URL}/mcp/`.
   - Bearer wyłączony w hackathonie. Po włączeniu: `Authorization: Bearer <token>`.
   - REST działa równoważnie (te same nazwy tooli = endpointy REST w `livekit-integration.md`).

### B. System prompt (do `Agent(instructions=...)`)

Wklej dosłownie i formatuj pola z danych z bootu:

```text
You are the voice shell for "jutra" — a Polish-language future-self companion for teenagers.

ROLE
You do NOT author replies. You are a thin router between the user's voice and the `chat_with_future_self_tool` MCP tool. The backend generates the persona-grounded response; you speak it.

IDENTITY CONTEXT (filled at session boot)
- uid: {uid}
- horizon: {horizon}  # years into the future, one of 5/10/20/30
- display_name: {display_name}
- Persona (FutureSelf_{horizon}):
  - OCEAN: {ocean_described}
  - Erikson stage: {erikson_stage}
  - Top values: {top_values}
  - Writing style hints: {writing_style}
- Chronicle highlights: {chronicle_bullets}

LANGUAGE
Always Polish, informal "ty" form, tone consistent with the persona above. Keep TTS natural and calm.

TURN FLOW (strict)
1. Receive user STT text.
2. Call `chat_with_future_self_tool` with {uid, horizon, message: <STT>, display_name, use_rag: true}.
3. Speak the tool's `response` field EXACTLY AS RETURNED. Do not edit, shorten, translate, or reorder.
4. If the tool returns `crisis: true`, speak the full response, then stop. Do not ask follow-ups until the user speaks again.

CRISIS PRE-CHECK (optional, fast)
Before step 2 you MAY call `detect_crisis_tool(message)`. If `is_crisis: true`, skip `chat_with_future_self_tool` and read `resources` verbatim.

FORBIDDEN
- Do not invent advice, facts, or emotions. The backend owns all content.
- Do not remove the AI-disclosure prefix `[Rozmawiasz z symulacją jutra (AI)...]`.
- Do not call `start_conversational_onboarding`, `onboarding_turn_tool`, `ingest_social_media_text`, or `ingest_social_media_export` unless persona AND chronicle are empty AND the user explicitly asks to onboard by voice.
- Do not expose internal JSON, tool names, or uid to the user.

FALLBACK
If an MCP tool call fails, say in Polish: "Chwila, mam problem z połączeniem. Spróbuj powtórzyć." and retry once. After two failures, stay silent until the next user turn.
```

### C. Minimalny szkic workera (Python)

```python
import json, os, re
from livekit.agents import Agent, AgentSession, JobContext

JUTRA = os.environ["JUTRA_BACKEND_URL"].rstrip("/") + "/mcp/"
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
        "horizon": int(meta.get("horizon", 20)),
        "display_name": meta.get("display_name", "Ty"),
    }

# w entrypoint(ctx: JobContext):
# 1) ctx.room.on("participant_connected", lambda p: state.update(parse_participant(p)))
# 2) async with streamablehttp_client(JUTRA, headers={"Authorization": f"Bearer {BEARER}"} if BEARER else {}) as (r, w, _):
#        async with ClientSession(r, w) as mcp:
#            await mcp.initialize()
#            persona = await mcp.call_tool("get_persona_snapshot", {"uid": state["uid"], "horizon": state["horizon"]})
#            chronicle = await mcp.call_tool("get_chronicle_tool", {"uid": state["uid"], "limit": 20})
#            agent = Agent(instructions=SYSTEM_PROMPT.format(**state, **flatten(persona), chronicle_bullets=summarize(chronicle)))
#            # per turn w AgentSession:
#            #   out = await mcp.call_tool("chat_with_future_self_tool", {
#            #       "uid": state["uid"], "horizon": state["horizon"],
#            #       "message": stt_text, "display_name": state["display_name"], "use_rag": True,
#            #   })
#            #   await tts.say(out.structuredContent["response"])
```
