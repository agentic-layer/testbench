import pytest
import yaml
from schema.config import PipelineConfig


class TestPipelineConfigUrlSource:
    def test_valid_url_source(self, tmp_path):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "url"
        assert config.dataset.url == "https://example.com/dataset.csv"
        assert config.agent.url == "https://my-agent.example.com"
        assert config.evaluate.model is None
        assert config.otlp is None
        assert config.workflow.name == "test-workflow"

    def test_url_source_missing_url_field(self):
        config_dict = {
            "dataset": {"source": "url"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        with pytest.raises(ValueError, match="url"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigFileSource:
    def test_valid_file_source(self):
        config_dict = {
            "dataset": {"source": "file", "path": "./data/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "file"
        assert config.dataset.path == "./data/dataset.csv"

    def test_file_source_missing_path_field(self):
        config_dict = {
            "dataset": {"source": "file"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
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
                "endpoint": "http://minio:9000",
            },
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "s3"
        assert config.dataset.bucket == "datasets"
        assert config.dataset.key == "dataset.csv"
        assert config.dataset.endpoint == "http://minio:9000"

    def test_s3_source_missing_bucket(self):
        config_dict = {
            "dataset": {"source": "s3", "key": "dataset.csv", "endpoint": "http://minio:9000"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        with pytest.raises(ValueError, match="bucket"):
            PipelineConfig.model_validate(config_dict)


class TestPipelineConfigOptionalFields:
    def test_with_evaluate_model(self):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "evaluate": {"model": "gemini-2.5-flash-lite"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.evaluate.model == "gemini-2.5-flash-lite"

    def test_with_otlp_endpoint(self):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "otlp": {"endpoint": "https://otlp.grafana.net/otlp"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.otlp is not None
        assert config.otlp.endpoint == "https://otlp.grafana.net/otlp"

    def test_execution_id_defaults_to_auto(self):
        config_dict = {
            "dataset": {"source": "url", "url": "https://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.workflow.execution_id == "auto"
        assert config.workflow.execution_number == 1

    def test_valid_experiment_source(self):
        config_dict = {
            "dataset": {"source": "experiment", "path": "./data/experiment.json"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        config = PipelineConfig.model_validate(config_dict)
        assert config.dataset.source == "experiment"
        assert config.dataset.path == "./data/experiment.json"

    def test_experiment_source_missing_path(self):
        config_dict = {
            "dataset": {"source": "experiment"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
        }
        with pytest.raises(ValueError, match="path"):
            PipelineConfig.model_validate(config_dict)

    def test_invalid_source_type(self):
        config_dict = {
            "dataset": {"source": "ftp", "url": "ftp://example.com/dataset.csv"},
            "agent": {"url": "https://my-agent.example.com"},
            "workflow": {"name": "test-workflow"},
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
workflow:
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
        assert config.workflow.name == "my-evaluation"
