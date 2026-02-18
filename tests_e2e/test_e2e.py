"""
End-to-end test that runs all scripts in the correct order:
1. setup.py - Downloads, converts and saves Experiment to data/datasets/experiment.json
2. run.py - Runs agent queries and saves ExecutedExperiment to data/experiments/executed_experiment.json
3. evaluate.py - Evaluates results and saves EvaluatedExperiment to data/experiments/evaluated_experiment.json
4. publish.py - Publishes metrics via OpenTelemetry OTLP

Usage:
    pytest tests_e2e/test_e2e.py

    # With custom configuration via environment variables:
    E2E_DATASET_URL="http://localhost:11020/dataset.csv" \
    E2E_AGENT_URL="http://localhost:8000" \
    E2E_MODEL="gemini-flash-latest" \
    E2E_WORKFLOW_NAME="weather-assistant-test" \
    pytest tests_e2e/test_e2e.py
"""

import logging
import os
import subprocess  # nosec
from pathlib import Path
from typing import List

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class E2ETestRunner:
    """Manages the end-to-end test execution pipeline."""

    def __init__(
        self,
        dataset_url: str,
        agent_url: str,
        model: str,
        workflow_name: str,
        otlp_endpoint: str = "localhost:4318",
    ):
        self.dataset_url = dataset_url
        self.agent_url = agent_url
        self.model = model
        self.workflow_name = workflow_name
        self.otlp_endpoint = otlp_endpoint

        # Define script paths
        self.scripts_dir = Path(__file__).parent.parent / "testbench"
        self.setup_script = self.scripts_dir / "setup.py"
        self.run_script = self.scripts_dir / "run.py"
        self.evaluate_script = self.scripts_dir / "evaluate.py"
        self.publish_script = self.scripts_dir / "publish.py"

        # Define expected output files
        self.dataset_file = Path("./data/datasets/experiment.json")
        self.executed_file = Path("./data/experiments/executed_experiment.json")
        self.evaluated_file = Path("./data/experiments/evaluated_experiment.json")

    def verify_scripts_exist(self) -> bool:
        """Verify that all required scripts exist."""
        logger.info("Verifying all scripts exist...")
        scripts = [
            self.setup_script,
            self.run_script,
            self.evaluate_script,
            self.publish_script,
        ]

        missing_scripts = [script for script in scripts if not script.exists()]

        if missing_scripts:
            logger.error("Missing scripts:")
            for script in missing_scripts:
                logger.error(f"  - {script}")
            return False

        logger.info("All scripts found")
        return True

    def run_command(self, command: List[str], step_name: str, env: dict | None = None) -> bool:
        """
        Run a command and handle output/errors.

        Args:
            command: List of command arguments
            step_name: Name of the step for logging
            env: Optional environment variables to pass to the command

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Step: {step_name}")
        logger.info(f"Command: {' '.join(command)}")
        logger.info(f"{'=' * 60}\n")

        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, env=env)  # nosec

            if result.stdout:
                logger.info("Output:")
                for line in result.stdout.strip().split("\n"):
                    logger.info(f"  {line}")

            logger.info(f"{step_name} completed successfully\n")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"{step_name} failed with exit code {e.returncode}")

            if e.stdout:
                logger.error("Standard output:")
                for line in e.stdout.strip().split("\n"):
                    logger.error(f"  {line}")

            if e.stderr:
                logger.error("Error output:")
                for line in e.stderr.strip().split("\n"):
                    logger.error(f"  {line}")

            return False

        except Exception as e:
            logger.error(f"Unexpected error in {step_name}: {e}")
            return False

    def verify_file_exists(self, file_path: Path, step_name: str) -> bool:
        """Verify that an expected output file was created."""
        if file_path.exists():
            logger.info(f"Verified {file_path} was created by {step_name}")
            return True
        else:
            logger.error(f"Expected file {file_path} not found after {step_name}")
            return False

    def run_setup(self) -> bool:
        """Run setup.py to download and convert dataset."""
        command = ["python3", str(self.setup_script), self.dataset_url]
        success = self.run_command(command, "1. Setup - Download Dataset")

        if success:
            return self.verify_file_exists(self.dataset_file, "setup.py")
        return False

    def run_agent_queries(self) -> bool:
        """Run run.py to execute agent queries on the dataset."""
        command = ["python3", str(self.run_script), self.agent_url, self.workflow_name]
        success = self.run_command(command, "2. Run - Execute Agent Queries")

        if success:
            return self.verify_file_exists(self.executed_file, "run.py")
        return False

    def run_evaluation(self) -> bool:
        """Run evaluate.py to evaluate results using metrics."""
        command = ["python3", str(self.evaluate_script), "--model", self.model]
        success = self.run_command(command, "3. Evaluate - Calculate Metrics")

        if success:
            return self.verify_file_exists(self.evaluated_file, "evaluate.py")
        return False

    def run_publish(self) -> bool:
        """Run publish.py to publish metrics via OpenTelemetry OTLP."""
        env = os.environ.copy()
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = self.otlp_endpoint

        command = [
            "python3",
            str(self.publish_script),
            self.workflow_name,
            "e2e-test-exec",  # execution_id
            "1",  # execution_number
        ]
        return self.run_command(command, "4. Publish - Push Metrics via OTLP", env=env)

    def run_full_pipeline(self) -> bool:
        """Execute the complete E2E test pipeline."""
        logger.info("\n" + "=" * 60)
        logger.info("Starting E2E Test Pipeline")
        logger.info("=" * 60 + "\n")

        if not self.verify_scripts_exist():
            logger.error("Cannot proceed - missing required scripts")
            return False

        steps = [
            ("Setup", self.run_setup),
            ("Run", self.run_agent_queries),
            ("Evaluate", self.run_evaluation),
            ("Publish", self.run_publish),
        ]

        for step_name, step_func in steps:
            if not step_func():
                logger.error(f"\n{'=' * 60}")
                logger.error(f"E2E Test FAILED at step: {step_name}")
                logger.error(f"{'=' * 60}\n")
                return False

        logger.info("\n" + "=" * 60)
        logger.info("E2E Test Pipeline COMPLETED SUCCESSFULLY")
        logger.info("=" * 60 + "\n")

        logger.info("Summary:")
        logger.info(f"  Dataset created: {self.dataset_file}")
        logger.info(f"  Executed experiment: {self.executed_file}")
        logger.info(f"  Evaluated experiment: {self.evaluated_file}")
        logger.info(f"  Metrics published to: {self.otlp_endpoint}")
        logger.info(f"  Workflow name: {self.workflow_name}")

        return True


def test_e2e_pipeline():
    """Pytest test function for the E2E pipeline.

    This test can be run with pytest and uses environment variables or defaults
    for configuration. To customize, set these environment variables:
    - E2E_DATASET_URL
    - E2E_AGENT_URL
    - E2E_MODEL
    - E2E_WORKFLOW_NAME
    - E2E_OTLP_ENDPOINT

    Example:
        E2E_DATASET_URL="https://example.com/data.csv" pytest tests_e2e/test_e2e.py
    """

    dataset_url = os.getenv("E2E_DATASET_URL", "http://localhost:11020/dataset.csv")
    agent_url = os.getenv("E2E_AGENT_URL", "http://localhost:11010")
    model = os.getenv("E2E_MODEL", "gemini-2.5-flash-lite")
    workflow_name = os.getenv("E2E_WORKFLOW_NAME", "Test Workflow")
    otlp_endpoint = os.getenv("E2E_OTLP_ENDPOINT", "localhost:4318")

    runner = E2ETestRunner(
        dataset_url=dataset_url,
        agent_url=agent_url,
        model=model,
        workflow_name=workflow_name,
        otlp_endpoint=otlp_endpoint,
    )

    success = runner.run_full_pipeline()

    assert success, "E2E pipeline failed - check logs above for details"
