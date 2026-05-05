from unittest.mock import AsyncMock, patch

import pytest
import yaml
from pipeline import run_pipeline


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
    @patch("pipeline.visualize_main")
    @patch("pipeline.evaluate_main", new_callable=AsyncMock)
    @patch("pipeline.run_main", new_callable=AsyncMock)
    @patch("pipeline.setup_phase")
    def test_runs_all_phases_without_otlp(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, monkeypatch, config_file
    ):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        run_pipeline(config_file)

        mock_setup.assert_called_once()
        mock_run.assert_called_once()
        mock_evaluate.assert_called_once()
        mock_visualize.assert_called_once()

    @patch("pipeline.publish_metrics")
    @patch("pipeline.visualize_main")
    @patch("pipeline.evaluate_main", new_callable=AsyncMock)
    @patch("pipeline.run_main", new_callable=AsyncMock)
    @patch("pipeline.setup_phase")
    def test_runs_publish_when_otlp_env_set(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, mock_publish, monkeypatch, config_file
    ):
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otlp.example.com")

        run_pipeline(config_file)

        mock_publish.assert_called_once()

    @patch("pipeline.visualize_main")
    @patch("pipeline.evaluate_main", new_callable=AsyncMock)
    @patch("pipeline.run_main", new_callable=AsyncMock)
    @patch("pipeline.setup_phase")
    def test_skips_publish_when_no_otlp(
        self, mock_setup, mock_run, mock_evaluate, mock_visualize, monkeypatch, config_file
    ):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        with patch("pipeline.publish_metrics") as mock_publish:
            run_pipeline(config_file)
            mock_publish.assert_not_called()

    def test_invalid_config_raises(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.dump({"dataset": {"source": "url"}}))

        with pytest.raises(SystemExit):
            run_pipeline(str(config_path))

    @patch("pipeline.visualize_main")
    @patch("pipeline.evaluate_main", new_callable=AsyncMock)
    @patch("pipeline.run_main", new_callable=AsyncMock)
    @patch("pipeline.setup_phase")
    def test_passes_evaluate_model_override(self, mock_setup, mock_run, mock_evaluate, mock_visualize, tmp_path):
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
