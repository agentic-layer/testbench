"""Standalone pipeline runner - replicates the Testkube TestWorkflow without Kubernetes.

Reads a config.yaml file, validates it, and runs the full evaluation pipeline:
setup -> run -> evaluate -> [publish] -> visualize.

Usage::

    python3 scripts/pipeline.py config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import time
import uuid

import yaml
from evaluate import main as evaluate_main
from publish import publish_metrics
from run import main as run_main
from schema.config import PipelineConfig
from setup import dataframe_to_experiment, load_dataframe_from_file, load_dataframe_from_url
from setup import main as setup_s3_main
from visualize import main as visualize_main

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Output paths (same as existing pipeline)
EXPERIMENT_PATH = "data/datasets/experiment.json"
EXECUTED_PATH = "data/experiments/executed_experiment.json"
EVALUATED_PATH = "data/experiments/evaluated_experiment.json"
REPORT_PATH = "data/results/evaluation_report.html"


def _resolve_execution_id(execution_id: str) -> str:
    """Resolve 'auto' execution_id to GITHUB_RUN_ID or a generated UUID."""
    if execution_id != "auto":
        return execution_id
    github_run_id = os.environ.get("GITHUB_RUN_ID")
    if github_run_id:
        return github_run_id
    return str(uuid.uuid4())


def _resolve_execution_number(execution_number: int) -> int:
    """Use GITHUB_RUN_NUMBER if execution_number is default (1)."""
    github_run_number = os.environ.get("GITHUB_RUN_NUMBER")
    if execution_number == 1 and github_run_number:
        return int(github_run_number)
    return execution_number


def setup_phase(config: PipelineConfig) -> None:
    """Phase 1: Resolve dataset and convert to Experiment JSON."""
    source = config.dataset.source

    if source == "url":
        # Pydantic validator guarantees url is set when source=url
        df = load_dataframe_from_url(config.dataset.url)  # type: ignore[arg-type]
        dataframe_to_experiment(df)
    elif source == "file":
        # Pydantic validator guarantees path is set when source=file
        df = load_dataframe_from_file(config.dataset.path)  # type: ignore[arg-type]
        dataframe_to_experiment(df)
    elif source == "experiment":
        # Pre-built experiment.json — copy directly to expected path
        from pathlib import Path

        output_path = Path(EXPERIMENT_PATH)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.dataset.path, output_path)  # type: ignore[arg-type]
        logger.info("[setup] Copied experiment from %s", config.dataset.path)
    elif source == "s3":
        # Pydantic validator guarantees bucket, key, endpoint are set when source=s3
        if config.dataset.endpoint:
            os.environ.setdefault("MINIO_ENDPOINT", config.dataset.endpoint)
        setup_s3_main(config.dataset.bucket, config.dataset.key)  # type: ignore[arg-type]


def run_pipeline(config_path: str) -> None:
    """Load config and run the full pipeline."""
    # Load and validate config
    logger.info("[pipeline] Loading config from %s", config_path)
    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
        config = PipelineConfig.model_validate(raw)
    except Exception as e:
        logger.error("[pipeline] Config validation failed: %s", e)
        sys.exit(1)

    # Resolve workflow metadata
    execution_id = _resolve_execution_id(config.workflow.execution_id)
    execution_number = _resolve_execution_number(config.workflow.execution_number)
    workflow_name = config.workflow.name

    logger.info(
        "[pipeline] Workflow: %s (execution_id=%s, execution_number=%d)",
        workflow_name,
        execution_id,
        execution_number,
    )

    # Set OTLP endpoint if configured (used by run.py for tracing)
    if config.otlp:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.otlp.endpoint
        logger.info("[pipeline] OTLP endpoint: %s", config.otlp.endpoint)
    else:
        logger.info("[pipeline] No OTLP endpoint configured - tracing and publish will be skipped")

    # Phase 1: Setup
    logger.info("[setup] Starting dataset setup...")
    start = time.time()
    setup_phase(config)
    logger.info("[setup] Completed in %.1fs", time.time() - start)

    # Phase 2: Run
    logger.info("[run] Starting agent execution...")
    start = time.time()
    asyncio.run(run_main(config.agent.url, workflow_name, EXPERIMENT_PATH))
    logger.info("[run] Completed in %.1fs", time.time() - start)

    # Phase 3: Evaluate
    logger.info("[evaluate] Starting metric evaluation...")
    start = time.time()
    asyncio.run(evaluate_main(EXECUTED_PATH, EVALUATED_PATH, config.evaluate.model))
    logger.info("[evaluate] Completed in %.1fs", time.time() - start)

    # Phase 4: Publish (conditional)
    if config.otlp:
        logger.info("[publish] Starting metrics publishing...")
        start = time.time()
        publish_metrics(EVALUATED_PATH, workflow_name, execution_id, execution_number)
        logger.info("[publish] Completed in %.1fs", time.time() - start)

    # Phase 5: Visualize
    logger.info("[visualize] Generating HTML report...")
    start = time.time()
    visualize_main(EVALUATED_PATH, REPORT_PATH, workflow_name, execution_id, execution_number)
    logger.info("[visualize] Completed in %.1fs", time.time() - start)

    logger.info("[pipeline] Pipeline completed successfully")
    logger.info("[pipeline] Report: %s", REPORT_PATH)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the testbench evaluation pipeline without Kubernetes or Testkube")
    parser.add_argument(
        "config",
        help="Path to config.yaml file",
    )
    args = parser.parse_args()

    run_pipeline(args.config)
