"""Google Cloud Storage helpers."""

from __future__ import annotations

from google.cloud import storage

from jutra.settings import get_settings


def _bucket() -> storage.Bucket:
    s = get_settings()
    return storage.Client(project=s.google_cloud_project).bucket(s.gcs_bucket)


def upload_bytes(blob_name: str, data: bytes, content_type: str = "image/jpeg") -> None:
    blob = _bucket().blob(blob_name)
    blob.upload_from_string(data, content_type=content_type)


def download_bytes(blob_name: str) -> bytes:
    return _bucket().blob(blob_name).download_as_bytes()
