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
        "ocean_t": profile.ocean_t,
        "riasec_top3": profile.riasec_top3,
        "created_at": profile.created_at,
        "updated_at": _now(),
    }
    ref.set(data, merge=True)


def get_user(uid: str) -> UserProfile | None:
    snap = _user_doc(uid).get()
    if not snap.exists:
        return None
    d = snap.to_dict() or {}
    return UserProfile(
        uid=uid,
        display_name=d.get("display_name", ""),
        base_age=int(d.get("base_age", 15)),
        ocean_t=dict(d.get("ocean_t", {})),
        riasec_top3=list(d.get("riasec_top3", [])),
        created_at=d.get("created_at", _now()),
        updated_at=d.get("updated_at", _now()),
    )


def update_ocean(uid: str, ocean_t: dict[str, float]) -> None:
    _user_doc(uid).set({"ocean_t": ocean_t, "updated_at": _now()}, merge=True)


# --- chronicle (ID-RAG triples) ------------------------------------------


def _triple_id(t: ChronicleTriple) -> str:
    h = hashlib.sha1(f"{t.subject}|{t.predicate}|{t.object}|{t.kind}".encode()).hexdigest()
    return h[:20]


def add_chronicle(uid: str, triple: ChronicleTriple) -> str:
    tid = _triple_id(triple)
    _user_doc(uid).collection("chronicle").document(tid).set(
        {
            "subject": triple.subject,
            "predicate": triple.predicate,
            "object": triple.object,
            "kind": triple.kind,
            "weight": triple.weight,
            "source": triple.source,
            "created_at": triple.created_at,
        }
    )
    return tid


def list_chronicle(uid: str, kind: str | None = None, limit: int = 50) -> list[dict]:
    q = _user_doc(uid).collection("chronicle")
    if kind:
        q = q.where("kind", "==", kind)
    q = q.order_by("weight", direction=firestore.Query.DESCENDING).limit(limit)
    return [{**d.to_dict(), "id": d.id} for d in q.stream()]


def top_values(uid: str, limit: int = 5) -> list[str]:
    items = list_chronicle(uid, kind="value", limit=limit)
    return [it["object"] for it in items if it.get("object")]


# --- episodic memories ---------------------------------------------------


def add_memory(uid: str, item: MemoryItem) -> str:
    mid = uuid.uuid4().hex[:20]
    _user_doc(uid).collection("memories").document(mid).set(
        {
            "text": item.text,
            "topic": item.topic,
            "source": item.source,
            "horizon": item.horizon,
            "created_at": item.created_at,
        }
    )
    return mid


def recent_memories(uid: str, limit: int = 10) -> list[dict]:
    q = (
        _user_doc(uid)
        .collection("memories")
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .limit(limit)
    )
    return [d.to_dict() for d in q.stream()]


# --- social posts with vector search -------------------------------------


def add_post(uid: str, post: SocialPost) -> str:
    pid = hashlib.sha1(post.raw_text.encode()).hexdigest()[:20]
    doc = {
        "platform": post.platform,
        "raw_text": post.raw_text,
        "themes": post.themes,
        "created_at": post.created_at,
    }
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
    """Return top-k posts nearest to the query embedding (cosine)."""
    coll = _user_doc(uid).collection("posts")
    query = coll.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_embedding),
        distance_measure=distance_measure,
        limit=k,
    )
    out: list[dict] = []
    for snap in query.stream():
        d = snap.to_dict() or {}
        d.pop("embedding", None)
        out.append(d)
    return out


def count_posts(uid: str) -> int:
    coll = _user_doc(uid).collection("posts")
    agg = coll.count().get()
    if not agg:
        return 0
    return int(agg[0][0].value)


# --- photo metadata ------------------------------------------------------

_PHOTO_HORIZONS = [5, 10, 20, 30]


def save_photo_original(uid: str, blob_name: str) -> None:
    """Initialise photo metadata after original upload."""
    _user_doc(uid).set(
        {
            "photos": {
                "original_gcs": blob_name,
                "overall_status": "processing",
                "aged": {
                    str(h): {"gcs_path": "", "status": "pending"}
                    for h in _PHOTO_HORIZONS
                },
                "uploaded_at": _now(),
            }
        },
        merge=True,
    )


def set_aged_photo_done(uid: str, horizon: int, blob_name: str) -> None:
    _user_doc(uid).update(
        {
            f"photos.aged.{horizon}.gcs_path": blob_name,
            f"photos.aged.{horizon}.status": "done",
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

_SUBCOLLECTIONS = ("chronicle", "memories", "posts")


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
