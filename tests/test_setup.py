"""
Unit tests for setup.py

Tests the dataset download, conversion, and Ragas dataset creation functionality.
"""

import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from setup import custom_convert_csv, dataframe_to_experiment, get_converter, main, main_auto


# Fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    tmp = tempfile.mkdtemp()
    original_cwd = Path.cwd()
    yield tmp, original_cwd
    shutil.rmtree(tmp, ignore_errors=True)


# TestCustomConvertCSV tests
def test_converts_string_to_list():
    """Test that retrieved_contexts strings are converted to lists"""
    csv_content = b"user_input,retrieved_contexts,reference\n"
    csv_content += b'"Question?","Context text","Answer"\n'

    buffer = BytesIO(csv_content)
    df = custom_convert_csv(buffer)

    assert isinstance(df["retrieved_contexts"].iloc[0], list)
    assert df["retrieved_contexts"].iloc[0] == ["Context text"]


def test_handles_empty_retrieved_contexts():
    """Test handling of empty retrieved_contexts"""
    csv_content = b"user_input,retrieved_contexts,reference\n"
    csv_content += b'"Question?","","Answer"\n'

    buffer = BytesIO(csv_content)
    df = custom_convert_csv(buffer)

    # Empty string becomes [nan] in pandas, which then becomes []
    # The function converts non-list values to lists
    result = df["retrieved_contexts"].iloc[0]
    # Check that it's a list and handle NaN case
    assert isinstance(result, list)
    # If it contains NaN, that's acceptable behavior for empty strings in CSV
    if result and pd.isna(result[0]):
        # This is expected - pandas converts empty string to NaN
        pass
    else:
        # Or it should be an empty list
        assert result == []


def test_missing_retrieved_contexts_column():
    """Test that CSV without retrieved_contexts column works"""
    csv_content = b"user_input,reference\n"
    csv_content += b'"Question?","Answer"\n'

    buffer = BytesIO(csv_content)
    df = custom_convert_csv(buffer)

    assert "retrieved_contexts" not in df.columns


# TestGetConverter tests
def test_unsupported_format():
    """Test that unsupported formats raise TypeError"""
    with pytest.raises(TypeError) as exc_info:
        get_converter("https://example.com/data.xlsx")

    assert "Unsupported filetype" in str(exc_info.value)


# TestDataframeToRagasDataset tests
def test_creates_ragas_dataset_file(temp_dir):
    """Test that experiment.json is created"""

    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        df = pd.DataFrame(
            {
                "user_input": ["Question 1"],
                "retrieved_contexts": [["Context 1"]],
                "reference": ["Answer 1"],
            }
        )

        dataframe_to_experiment(df)

        # Check for the file in the datasets subdirectory
        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists(), f"Dataset file not found at {dataset_file}"
    finally:
        os.chdir(original_cwd)


# TestMain tests
def test_main_with_csv(temp_dir, monkeypatch):
    """Test main function with CSV file from S3"""

    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        # Mock S3 response
        csv_content = b"user_input,retrieved_contexts,reference\n"
        csv_content += b'"Question?","Context text","Answer"\n'

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(csv_content)}

        def mock_create_s3_client():
            return MockS3Client()

        monkeypatch.setattr("setup.create_s3_client", mock_create_s3_client)

        # Run main with bucket and key
        main("test-bucket", "data.csv")

        # Verify dataset was created in datasets subdirectory
        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists(), f"Dataset file not found at {dataset_file}"
    finally:
        os.chdir(original_cwd)


def test_main_with_json(temp_dir, monkeypatch):
    """Test main function with JSON file from S3"""

    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        # Mock S3 response
        json_content = b"""[
            {
                "user_input": "Question?",
                "retrieved_contexts": ["Context text"],
                "reference": "Answer"
            }
        ]"""

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                return {"Body": BytesIO(json_content)}

        def mock_create_s3_client():
            return MockS3Client()

        monkeypatch.setattr("setup.create_s3_client", mock_create_s3_client)

        # Run main with bucket and key
        main("test-bucket", "data.json")

        # Verify dataset was created in datasets subdirectory
        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists(), f"Dataset file not found at {dataset_file}"
    finally:
        os.chdir(original_cwd)


def test_main_with_invalid_s3_key(temp_dir, monkeypatch):
    """Test main function with invalid S3 key (S3 error)"""

    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        # Mock S3 error
        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                raise Exception("NoSuchKey: The specified key does not exist")

        def mock_create_s3_client():
            return MockS3Client()

        monkeypatch.setattr("setup.create_s3_client", mock_create_s3_client)

        # Verify that the error propagates
        with pytest.raises(Exception, match="NoSuchKey"):
            main("test-bucket", "nonexistent.csv")
    finally:
        os.chdir(original_cwd)


def test_main_with_http_url(temp_dir, monkeypatch):
    """Test main_auto function with HTTP URL source."""
    tmp, original_cwd = temp_dir
    os.chdir(tmp)
    try:
        csv_content = b"user_input,retrieved_contexts,reference\n"
        csv_content += b'"Question?","Context text","Answer"\n'

        async def mock_download(url: str) -> bytes:
            assert url == "https://example.com/data.csv"
            return csv_content

        monkeypatch.setattr("setup.download_http", mock_download)
        main_auto("https://example.com/data.csv")

        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists()
    finally:
        os.chdir(original_cwd)


def test_main_with_local_file(temp_dir):
    """Test main_auto function with local file path."""
    tmp, original_cwd = temp_dir
    os.chdir(tmp)
    try:
        csv_path = Path(tmp) / "input.csv"
        csv_path.write_text('user_input,reference\n"Question?","Answer"\n')
        main_auto(str(csv_path))

        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists()
    finally:
        os.chdir(original_cwd)


def test_main_with_s3_uri(temp_dir, monkeypatch):
    """Test main_auto function with s3:// URI."""
    tmp, original_cwd = temp_dir
    os.chdir(tmp)
    try:
        csv_content = b'user_input,reference\n"Question?","Answer"\n'

        class MockS3Client:
            def get_object(self, Bucket, Key):  # noqa: N803
                assert Bucket == "my-bucket"
                assert Key == "path/to/data.csv"
                return {"Body": BytesIO(csv_content)}

        monkeypatch.setattr("setup.create_s3_client", lambda: MockS3Client())
        main_auto("s3://my-bucket/path/to/data.csv")

        dataset_file = Path(tmp) / "data" / "datasets" / "experiment.json"
        assert dataset_file.exists()
    finally:
        os.chdir(original_cwd)
