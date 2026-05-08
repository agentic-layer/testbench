"""Download an Experiment JSON file from S3/MinIO, validate it, and save.

Phase 1 of the evaluation pipeline. The source object is expected to already
be a serialized ``Experiment`` (matching ``schema/experiment.schema.json``)
in JSON form. The file is validated against the ``Experiment`` Pydantic
model and written to ``data/datasets/experiment.json``.

Usage::

    python3 scripts/setup.py <bucket> <key>
"""

import argparse
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from pydantic import ValidationError

from testbench.schema.models import Experiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EXPERIMENT_OUTPUT_PATH = Path("data/datasets/experiment.json")
SUPPORTED_SUFFIX = ".json"


def parse_experiment(content: bytes, key: str) -> Experiment:
    """Parse and validate experiment JSON content from raw bytes.

    Args:
        content: Raw file content as bytes.
        key: File name or S3 key — used to verify format via suffix.

    Returns:
        A validated ``Experiment`` instance.

    Raises:
        ValueError: If the file suffix is not ``.json`` or content fails validation.
    """
    suffix = Path(key).suffix.lower()
    if suffix != SUPPORTED_SUFFIX:
        raise ValueError(f"Unsupported filetype for key: {key}. Must end with {SUPPORTED_SUFFIX}")

    data: Any = json.loads(content.decode("utf-8"))

    try:
        return Experiment.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Experiment validation failed for {key}: {e}") from e


def save_experiment(experiment: Experiment, output_path: Path = EXPERIMENT_OUTPUT_PATH) -> None:
    """Write a validated ``Experiment`` to ``data/datasets/experiment.json``."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(experiment.model_dump_json(indent=2, exclude_none=True))


def create_s3_client() -> Any:
    """Create and configure an S3 client targeting MinIO."""
    access_key = os.getenv("MINIO_ROOT_USER", "minio")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD", "minio123")
    endpoint_url = os.getenv("MINIO_ENDPOINT", "http://testkube-minio-service-testkube.testkube:9000")

    logger.info("Connecting to MinIO at %s", endpoint_url)

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


def load_experiment_from_s3(bucket: str, key: str) -> Experiment:
    """Download an experiment JSON file from S3/MinIO and validate it."""
    s3_client = create_s3_client()
    logger.info("Downloading from bucket '%s', key '%s'...", bucket, key)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content: bytes = response["Body"].read()
    logger.info("Downloaded %d bytes", len(content))
    return parse_experiment(content, key)


def load_experiment_from_url(url: str) -> Experiment:
    """Download an experiment JSON file from an HTTP(S) URL and validate it."""
    logger.info("Downloading experiment from %s...", url)
    with urllib.request.urlopen(url) as response:  # noqa: S310  # nosec B310
        content: bytes = response.read()
    logger.info("Downloaded %d bytes", len(content))
    return parse_experiment(content, url.split("?")[0])


def load_experiment_from_file(file_path: str) -> Experiment:
    """Load an experiment JSON file from a local path and validate it."""
    path = Path(file_path)
    logger.info("Loading experiment from %s...", file_path)
    content = path.read_bytes()
    logger.info("Loaded %d bytes", len(content))
    return parse_experiment(content, path.name)


def main(bucket: str, key: str) -> None:
    """Download an Experiment from S3, validate it, and save it locally.

    Args:
        bucket: S3 bucket name.
        key: S3 object key (path to a JSON Experiment file).
    """
    experiment = load_experiment_from_s3(bucket, key)
    save_experiment(experiment)
    logger.info("Experiment saved to %s", EXPERIMENT_OUTPUT_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Download an Experiment JSON from S3/MinIO, validate it, and save to data/datasets/experiment.json"
        )
    )
    parser.add_argument("bucket", type=str, help="S3/MinIO bucket name")
    parser.add_argument(
        "key",
        type=str,
        help="S3/MinIO object key (path to .json Experiment file)",
    )
    args = parser.parse_args()

    main(args.bucket, args.key)
