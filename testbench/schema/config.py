"""Pipeline configuration model for config.yaml validation."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, model_validator

from testbench.schema.models import Experiment


class DatasetConfig(BaseModel):
    """Dataset source configuration."""

    source: Literal["url", "file", "s3", "experiment", "inline"]
    url: str | None = None
    path: str | None = None
    bucket: str | None = None
    key: str | None = None
    inline: Experiment | None = None

    @model_validator(mode="after")
    def validate_source_fields(self) -> Self:
        """Ensure required fields are present for the chosen source type."""
        if self.source == "url" and not self.url:
            raise ValueError("'url' field is required when source is 'url'")
        if self.source == "file" and not self.path:
            raise ValueError("'path' field is required when source is 'file'")
        if self.source == "experiment" and not self.path:
            raise ValueError("'path' field is required when source is 'experiment'")
        if self.source == "s3":
            missing = [f for f in ("bucket", "key") if not getattr(self, f)]
            if missing:
                raise ValueError(f"Fields {missing} are required when source is 's3'")
        if self.source == "inline" and self.inline is None:
            raise ValueError("'inline' field is required when source is 'inline'")
        return self


class AgentConfig(BaseModel):
    """Agent endpoint configuration."""

    url: str


class EvaluateConfig(BaseModel):
    """Evaluation phase configuration."""

    model: str | None = None
    fail_on_metric_failure: bool = True


class ExperimentConfig(BaseModel):
    """Experiment metadata configuration."""

    name: str


class WorkflowConfig(BaseModel):
    """Workflow execution metadata configuration."""

    execution_id: str = "auto"
    execution_number: int = 1


class PipelineConfig(BaseModel):
    """Top-level pipeline configuration parsed from config.yaml."""

    dataset: DatasetConfig
    agent: AgentConfig
    evaluate: EvaluateConfig = EvaluateConfig()
    experiment: ExperimentConfig
    workflow: WorkflowConfig = WorkflowConfig()
