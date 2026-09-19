"""
MinIO storage client for the EEG pipeline.

Stores the cleaned/filtered EEG output produced by the analysis agent.

MANUAL SETUP REQUIRED BEFORE RUNNING:
1. Have a MinIO server running and reachable (e.g. `docker run -p 9000:9000
   -p 9001:9001 minio/minio server /data --console-address ":9001"` for a
   local instance, or your team's shared instance).
2. Create the bucket this code writes to (default name below) via the MinIO
   console or `mc mb` — this code does not assume permission to create
   buckets, only to read/write objects in one that already exists.
3. Set these environment variables before running the orchestrator:
     MINIO_ENDPOINT   (e.g. "localhost:9000")
     MINIO_ACCESS_KEY
     MINIO_SECRET_KEY
     MINIO_BUCKET     (defaults to "eeg-pipeline" if unset)
     MINIO_SECURE     ("true" if your endpoint uses HTTPS, else "false")
   Do NOT hardcode real credentials in this file or commit them — read them
   from the environment, as done below.
"""

from __future__ import annotations

import os
from minio import Minio
from minio.error import S3Error

DEFAULT_BUCKET = os.environ.get("MINIO_BUCKET", "eeg-pipeline")


def get_client() -> Minio:
    endpoint = os.environ["MINIO_ENDPOINT"]  # raises if not set — fail loudly, don't default silently
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"

    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )


def upload_file(local_path: str, object_name: str | None = None, bucket: str = DEFAULT_BUCKET) -> str:
    """
    Uploads a real file to MinIO. Returns the object name it was stored under.

    object_name defaults to the file's basename if not given — pass an
    explicit path-like name (e.g. "cleaned/subject01_cleaned_raw.fif") to
    organize by pipeline stage.
    """
    client = get_client()

    if not client.bucket_exists(bucket):
        # Intentionally NOT auto-creating the bucket — see setup note above.
        # Bucket-existence policy is a decision for whoever owns access control
        # (Ananiya's scope in your architecture), not something to do silently here.
        raise RuntimeError(
            f"Bucket '{bucket}' does not exist. Create it manually before running "
            f"the pipeline (see MANUAL SETUP note at the top of this file)."
        )

    if object_name is None:
        object_name = os.path.basename(local_path)

    client.fput_object(bucket, object_name, local_path)
    return object_name


def download_file(object_name: str, local_path: str, bucket: str = DEFAULT_BUCKET) -> str:
    """Downloads a real object from MinIO to a local path. Returns local_path."""
    client = get_client()
    client.fget_object(bucket, object_name, local_path)
    return local_path
