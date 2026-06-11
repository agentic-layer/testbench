from unittest.mock import AsyncMock, patch

import pytest
import yaml

from testbench.schema.config import PipelineConfig
from testbench.testworkflow import run_pipeline, setup_phase


@pytest.fixture
def minimal_config(tmp_path):
    return {
        "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
        "agent": {"url": "https://my-agent.example.com"},
        "experiment": {"name": "test-workflow"},
    }


@pytest.fixture
def config_file(tmp_path, minimal_config):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(minimal_config))
    return str(config_path)


class TestRunPipeline:
    @patch("testbench.testworkflow.check_evaluations", return_value=0)
    @patch("testbench.testworkflow.visualize_main")
    @patch("testbench.testworkflow.evaluate_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.run_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.setup_phase")
    def test_runs_all_phases_without_otlp(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, mock_check, monkeypatch, config_file
    ):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        run_pipeline(config_file)

        mock_setup.assert_called_once()
        mock_run.assert_called_once()
        mock_evaluate.assert_called_once()
        mock_visualize.assert_called_once()

    @patch("testbench.testworkflow.check_evaluations", return_value=0)
    @patch("testbench.testworkflow.publish_metrics")
    @patch("testbench.testworkflow.visualize_main")
    @patch("testbench.testworkflow.evaluate_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.run_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.setup_phase")
    def test_runs_publish_when_otlp_env_set(
        self,
        mock_setup,
        mock_run,
        mock_evaluate,
        mock_visualize,
        mock_publish,
        mock_check,
        monkeypatch,
        config_file,
    ):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.example.com")

        run_pipeline(config_file)

        mock_publish.assert_called_once()

    @patch("testbench.testworkflow.check_evaluations", return_value=0)
    @patch("testbench.testworkflow.visualize_main")
    @patch("testbench.testworkflow.evaluate_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.run_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.setup_phase")
    def test_skips_publish_when_no_otlp(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, mock_check, monkeypatch, config_file
    ):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        with patch("testbench.testworkflow.publish_metrics") as mock_publish:
            run_pipeline(config_file)
            mock_publish.assert_not_called()

    def test_invalid_config_raises(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"dataset": {"source": "url"}}))

        with pytest.raises(SystemExit):
            run_pipeline(str(config_path))

    @patch("testbench.testworkflow.check_evaluations", return_value=0)
    @patch("testbench.testworkflow.visualize_main")
    @patch("testbench.testworkflow.evaluate_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.run_main", new_callable=AsyncMock)
    @patch("testbench.testworkflow.setup_phase")
    def test_passes_evaluate_model_override(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, mock_check, tmp_path
    ):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "evaluate": {"model": "gemini-2.5-flash-lite"},
            "experiment": {"name": "test-workflow"},
        }
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump(config_dict))

        run_pipeline(str(config_path))

        # Check that evaluate_main was called with the model override
        call_args = mock_evaluate.call_args
        assert call_args[0][2] == "gemini-2.5-flash-lite"


class TestSetupPhaseInline:
    def _config(self) -> PipelineConfig:
        return PipelineConfig.model_validate(
            {
                "dataset": {
                    "source": "inline",
                    "inline": {
                        "llm_as_a_judge_model": "gemini-2.5-flash-lite",
                        "default_threshold": 0.9,
                        "scenarios": [
                            {
                                "name": "Weather in New York",
                                "steps": [
                                    {
                                        "input": "What is the weather like in New York right now?",
                                        "metrics": [{"metric_name": "AgentGoalAccuracyWithoutReference"}],
                                    }
                                ],
                            }
                        ],
                    },
                },
                "agent": {"url": "https://my-agent.example.com"},
                "experiment": {"name": "test-experiment"},
            }
        )

    @patch("testbench.testworkflow.save_experiment")
    @patch("testbench.testworkflow.load_experiment_from_url")
    @patch("testbench.testworkflow.load_experiment_from_file")
    @patch("testbench.testworkflow.load_experiment_from_s3")
    def test_inline_skips_loaders_and_saves_directly(self, mock_s3, mock_file, mock_url, mock_save):
        config = self._config()

        setup_phase(config)

        mock_url.assert_not_called()
        mock_file.assert_not_called()
        mock_s3.assert_not_called()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved is config.dataset.inline
        assert saved.scenarios[0].name == "Weather in New York"
