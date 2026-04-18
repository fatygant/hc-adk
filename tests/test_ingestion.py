from __future__ import annotations

from dataclasses import dataclass

import pytest

from jutra.ingestion import pipeline as pipeline_mod
from jutra.ingestion.parsers.instagram_json import parse_instagram_json
from jutra.ingestion.parsers.twitter_archive import parse_twitter_archive
from jutra.memory import store as memstore
from tests._fakestore import FakeFirestore


def test_parse_twitter_archive_strips_prefix_and_retweets() -> None:
    raw = (
        "window.YTD.tweets.part0 = [\n"
        '  { "tweet": { "full_text": "RT @someone: ignore me", "created_at": "Sat" } },\n'
        '  { "tweet": { "full_text": "pierwsza mysl o przyszlosci", "created_at": "Sun" } },\n'
        '  { "tweet": { "full_text": "druga mysl", "created_at": "Mon" } }\n'
        "];"
    )
    parsed = parse_twitter_archive(raw, limit=10)
    assert [p.text for p in parsed] == [
        "pierwsza mysl o przyszlosci",
        "druga mysl",
    ]


def test_parse_twitter_archive_respects_limit() -> None:
    tweets = ",\n".join(
        f'{{ "tweet": {{ "full_text": "post {i}", "created_at": "Sun" }} }}' for i in range(10)
    )
    raw = f"window.YTD.tweets.part0 = [{tweets}];"
    parsed = parse_twitter_archive(raw, limit=3)
    assert len(parsed) == 3


def test_parse_instagram_json() -> None:
    raw = (
        "["
        '{"media":[{"title":"zdjecie z koncertu","creation_timestamp":1710000000}]},'
        '{"title":"podroz","media":[{"title":""}]}'
        "]"
    )
    parsed = parse_instagram_json(raw, limit=5)
    assert len(parsed) == 2
    assert parsed[0].text == "zdjecie z koncertu"
    assert parsed[0].created_at.startswith("2024-")
    assert parsed[1].text == "podroz"


@dataclass
class _FakeResp:
    text: str


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeFirestore:
    db = FakeFirestore()
    monkeypatch.setattr(memstore, "firestore_client", lambda: db)
    return db


def test_text_ingest_end_to_end(monkeypatch: pytest.MonkeyPatch, fake_db: FakeFirestore) -> None:
    # Fake LLM: return themes/values/preferences/signals based on keyword.
    def fake_generate(kind, contents, *, config=None):  # type: ignore[no-untyped-def]
        text = contents if isinstance(contents, str) else str(contents)
        if "matem" in text.lower() or "kod" in text.lower():
            return _FakeResp(
                text=(
                    '{"themes":["nauka"],'
                    '"values":["wiedza"],'
                    '"preferences":["lubie programowac"],'
                    '"ocean_signals":{"O":0.5,"C":0.3,"E":0.0,"A":0.0,"N":-0.2}}'
                )
            )
        if "muzyk" in text.lower():
            return _FakeResp(
                text=(
                    '{"themes":["muzyka"],'
                    '"values":["ekspresja"],'
                    '"preferences":["lubie muzyke"],'
                    '"ocean_signals":{"O":0.4,"C":0.0,"E":0.2,"A":0.1,"N":0.0}}'
                )
            )
        return _FakeResp(text="{}")

    def fake_embed(texts):  # type: ignore[no-untyped-def]
        return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(pipeline_mod, "generate_with_fallback", fake_generate)
    monkeypatch.setattr(pipeline_mod, "embed", fake_embed)

    result = pipeline_mod.text_ingest(
        "alex",
        [
            "lubie matematyke i kodowanie",
            "dzis gralem na gitarze, muzyka to moje zycie",
            "puste",
        ],
        platform="twitter",
    )

    assert result.ingested == 2
    assert result.skipped == 1
    assert set(result.top_themes) >= {"nauka", "muzyka"}
    # OCEAN should move UP on O (both posts positive) and C (first positive)
    assert result.updated_ocean["O"] > 50
    # chronicle should have 2 values + 2 preferences
    values = memstore.list_chronicle("alex", kind="value")
    prefs = memstore.list_chronicle("alex", kind="preference")
    assert {v["object"] for v in values} == {"wiedza", "ekspresja"}
    assert {p["object"] for p in prefs} == {"lubie programowac", "lubie muzyke"}
    # posts should have embeddings
    assert memstore.count_posts("alex") == 2
