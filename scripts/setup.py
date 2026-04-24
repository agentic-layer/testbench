"""Download dataset from S3/MinIO, convert to Experiment JSON, and save.

Phase 1 of the evaluation pipeline. Downloads a dataset file (CSV, JSON,
or Parquet) from S3/MinIO and converts it into an ``Experiment`` JSON file
that subsequent phases can consume.

Usage::

    python3 scripts/setup.py <bucket> <key>
"""

import argparse
import logging
import os
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import boto3
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


def load_dataframe_from_url(url: str) -> DataFrame:
    """Download a dataset file from a URL and return as a DataFrame.

    Args:
        url: HTTP(S) URL to the dataset file (CSV, JSON, or Parquet).

    Returns:
        Pandas DataFrame with the dataset content.
    """
    suffix = Path(url.split("?")[0]).suffix.lower()
    converter = get_converter(f"file{suffix}")

    logger.info("Downloading dataset from %s...", url)
    with urllib.request.urlopen(url) as response:  # noqa: S310  # nosec B310
        file_content = response.read()
    logger.info("Downloaded %d bytes", len(file_content))

    return converter(BytesIO(file_content))


def load_dataframe_from_file(file_path: str) -> DataFrame:
    """Load a dataset file from a local path and return as a DataFrame.

    Args:
        file_path: Local path to the dataset file (CSV, JSON, or Parquet).

    Returns:
        Pandas DataFrame with the dataset content.
    """
    path = Path(file_path)
    converter = get_converter(path.name)

    logger.info("Loading dataset from %s...", file_path)
    with open(path, "rb") as f:
        file_content = f.read()
    logger.info("Loaded %d bytes", len(file_content))

    return converter(BytesIO(file_content))


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download dataset from S3/MinIO -> convert to Experiment JSON -> save to data/datasets/experiment.json"
    )
    parser.add_argument(
        "bucket",
        type=str,
        help="S3/MinIO bucket name containing the dataset",
    )
    parser.add_argument(
        "key",
        type=str,
        help="S3/MinIO object key (path to dataset file in .csv / .json / .parquet format)",
    )
    args = parser.parse_args()

    main(args.bucket, args.key)
