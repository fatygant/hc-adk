"""Firestore client wrapper (single default database, region eur3)."""

from __future__ import annotations

from functools import lru_cache

from google.cloud import firestore

from jutra.settings import get_settings


@lru_cache
def firestore_client() -> firestore.Client:
    s = get_settings()
    return firestore.Client(project=s.google_cloud_project)
