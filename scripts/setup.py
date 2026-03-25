"""Download dataset from S3/MinIO, convert to Experiment JSON, and save.

Phase 1 of the evaluation pipeline. Downloads a dataset file (CSV, JSON,
or Parquet) from S3/MinIO and converts it into an ``Experiment`` JSON file
that subsequent phases can consume.

Usage::

    python3 scripts/setup.py <bucket> <key>
"""

import argparse
import asyncio
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import boto3
import httpx
import pandas as pd
from botocore.client import Config
from pandas import DataFrame
from schema.models import Experiment, Reference, Scenario, Step

# Set up module-level logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def dataframe_to_experiment(dataframe: DataFrame) -> None:
    """Convert DataFrame to Experiment JSON and save to data/datasets/experiment.json.

    Expected schema:
    - user_input: The test question/prompt
    - retrieved_contexts: List of retrieved context strings (optional)
    - reference: The reference/ground truth answer (optional)
    """
    steps: list[Step] = []

    for _, row in dataframe.iterrows():
        custom_values: dict[str, Any] = {}

        if "retrieved_contexts" in row and row["retrieved_contexts"] is not None:
            custom_values["retrieved_contexts"] = row["retrieved_contexts"]

        reference: Reference | None = None
        if "reference" in row and row["reference"] is not None and str(row["reference"]).strip():
            reference = Reference(response=str(row["reference"]))

        step = Step(
            input=str(row["user_input"]),
            reference=reference,
            custom_values=custom_values if custom_values else None,
        )
        steps.append(step)

    scenario = Scenario(name="dataset", steps=steps)
    experiment = Experiment(scenarios=[scenario])

    output_path = Path("data/datasets/experiment.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(experiment.model_dump_json(indent=2, exclude_none=True))


def get_converter(key: str) -> Callable[[BytesIO], DataFrame]:
    """Extract the file format from the S3 key suffix and return the converter function."""
    suffix = Path(key).suffix.lower()

    format_map: dict[str, Callable[[BytesIO], DataFrame]] = {
        ".json": pd.read_json,
        ".csv": custom_convert_csv,
        ".parquet": pd.read_parquet,
        ".prq": pd.read_parquet,
    }

    if suffix in format_map:
        return format_map[suffix]

    raise TypeError(f"Unsupported filetype for key: {key}. Must end with .csv, .json, .parquet, or .prq")


def custom_convert_csv(input_file: BytesIO) -> DataFrame:
    """Convert a CSV input file to a Pandas DataFrame.

    If 'retrieved_contexts' column exists, ensures it is a list of strings
    (RAGAS requires 'retrieved_contexts' as a list of strings).

    Args:
        input_file: The CSV input_file

    Returns:
        Pandas DataFrame with correct formatting
    """
    dataframe: DataFrame = pd.read_csv(input_file)

    # Ensure retrieved_contexts is a list (convert string to list if needed)
    if "retrieved_contexts" in dataframe:
        dataframe["retrieved_contexts"] = dataframe["retrieved_contexts"].apply(
            lambda x: x if isinstance(x, list) else [x] if x else []
        )

    return dataframe


def create_s3_client() -> Any:
    """Create and configure S3 client for MinIO."""
    # Get MinIO credentials from environment
    access_key = os.getenv("MINIO_ROOT_USER", "minio")
    secret_key = os.getenv("MINIO_ROOT_PASSWORD", "minio123")
    endpoint_url = os.getenv("MINIO_ENDPOINT", "http://testkube-minio-service-testkube.testkube:9000")

    logger.info(f"Connecting to MinIO at {endpoint_url}")

    # Create S3 client with MinIO configuration
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",  # MinIO doesn't care about region, but boto3 requires it
    )

    return s3_client


def main(bucket: str, key: str) -> None:
    """Download dataset from S3/MinIO -> convert to Experiment JSON -> save.

    Source dataset must contain column: user_input
    Optional columns: retrieved_contexts, reference

    Args:
        bucket: S3 bucket name
        key: S3 object key (path to dataset file)
    """
    converter = get_converter(key)

    # Create S3 client
    s3_client = create_s3_client()

    # Download file from S3
    logger.info(f"Downloading from bucket '{bucket}', key '{key}'...")
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        file_content = response["Body"].read()
        logger.info(f"Downloaded {len(file_content)} bytes")
    except Exception as e:
        logger.error(f"Failed to download from S3: {e}")
        raise

    # Load into DataFrame by using the correct converter
    logger.info("Converting to DataFrame...")
    buffer = BytesIO(file_content)

    dataframe = converter(buffer)
    logger.info(f"Loaded {len(dataframe)} rows")

    # Convert DataFrame to Experiment JSON and save it
    logger.info("Converting to Experiment JSON...")
    dataframe_to_experiment(dataframe)
    logger.info("Dataset saved successfully to data/datasets/experiment.json")


async def download_http(url: str) -> bytes:
    """Download a file from an HTTP/HTTPS URL."""
    logger.info(f"Downloading from {url}...")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120)) as client:
        response = await client.get(url)
        response.raise_for_status()
        logger.info(f"Downloaded {len(response.content)} bytes")
        return response.content


def detect_source_type(source: str) -> str:
    """Detect the source type from the source string."""
    if source.startswith("s3://"):
        return "s3"
    if source.startswith("http://") or source.startswith("https://"):
        return "http"
    return "file"


def main_auto(source: str) -> None:
    """Download dataset from any source, convert to Experiment JSON, and save.

    Auto-detects source type:
    - s3://bucket/key -> S3 download
    - http:// or https:// -> HTTP download
    - otherwise -> local file path
    """
    source_type = detect_source_type(source)

    if source_type == "s3":
        path = source[5:]  # Remove "s3://"
        parts = path.split("/", 1)
        if len(parts) != 2 or not parts[1]:
            raise ValueError(f"Invalid S3 URI: {source}. Expected format: s3://bucket/key")
        bucket, key = parts
        main(bucket, key)
        return

    if source_type == "http":
        parsed = urlparse(source)
        key = parsed.path
        converter = get_converter(key)
        content = asyncio.run(download_http(source))
        buffer = BytesIO(content)
        dataframe = converter(buffer)
    else:
        file_path = Path(source)
        if not file_path.exists():
            raise FileNotFoundError(f"Local file not found: {source}")
        converter = get_converter(source)
        with open(file_path, "rb") as f:
            buffer = BytesIO(f.read())
        dataframe = converter(buffer)

    logger.info(f"Loaded {len(dataframe)} rows")
    dataframe_to_experiment(dataframe)
    logger.info("Dataset saved successfully to data/datasets/experiment.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download dataset and convert to Experiment JSON")
    parser.add_argument(
        "source",
        type=str,
        help="Dataset source: s3://bucket/key, HTTP URL, or local file path",
    )
    parser.add_argument(
        "key",
        type=str,
        nargs="?",
        default=None,
        help="(Legacy) S3 object key when first arg is a bucket name",
    )
    args = parser.parse_args()

    if args.key is not None:
        # Legacy mode: setup.py <bucket> <key>
        main(args.source, args.key)
    else:
        # New mode: setup.py <source>
        main_auto(args.source)
