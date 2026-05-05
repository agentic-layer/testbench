"""Unit tests for setup.py.

Verifies S3 download, format parsing (JSON/YAML), Experiment validation,
and saving to data/datasets/experiment.json.
"""

import json
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from setup import (
    EXPERIMENT_OUTPUT_PATH,
    load_experiment_from_file,
    load_experiment_from_s3,
    load_experiment_from_url,
    main,
    parse_experiment,
    save_experiment,
)

VALID_EXPERIMENT_DICT = {
    "scenarios": [
        {
            "name": "scenario-1",
            "steps": [
                {"input": "What is AI?"},
            ],
        }
    ]
}


@pytest.fixture
def temp_cwd():
    tmp = tempfile.mkdtemp()
    original_cwd = Path.cwd()
    os.chdir(tmp)
    try:
        yield Path(tmp)
    finally:
        os.chdir(original_cwd)
        shutil.rmtree(tmp, ignore_errors=True)


class TestParseExperiment:
    def test_parses_json(self):
        content = json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8")
        experiment = parse_experiment(content, "data.json")
        assert experiment.scenarios[0].name == "scenario-1"
        assert experiment.scenarios[0].steps[0].input == "What is AI?"

    def test_yaml_format_rejected(self):
        with pytest.raises(ValueError, match="Unsupported filetype"):
            parse_experiment(b"scenarios: []", "data.yaml")

    def test_csv_format_rejected(self):
        with pytest.raises(ValueError, match="Unsupported filetype"):
            parse_experiment(b"input,reference\nfoo,bar", "data.csv")

    def test_invalid_experiment_raises(self):
        bad = json.dumps({"scenarios": [{"name": "s1"}]}).encode("utf-8")  # missing steps
        with pytest.raises(ValueError, match="validation failed"):
            parse_experiment(bad, "data.json")

    def test_malformed_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_experiment(b"{not json", "data.json")


class TestSaveExperiment:
    def test_writes_default_path(self, temp_cwd):
        experiment = parse_experiment(json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8"), "x.json")
        save_experiment(experiment)
        assert EXPERIMENT_OUTPUT_PATH.exists()
        saved = json.loads(EXPERIMENT_OUTPUT_PATH.read_text())
        assert saved["scenarios"][0]["name"] == "scenario-1"

    def test_writes_custom_path(self, temp_cwd):
        experiment = parse_experiment(json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8"), "x.json")
        out = temp_cwd / "custom" / "out.json"
        save_experiment(experiment, out)
        assert out.exists()


class TestLoadExperimentFromUrl:
    def test_downloads_and_parses_json(self):
        content = json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = content
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("setup.urllib.request.urlopen", return_value=mock_response):
            experiment = load_experiment_from_url("https://example.com/exp.json")
            assert experiment.scenarios[0].name == "scenario-1"

    def test_strips_query_string_for_suffix(self):
        content = json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = content
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("setup.urllib.request.urlopen", return_value=mock_response):
            experiment = load_experiment_from_url("https://example.com/exp.json?token=abc")
            assert experiment.scenarios[0].steps[0].input == "What is AI?"


class TestLoadExperimentFromFile:
    def test_load_json(self, tmp_path):
        path = tmp_path / "exp.json"
        path.write_text(json.dumps(VALID_EXPERIMENT_DICT))
        experiment = load_experiment_from_file(str(path))
        assert experiment.scenarios[0].name == "scenario-1"

    def test_unsupported_raises(self, tmp_path):
        path = tmp_path / "exp.csv"
        path.write_text("foo,bar")
        with pytest.raises(ValueError, match="Unsupported"):
            load_experiment_from_file(str(path))


class TestLoadExperimentFromS3:
    def test_downloads_and_parses(self, monkeypatch):
        content = json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8")

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(content)}

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        experiment = load_experiment_from_s3("bucket", "exp.json")
        assert experiment.scenarios[0].name == "scenario-1"

    def test_propagates_s3_error(self, monkeypatch):
        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                raise Exception("NoSuchKey")

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        with pytest.raises(Exception, match="NoSuchKey"):
            load_experiment_from_s3("bucket", "missing.json")


class TestMain:
    def test_main_with_json_from_s3(self, temp_cwd, monkeypatch):
        content = json.dumps(VALID_EXPERIMENT_DICT).encode("utf-8")

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(content)}

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        main("test-bucket", "data.json")
        assert EXPERIMENT_OUTPUT_PATH.exists()
        saved = json.loads(EXPERIMENT_OUTPUT_PATH.read_text())
        assert saved["scenarios"][0]["name"] == "scenario-1"

    def test_main_with_invalid_s3_key(self, temp_cwd, monkeypatch):
        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                raise Exception("NoSuchKey: The specified key does not exist")

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        with pytest.raises(Exception, match="NoSuchKey"):
            main("test-bucket", "nonexistent.json")

    def test_main_rejects_unsupported_format(self, temp_cwd, monkeypatch):
        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(b"foo,bar")}

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        with pytest.raises(ValueError, match="Unsupported"):
            main("test-bucket", "data.csv")

    def test_main_rejects_invalid_experiment(self, temp_cwd, monkeypatch):
        bad = json.dumps({"scenarios": [{"name": "s1"}]}).encode("utf-8")  # missing steps

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(bad)}

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        with pytest.raises(ValueError, match="validation failed"):
            main("test-bucket", "data.json")
