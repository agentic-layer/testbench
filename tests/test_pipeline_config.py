import pytest
import yaml

from testbench.schema.config import PipelineConfig


class TestPipelineConfigUrlSource:
    def test_valid_url_source(self, tmp_path):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "url"
        assert config.dataset.url == "https://example.com/dataset.csv"
        assert config.agent.url == "https://my-agent.example.com"
        assert config.evaluate.model is None
        assert config.experiment.name == "test-experiment"

    def test_url_source_missing_url_field(self):
        config_dict = {
            "dataset": {"source": "url"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="url"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigFileSource:
    def test_valid_file_source(self):
        config_dict = {
            "dataset": {"source": "file", "path": "./data/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "file"
        assert config.dataset.path == "./data/dataset.csv"

    def test_file_source_missing_path_field(self):
        config_dict = {
            "dataset": {"source": "file"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="path"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigS3Source:
    def test_valid_s3_source(self):
        config_dict = {
            "dataset": {
                "source": "s3",
                "bucket": "datasets",
                "key": "dataset.csv",
            },
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "s3"
        assert config.dataset.bucket == "datasets"
        assert config.dataset.key == "dataset.csv"

    def test_s3_source_missing_bucket(self):
        config_dict = {
            "dataset": {"source": "s3", "key": "dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="bucket"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigInlineSource:
    def _inline_dataset(self) -> dict:
        return {
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
        }

    def test_valid_inline_source(self):
        config_dict = {
            "dataset": {"source": "inline", "inline": self._inline_dataset()},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "inline"
        assert config.dataset.inline is not None
        assert config.dataset.inline.llm_as_a_judge_model == "gemini-2.5-flash-lite"
        assert config.dataset.inline.scenarios[0].name == "Weather in New York"
        assert config.dataset.inline.scenarios[0].steps[0].input == "What is the weather like in New York right now?"

    def test_inline_source_missing_inline_field(self):
        config_dict = {
            "dataset": {"source": "inline"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="inline"):
            PipelineConfig.model_validate(config_dict)

    def test_inline_source_validates_nested_experiment(self):
        bad = self._inline_dataset()
        bad["scenarios"] = [{"name": "Missing steps"}]
        config_dict = {
            "dataset": {"source": "inline", "inline": bad},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="steps"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigOptionalFields:
    def test_with_evaluate_model(self):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "evaluate": {"model": "gemini-2.5-flash-lite"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.evaluate.model == "gemini-2.5-flash-lite"

    def test_execution_id_defaults_to_auto(self):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.workflow.execution_id == "auto"
        assert config.workflow.execution_number == 1

    def test_valid_experiment_source(self):
        config_dict = {
            "dataset": {"source": "experiment", "path": "./data/experiment.json"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "experiment"
        assert config.dataset.path == "./data/experiment.json"

    def test_experiment_source_missing_path(self):
        config_dict = {
            "dataset": {"source": "experiment"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="path"):
            PipelineConfig.model_validate(config_dict)

    def test_invalid_source_type(self):
        config_dict = {
            "dataset": {"source": "ftp", "url": "ftp://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "experiment": {"name": "test-experiment"},
        }
        with pytest.raises(ValueError, match="Input should be"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigFromYaml:
    def test_load_from_yaml_file(self, tmp_path):
        yaml_content = """
dataset:
  source: url
  url: https://example.com/dataset.csv
agent:
  url: https://my-agent.example.com
evaluate:
  model: gemini-2.5-flash-lite
experiment:
  name: my-evaluation
"""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml_content)

        with open(config_file) as f:
            raw = yaml.safe_load(f)
        config = PipelineConfig.model_validate(raw)

        assert config.dataset.source == "url"
        assert config.dataset.url == "https://example.com/dataset.csv"
        assert config.evaluate.model == "gemini-2.5-flash-lite"
        assert config.experiment.name == "my-evaluation"
