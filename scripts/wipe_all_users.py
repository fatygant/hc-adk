#!/usr/bin/env python3
"""Wipe all Firestore user data (and optionally GCS photos).

Run before a major cutover (e.g. enabling email auth) so new accounts do not
inherit old personas.

Usage:
    GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \\
      python3 scripts/wipe_all_users.py

  With photo bucket cleanup (destructive):
    python3 scripts/wipe_all_users.py --gcs

Requires Firestore delete permission on `users/*` and `email_accounts/*`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wipe_gcs_bucket(bucket: str) -> None:
    from google.cloud import storage  # noqa: PLC0415

    client = storage.Client()
    deleted = 0
    for blob in client.list_blobs(bucket):
        blob.delete()
        deleted += 1
    print(f"== GCS bucket {bucket}: deleted {deleted} objects")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gcs",
        action="store_true",
        help="Also delete all objects in GCS_BUCKET (default from env or hc-user-photos)",
    )
    args = parser.parse_args()

    from jutra.infra.firestore import firestore_client  # noqa: PLC0415
    from jutra.memory.store import wipe_user  # noqa: PLC0415

    db = firestore_client()

    # email_accounts (login index)
    acc_coll = db.collection("email_accounts")
    acc_snaps = list(acc_coll.stream())
    for snap in acc_snaps:
        snap.reference.delete()
    print(f"== deleted {len(acc_snaps)} email_accounts documents")

    users_coll = db.collection("users")
    uids = [s.id for s in users_coll.stream()]
    print(f"== found {len(uids)} users: {uids}")

    grand: dict[str, int] = {}
    for uid in uids:
        counts = wipe_user(uid)
        print(f"   wipe {uid}: {counts}")
        for k, v in counts.items():
            grand[k] = grand.get(k, 0) + v

    print(f"== totals: {grand}")

    if args.gcs:
        bucket = os.environ.get("GCS_BUCKET", "hc-user-photos")
        _wipe_gcs_bucket(bucket)

    print("== done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
