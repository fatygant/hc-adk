"""Firestore CRUD for users, chronicle, memories, posts.

Collection layout:
  users/{uid}                          (UserProfile)
  users/{uid}/chronicle/{tid}           (ChronicleTriple)
  users/{uid}/memories/{mid}            (MemoryItem)
  users/{uid}/posts/{pid}               (SocialPost with 768-dim `embedding`)

All writes carry server-side timestamps and are idempotent on (uid, tid/mid/pid)
so the seed script can be re-run safely during the demo.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import UTC, datetime

from google.cloud import firestore
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector

from jutra.infra.firestore import firestore_client
from jutra.memory.models import (
    ChronicleTriple,
    MemoryItem,
    SocialPost,
    UserProfile,
)

_USERS = "users"


def _user_doc(uid: str) -> firestore.DocumentReference:
    return firestore_client().collection(_USERS).document(uid)


def _now() -> datetime:
    return datetime.now(UTC)


# --- user profile --------------------------------------------------------


def upsert_user(profile: UserProfile) -> None:
    ref = _user_doc(profile.uid)
    data = {
        "uid": profile.uid,
        "display_name": profile.display_name,
        "base_age": profile.base_age,
        "gender": profile.gender,
        "ocean_t": profile.ocean_t,
        "riasec_top3": profile.riasec_top3,
        "created_at": profile.created_at,
        "updated_at": _now(),
        "style_turn_count": profile.style_turn_count,
        "style_profile": profile.style_profile,
    }
    if profile.context_notes:
        data["context_notes"] = profile.context_notes
    ref.set(data, merge=True)


def get_user(uid: str) -> UserProfile | None:
    snap = _user_doc(uid).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    gender_raw = str(d.get("gender", "u") or "u").lower()
    gender = gender_raw if gender_raw in ("f", "m", "u") else "u"
    return UserProfile(
        uid=uid,
        display_name=d.get("display_name", ""),
        base_age=int(d.get("base_age", 15)),
        gender=gender,  # type: ignore[arg-type]
        ocean_t=dict(d.get("ocean_t", {})),
        riasec_top3=list(d.get("riasec_top3", [])),
        context_notes=list(d.get("context_notes", []) or []),
        style_profile=dict(d.get("style_profile", {}) or {}),
        style_turn_count=int(d.get("style_turn_count", 0) or 0),
        created_at=d.get("created_at", _now()),
        updated_at=d.get("updated_at", _now()),
    )


def append_context_notes(uid: str, new_notes: list[str], *, max_notes: int = 40) -> None:
    """Append deduplicated short notes to users/{uid}.context_notes (cap at max_notes)."""
    cleaned = [n.strip() for n in new_notes if n and str(n).strip()]
    if not cleaned:
        return
    ref = _user_doc(uid)
    snap = ref.get()
    existing: list[str] = []
    if snap.exists:
        existing = list((snap.to_dict() or {}).get("context_notes", []) or [])
    combined = existing + cleaned
    seen: set[str] = set()
    out: list[str] = []
    for x in combined:
        if x not in seen:
            seen.add(x)
            out.append(x)
    out = out[-max_notes:]
    ref.set({"context_notes": out, "updated_at": _now()}, merge=True)


def get_context_notes(uid: str, limit: int = 40) -> list[str]:
    u = get_user(uid)
    if u is None or not u.context_notes:
        return []
    return u.context_notes[-limit:]


_OCEAN_HISTORY_MAX = 50


def append_ocean_history(
    uid: str,
    entry: dict,
) -> None:
    """Append one OCEAN change record; cap list length."""
    ref = _user_doc(uid)
    snap = ref.get()
    hist: list[dict] = []
    if snap.exists:
        hist = list((snap.to_dict() or {}).get("ocean_history", []) or [])
    hist.append(entry)
    hist = hist[-_OCEAN_HISTORY_MAX:]
    ref.set({"ocean_history": hist, "updated_at": _now()}, merge=True)


def update_ocean(
    uid: str,
    ocean_t: dict[str, float],
    *,
    source: str = "unknown",
    rationale: str = "",
) -> None:
    u = get_user(uid)
    old_o = dict(u.ocean_t) if u and u.ocean_t else {}
    delta: dict[str, float] = {}
    for k in ("O", "C", "E", "A", "N"):
        new_v = float(ocean_t.get(k, old_o.get(k, 50.0)))
        old_v = float(old_o.get(k, 50.0))
        if abs(new_v - old_v) > 1e-6:
            delta[k] = round(new_v - old_v, 4)
    _user_doc(uid).set({"ocean_t": ocean_t, "updated_at": _now()}, merge=True)
    if delta or rationale:
        append_ocean_history(
            uid,
            {
                "ts": _now(),
                "delta": delta,
                "source": source,
                "rationale": (rationale or "")[:500],
            },
        )


def get_riasec_counter(uid: str) -> dict[str, int]:
    snap = _user_doc(uid).get()
    if not snap.exists:
        return {}
    raw = (snap.to_dict() or {}).get("riasec_counter") or {}
    out: dict[str, int] = {}
    for k in ("R", "I", "A", "S", "E", "C"):
        try:
            out[k] = int(raw.get(k, 0) or 0)
        except (TypeError, ValueError):
            out[k] = 0
    return out


def set_riasec_state(uid: str, counter: dict[str, int], top3: list[str]) -> None:
    clean_counter = {k: int(counter.get(k, 0) or 0) for k in ("R", "I", "A", "S", "E", "C")}
    _user_doc(uid).set(
        {
            "riasec_counter": clean_counter,
            "riasec_top3": list(top3)[:3],
            "updated_at": _now(),
        },
        merge=True,
    )


def merge_identity_facets(uid: str, facets: dict[str, str]) -> None:
    """Merge optional identity facets onto users/{uid} (facet_* keys)."""
    data: dict = {"updated_at": _now()}
    for k, v in facets.items():
        v = (v or "").strip()
        if v:
            data[f"facet_{k}"] = v[:200]
    if len(data) > 1:
        _user_doc(uid).set(data, merge=True)


def get_identity_facets(uid: str) -> dict[str, str]:
    snap = _user_doc(uid).get()
    if not snap.exists:
        return {}
    d = snap.to_dict() or {}
    out: dict[str, str] = {}
    for k in ("pronouns", "locality", "language", "school_or_work"):
        v = d.get(f"facet_{k}")
        if v:
            out[k] = str(v)
    return out


def set_user_base_age(uid: str, base_age: int) -> None:
    """Merge `base_age` on users/{uid} (validated 10–80)."""
    if not (10 <= base_age <= 80):
        return
    _user_doc(uid).set({"base_age": base_age, "updated_at": _now()}, merge=True)


# --- rolling chat log (short window for intra-session context) -----------
#
# Each entry: {"role": "user"|"assistant", "text": str, "ts": datetime}.
# Stored on users/{uid}/chat_log/{mid}; the system prompt includes the last
# N entries so the stateless-per-turn future-self LLM knows it already
# greeted and can avoid repetitive openers.

_CHAT_LOG_MAX = 12


def append_chat_turn(uid: str, role: str, text: str, *, max_entries: int = _CHAT_LOG_MAX) -> None:
    """Append one chat entry and trim the rolling log to `max_entries`."""
    text = (text or "").strip()
    if not text or role not in ("user", "assistant"):
        return
    coll = _user_doc(uid).collection("chat_log")
    mid = uuid.uuid4().hex[:20]
    coll.document(mid).set({"role": role, "text": text[:2000], "ts": _now()})

    snaps = list(coll.order_by("ts", direction=firestore.Query.DESCENDING).stream())
    for stale in snaps[max_entries:]:
        stale.reference.delete()


def recent_chat_turns(uid: str, limit: int = 8) -> list[dict]:
    """Return last `limit` chat entries in chronological order."""
    coll = _user_doc(uid).collection("chat_log")
    snaps = list(coll.order_by("ts", direction=firestore.Query.DESCENDING).limit(limit).stream())
    rows = [s.to_dict() or {} for s in snaps]
    rows.reverse()
    return rows


def count_user_chat_turns(uid: str) -> int:
    """Count chat_log documents with role=user (rolling log is small, O(n) ok)."""
    coll = _user_doc(uid).collection("chat_log")
    return sum(1 for s in coll.stream() if (s.to_dict() or {}).get("role") == "user")


def set_user_style_state(uid: str, style_profile: dict, style_turn_count: int) -> None:
    """Persist distilled speaking-style profile and snapshot user-turn count."""
    _user_doc(uid).set(
        {
            "style_profile": style_profile,
            "style_turn_count": style_turn_count,
            "updated_at": _now(),
        },
        merge=True,
    )


# --- chronicle (ID-RAG triples) ------------------------------------------


def _triple_id(t: ChronicleTriple) -> str:
    h = hashlib.sha1(f"{t.subject}|{t.predicate}|{t.object}|{t.kind}".encode()).hexdigest()
    return h[:20]


def _chronicle_effective_weight(doc: dict) -> float:
    w = float(doc.get("weight", 0.5) or 0.5)
    last = doc.get("last_seen") or doc.get("created_at")
    if last is None:
        days = 0.0
    elif hasattr(last, "timestamp"):
        delta = _now() - last
        days = max(0.0, delta.total_seconds() / 86400.0)
    else:
        days = 0.0
    return w * math.exp(-days / 180.0)


def add_chronicle(uid: str, triple: ChronicleTriple) -> str:
    tid = _triple_id(triple)
    ref = _user_doc(uid).collection("chronicle").document(tid)
    now = _now()
    snap = ref.get()
    if snap.exists:
        d = snap.to_dict() or {}
        old_w = float(d.get("weight", triple.weight))
        occ = int(d.get("occurrences", 1)) + 1
        new_w = min(1.0, old_w + 0.1 / math.sqrt(float(occ)))
        ref.set(
            {
                "subject": triple.subject,
                "predicate": triple.predicate,
                "object": triple.object,
                "kind": triple.kind,
                "weight": new_w,
                "source": triple.source,
                "occurrences": occ,
                "last_seen": now,
                "disputed": False,
                "created_at": d.get("created_at", triple.created_at),
            }
        )
    else:
        ref.set(
            {
                "subject": triple.subject,
                "predicate": triple.predicate,
                "object": triple.object,
                "kind": triple.kind,
                "weight": triple.weight,
                "source": triple.source,
                "created_at": triple.created_at,
                "occurrences": 1,
                "last_seen": now,
                "disputed": False,
            }
        )
    return tid


def revoke_chronicle(uid: str, kind: str, object: str) -> bool:  # noqa: A002
    """Halve weight on a value/preference triple; mark disputed if weight < 0.3."""
    if kind == "value":
        t = ChronicleTriple(uid, "ceni", object, kind="value")
    elif kind == "preference":
        t = ChronicleTriple(uid, "lubi", object, kind="preference")
    else:
        return False
    tid = _triple_id(t)
    ref = _user_doc(uid).collection("chronicle").document(tid)
    snap = ref.get()
    if not snap.exists:
        return False
    d = snap.to_dict() or {}
    old_w = float(d.get("weight", 0.5))
    new_w = old_w * 0.5
    disputed = new_w < 0.3
    ref.set(
        {
            "weight": new_w,
            "disputed": disputed,
            "last_seen": _now(),
        },
        merge=True,
    )
    return True


def list_chronicle(uid: str, kind: str | None = None, limit: int = 50) -> list[dict]:
    q = _user_doc(uid).collection("chronicle")
    if kind:
        q = q.where("kind", "==", kind)
    q = q.order_by("weight", direction=firestore.Query.DESCENDING).limit(limit)
    return [{**d.to_dict(), "id": d.id} for d in q.stream()]


def list_disputed_chronicle(uid: str, limit: int = 12) -> list[dict]:
    q = _user_doc(uid).collection("chronicle").where("disputed", "==", True).limit(limit)
    return [{**d.to_dict(), "id": d.id} for d in q.stream()]


def list_recent_arcs(uid: str, limit: int = 3) -> list[dict]:
    # Single-field order keeps us on the auto-created index. Filtering by kind
    # server-side would require a composite index (kind, created_at); at the
    # scale of a single user's chronicle (tens of rows) a Python-side filter
    # is cheap and avoids the index dependency.
    q = (
        _user_doc(uid)
        .collection("chronicle")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(max(limit * 10, 30))
    )
    out: list[dict] = []
    for d in q.stream():
        row = d.to_dict()
        if row.get("kind") != "arc":
            continue
        out.append({**row, "id": d.id})
        if len(out) >= limit:
            break
    return out


def top_values(uid: str, limit: int = 5) -> list[str]:
    items = list_chronicle(uid, kind="value", limit=50)
    scored: list[tuple[float, str]] = []
    for it in items:
        obj = it.get("object")
        if not obj:
            continue
        eff = _chronicle_effective_weight(it)
        if eff < 0.1:
            continue
        scored.append((eff, str(obj)))
    scored.sort(key=lambda x: -x[0])
    return [o for _, o in scored[:limit]]


# --- episodic memories ---------------------------------------------------


def add_memory(uid: str, item: MemoryItem) -> str:
    mid = uuid.uuid4().hex[:20]
    doc: dict = {
        "text": item.text,
        "topic": item.topic,
        "source": item.source,
        "created_at": item.created_at,
    }
    if item.due_hint:
        doc["due_hint"] = item.due_hint[:200]
    _user_doc(uid).collection("memories").document(mid).set(doc)
    return mid


def recent_memories(uid: str, limit: int = 10) -> list[dict]:
    q = (
        _user_doc(uid)
        .collection("memories")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [d.to_dict() for d in q.stream()]


def list_open_commitments(uid: str, *, limit: int = 5, max_age_days: int = 30) -> list[dict]:
    """Recent commitment memories, excluding very old rows.

    Filter by topic in Python to avoid a composite (topic, created_at) index.
    """
    q = (
        _user_doc(uid)
        .collection("memories")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(max(limit * 10, 50))
    )
    rows: list[dict] = []
    for d in q.stream():
        row = d.to_dict()
        if row.get("topic") == "commitment":
            rows.append(row)
    cutoff = _now().timestamp() - max_age_days * 86400
    out: list[dict] = []
    for m in rows:
        ts = m.get("created_at")
        if hasattr(ts, "timestamp") and ts.timestamp() < cutoff:
            continue
        text = (m.get("text") or "").strip()
        if not text:
            continue
        tl = text.lower()
        if any(
            x in tl
            for x in ("zrobiłem", "zrobilem", "zrobiłam", "zrobilam", "udało się", "udalo sie")
        ):
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return out


# --- social posts with vector search -------------------------------------


def add_post(uid: str, post: SocialPost) -> str:
    pid = hashlib.sha1(post.raw_text.encode()).hexdigest()[:20]
    doc = {
        "platform": post.platform,
        "raw_text": post.raw_text,
        "themes": post.themes,
        "created_at": post.created_at,
    }
    if post.salience is not None:
        doc["salience"] = float(post.salience)
    if post.embedding:
        doc["embedding"] = Vector(post.embedding)
    _user_doc(uid).collection("posts").document(pid).set(doc)
    return pid


def semantic_posts(
    uid: str,
    query_embedding: list[float],
    k: int = 5,
    distance_measure: DistanceMeasure = DistanceMeasure.COSINE,
) -> list[dict]:
    """Return top-k posts nearest to the query embedding (cosine), ties by salience."""
    coll = _user_doc(uid).collection("posts")
    query = coll.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=distance_measure,
        limit=max(k * 3, k + 5),
    )
    out: list[dict] = []
    for snap in query.stream():
        d = snap.to_dict() or {}
        d.pop("embedding", None)
        out.append(d)
    out.sort(key=lambda d: -float(d.get("salience", 0.5) or 0.5))
    return out[:k]


def count_posts(uid: str) -> int:
    coll = _user_doc(uid).collection("posts")
    agg = coll.count().get()
    if not agg:
        return 0
    return int(agg[0][0].value)


# --- photo metadata ------------------------------------------------------


def save_photo_original(uid: str, blob_name: str) -> None:
    """Initialise photo metadata after original upload.

    Layout: `users/{uid}.photos = {original_gcs, overall_status, aged:
    {gcs_path, status}, uploaded_at}`. A single aged photo replaces the former
    5/10/20/30 per-horizon map.
    """
    _user_doc(uid).set(
        {
            "photos": {
                "original_gcs": blob_name,
                "overall_status": "processing",
                "aged": {"gcs_path": "", "status": "pending"},
                "uploaded_at": _now(),
            }
        },
        merge=True,
    )


def set_aged_photo_done(uid: str, blob_name: str) -> None:
    _user_doc(uid).update(
        {
            "photos.aged.gcs_path": blob_name,
            "photos.aged.status": "done",
        }
    )


def set_overall_photo_status(uid: str, status: str) -> None:
    _user_doc(uid).update({"photos.overall_status": status})


def get_photo_meta(uid: str) -> dict | None:
    snap = _user_doc(uid).get(field_paths=["photos"])
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    return d.get("photos")  # type: ignore[return-value]


# --- housekeeping --------------------------------------------------------

_SUBCOLLECTIONS = ("chronicle", "memories", "posts", "chat_log")


def wipe_user(uid: str) -> dict[str, int]:
    """Delete the user doc and all known subcollections.

    Used by the demo seed script to keep the Alex_15 fixture deterministic
    between runs. Returns a count of deleted documents per subcollection so
    the caller can print a summary.
    """
    counts: dict[str, int] = {}
    user_ref = _user_doc(uid)
    for name in _SUBCOLLECTIONS:
        n = 0
        for snap in user_ref.collection(name).stream():
            snap.reference.delete()
            n += 1
        counts[name] = n
    if user_ref.get().exists:
        user_ref.delete()
        counts["user_doc"] = 1
    else:
        counts["user_doc"] = 0
    return counts
