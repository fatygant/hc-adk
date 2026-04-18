# jutra — backlog po hackathonie

Lista rzeczy, ktore swiadomie nie weszly w 24 h, wraz z uzasadnieniem i
rozsadnym kierunkiem pracy na potem. Kolejnosc = subiektywny priorytet.

## 1. Prawdziwa integracja z LiveKit voice agent

**Stan:** Backend wystawia 9 tooli przez MCP Streamable-HTTP + Bearer.
Voice-UI robi kolega na LiveKit Agents. Kontrakt zamkniety w
[`integrations/livekit-integration.md`](integrations/livekit-integration.md).

**Do zrobienia:** realny LiveKit worker odpalony na osobnym Cloud Run, STT
(Deepgram / Google STT) + TTS (ElevenLabs PL / Google Neural2-PL) + interrupcja
gdy mowisz w trakcie odpowiedzi agenta. Osobne repo, osobny deploy, ten sam
Secret Manager.

## 2. Prawdziwe uwierzytelnianie + dane per-uzytkownik

**Stan:** jeden wspoldzielony Bearer (`mcp-bearer` w Secret Manager) na calym
backendzie, `uid` jest parametrem tooli — czyli kazdy kto zna sekret, czyta
dowolnego uzytkownika.

**Do zrobienia:**
- Google Identity Platform (OAuth2, konto rodzica dla <16 r.z.) -> JWT.
- Firestore Security Rules: `users/{uid}` czyta tylko `request.auth.uid == uid`.
- MCP bearer przejmuje rola app-service-to-backend, `uid` wyciagany z JWT.
- Rate limit per-uid (Cloud Armor + Memorystore counter).

## 3. Zgodnosc prawna

**Stan:** tylko prefix AI disclosure + detektor kryzysu + redakcja PII.

**Do zrobienia:**
- GDPR art. 8 (PL: zgoda rodzica do 16 r.z.) — flow potwierdzenia email / SMS.
- DPIA (Data Protection Impact Assessment), bo przetwarzamy wrazliwe dane
  zdrowotne (klasyfikator kryzysu).
- AI Act system card (klasyfikacja jako "high-risk"? "limited-risk"?).
- Procedura zapomnienia (delete cascade juz jest jako `wipe_user` w
  [`jutra/memory/store.py`](jutra/memory/store.py) — brakuje UI + audit log).
- Zero retention LLM-ow (Vertex AI "no data for training" toggle).

## 4. Ingest OAuth (Spotify, Instagram, Twitter/X)

**Stan:** tylko wklejenie tekstu + eksport GDPR (`tweets.js`, `posts_*.json`).

**Do zrobienia:** Spotify top-tracks + top-artists + listeninghistory -> themes.
Instagram Graph API (wiecej niz GDPR dump). Mozliwa Letterboxd / Spotify
wrapping. Ingest w tle (Cloud Tasks), niezaleznie od okna chatu.

## 5. ValuesReasonerAgent (PB&J)

**Stan:** PB&J (Psychological-driven, Boundary-spanning, Jeopardy-based
rationalizations) tylko w system prompcie `FutureSelf_N`.

**Do zrobienia:** osobny `LlmAgent` ktory dla kazdej odpowiedzi generuje
3 alternatywne racjonalizacje tej samej decyzji (one-of-many), jedna jest
swiadomie kontrowersyjna. Wzmacnia autentycznosc persony ("przyszly ja nie
boi sie rzeczy trudnych").

## 6. Evalset ADK + golden set

**Stan:** 56 unit tests, zaden nie sprawdza "jakosci" odpowiedzi LLM.

**Do zrobienia:**
- Zestaw 30 zlotych promptow (wartosci, kariery, kryzys, ciekawostka).
- Evalset ADK (`jutra.evalset`) ktory scoruje odpowiedzi przez sedziego LLM
  (gemini-3-pro jako judge) na 4 osiach: tozsamosc, bezpieczenstwo,
  uzytecznosc, spojnosc z Chronicle.
- CI: kazdy PR robi evalset diff vs. main.

## 7. Observability + SLO

**Stan:** structured logs w Cloud Logging, nic poza tym.

**Do zrobienia:** Cloud Trace dla kazdej tury (onboarding/ingest/chat),
log sink do BigQuery, dashboard Grafana / Looker Studio z:
- latencja p50/p95 na tool,
- odsetek crisis=true (`>=3`),
- retencja post-onboarding (ile osob dochodzi do 1. tury chatu),
- top values / top themes w czasie.

## 8. Bardziej bogata persona

**Stan:** OCEAN T-scores + Maturity Principle + Erikson + RIASEC top-3.

**Do zrobienia:**
- Schwartz Value Survey (10 wartosci) zamiast wolnej listy.
- Attachment style (wplywa jak FutureSelf_N mowi o bliskosci).
- Self-discrepancy (actual vs. ideal vs. ought) — zmienia ton odpowiedzi.

## 9. Reliability

**Stan:** Cloud Run `--min-instances=1 --max-instances=3` (hackathonowy
scale). Fallback Gemini 3 preview -> 2.5 Flash.

**Do zrobienia:**
- Retry/backoff dla Firestore i Vertex (teraz tylko one-shot).
- Circuit breaker dla ingest (gdy LLM jest padnienty — kolejkuj posty do
  pozniejszego przetworzenia zamiast gubic).
- Multi-region Cloud Run (eu + us) z ruchem waga "closest".

## 10. Drobne techniczne

- `docs/` jest ignorowany w repo (osobny git); docelowo merge do `integrations/`.
- Zadne testy integracyjne nie strzelaja w live Firestore / Vertex (mamy fake
  store w tests/_fakestore.py). Warto dodac `pytest -m live`.
- `scripts/seed.py` jest idempotentny dzieki `--reset`, ale nie jest
  konteneryzowany — godne odpalenia jako Cloud Run Job po kazdym deployu.
- Dockerfile jest "fat" (calosc zrzutu); `uv` cache mozna byloby wydluzyc
  przez multi-stage build (`python:3.11-slim` + `uv pip install`).
