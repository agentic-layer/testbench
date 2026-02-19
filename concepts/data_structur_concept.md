# Data Structure Concept: Migration from JSONL to JSON Schema

## Executive Summary

### Problem Statement

The current testbench pipeline uses flat JSONL (JSON Lines) files for storing test data throughout the 3-phase evaluation workflow.

### Solution

Replace the flat JSONL format with a hierarchical JSON Schema-based structure that organizes tests into a three-level hierarchy:

```
Experiment → Scenarios → Steps
```

This migration introduces formal JSON schemas validated at each pipeline phase, custom RAGAS backend implementations for bidirectional data transformation, and content-based deterministic ID generation for reproducibility.

### Key Benefits

1. **Scenario Organization**: Group related test steps into named scenarios (e.g., "weather_queries", "booking_flow")
2. **Hierarchical Evaluation**: Support both step-level and scenario-level metrics
3. **Deterministic IDs**: Content-based hashing ensures reproducible identifiers across runs
4. **Schema Validation**: Catches data contract violations early

### Impact

This is a **breaking change** requiring:
- Updates to run.py, evaluate.py, publish.py, visualize.py
- Migration of existing JSONL test data to JSON format
- Updated Grafana dashboards
- No backwards compatibility with JSONL format

---

## Current State: JSONL-Based Pipeline

### Overview

The testbench currently uses RAGAS framework's `LocalJSONLBackend` to store evaluation data in flat JSONL format. Each line in the file represents a single, independent test sample with no relationship to other samples.

### RAGAS Backend Architecture

RAGAS (Retrieval-Augmented Generation Assessment) uses a backend abstraction layer for data persistence.
The `@experiment()` decorator processes datasets row-by-row asynchronously. Each decorated function:
1. Receives a single row (dict) as input
2. Processes it (queries agent, evaluates metrics, etc.)
3. Returns an enriched row (dict) with added fields
4. RAGAS collects all rows into a list and passes to backend for serialization

The `LocalJSONLBackend` simply writes each dict as a JSON line without understanding relationships between samples.

---

## Target State: JSON Schema-Based Pipeline

### Overview

The new system uses hierarchical JSON format validated against formal schemas at each phase. Data transitions through three schemas:

1. **experiment.schema.json** - User input (test definitions)
2. **executed_experiment.schema.json** - After agent execution
3. **evaluated_experiment.schema.json** - After metric evaluation

### Schema Hierarchy Visualization

```
Experiment
├── id (string) - Unique experiment identifier
├── llm_as_a_judge_model (string) - LLM for evaluation
├── default_threshold (number) - Fallback threshold (0.0-1.0)
└── scenarios[] (array)
    ├── id (string) - Unique scenario identifier
    ├── trace_id (string) - OpenTelemetry trace
    ├── name (string) - Human-readable scenario name
    ├── steps[] (array)
    │   ├── id (string) - Unique step identifier
    │   ├── input (string) - User query to agent
    │   ├── turns[] (array) - A2A conversation history
    │   │   ├── content (string) - Message content
    │   │   ├── type (enum) - "human" | "agent" | "tool"
    │   │   └── tool_calls[] (array, optional) - Tool invocations
    │   ├── reference (object, optional)
    │   │   ├── response (string) - Expected answer
    │   │   ├── tool_calls[] (array) - Expected tool usage
    │   │   ├── topics[] (array) - Expected topics covered
    │   │   └── ... (other reference fields)
    │   ├── custom_values (object, optional) - Custom metadata
    │   └── metrics[] (array) - Metric configurations
    │       ├── metric_name (string) - Metric identifier
    │       ├── threshold (number, optional) - Override threshold
    │       └── parameters (object, optional) - Metric config
    └── evaluations[] (array, optional) - Scenario-level metrics
```

### experiment.schema.json is User Input

The `experiment.schema.json` defines the **starting point** of the pipeline - the test definitions created manually by users. This is analogous to a test suite configuration file.

Users create `data/datasets/experiment.json` conforming to this schema BEFORE running the pipeline. This file contains:
- Test scenario definitions
- Expected inputs to the agent
- Reference data (ground truth)
- Metric configurations (which metrics to evaluate, thresholds)

**Example user-created experiment.json:**
```json
{
  "llm_as_a_judge_model": "gemini-2.5-flash-lite",
  "default_threshold": 0.9,
  "scenarios": [
    {
      "name": "weather_queries",
      "steps": [
        {
          "input": "What's the weather in NYC?",
          "reference": {
            "response": "The weather in NYC is sunny and 70F.",
            "tool_calls": [{"name": "get_weather", "args": {"city": "NYC"}}]
          },
          "metrics": [
            {"metric_name": "AnswerAccuracy", "threshold": 0.9},
            {"metric_name": "ToolCallAccuracy", "threshold": 1.0}
          ]
        }
      ]
    }
  ]
}
```

### Detailed Attribute Descriptions

#### run.py execution

**ADDED at experiment level:**
- `id` (string) - Unique experiment identifier generated via content hash

**ADDED at scenario level:**
- `id` (string) - Unique scenario identifier (hash of experiment_id + scenario_name)
- `trace_id` (string) - OpenTelemetry trace ID for distributed tracing

**ADDED at step level:**
- `id` (string) - Unique step identifier (Hash of scenario_id + step_input + index)
- `turns[]` (array) - Full A2A conversation history with message objects:
  - `content` (string) - Message text or stringified tool result
  - `type` (enum) - "human" | "agent" | "tool"
  - `tool_calls[]` (array, optional) - Tool invocations made by agent
    - `name` (string) - Tool name
    - `args` (object) - Tool arguments

**PRESERVED:**
- All user input data (llm_as_a_judge_model, default_threshold, scenarios, steps, metrics as metric configurations)

#### evaluate.py execution

**ADDED at step level:**
- `evaluations[]` (array) - List of `Evaluation` objects, each containing:
  - `metric` (object) - The metric configuration (metric_name, threshold, parameters)
  - `result` (object) - Evaluation result containing:
    - `result` (string) - "pass" or "fail" based on threshold comparison
    - `score` (number) - 0.0-1.0 computed metric score from LLM-as-judge
    - `details` (object) - Additional evaluation breakdown and reasoning

**PRESERVED:**
- All data from executed_experiment including IDs, trace_id, turns
- `metrics[]` at step level remains unchanged

### Complete Data Flow with Concrete Examples

#### Example 1: User Input (experiment.json)

**File**: `data/datasets/experiment.json`
**Conforms to**: `experiment.schema.json`

```json
{
  "llm_as_a_judge_model": "gemini-2.5-flash-lite",
  "default_threshold": 0.9,
  "scenarios": [
    {
      "name": "weather_queries",
      "steps": [
        {
          "input": "What's the weather in NYC?",
          "reference": {
            "response": "The weather in NYC is sunny and 70F.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "NYC"}
              }
            ]
          },
          "metrics": [
            {
              "metric_name": "AnswerAccuracy",
              "threshold": 0.9
            },
            {
              "metric_name": "ToolCallAccuracy",
              "threshold": 1.0,
              "parameters": {"exact_match": true}
            }
          ]
        },
        {
          "input": "And in London?",
          "reference": {
            "response": "London is rainy with 12C.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "London"}
              }
            ]
          },
          "metrics": [
            {
              "metric_name": "AnswerAccuracy"
            }
          ]
        }
      ]
    },
    {
      "name": "booking_flow",
      "steps": [
        {
          "input": "Book a flight to Paris",
          "reference": {
            "response": "I'll help you book a flight to Paris. What date would you like to travel?",
            "topics": ["booking", "flight", "Paris"]
          },
          "custom_values": {
            "expected_intent": "flight_booking",
            "priority": "high"
          },
          "metrics": [
            {
              "metric_name": "IntentClassification", # Custom metric
              "threshold": 0.95
            }
          ]
        }
      ],
      "evaluations": [
        {
          "metric_name": "ScenarioCoherence", # Custom Metric
          "threshold": 0.85,
          "parameters": {"check_continuity": true}
        }
      ]
    }
  ]
}
```

#### Example 2: After run.py (executed_experiment.json)

**File**: `data/experiments/executed_experiment.json`
**Conforms to**: `executed_experiment.schema.json`

```json
{
  "id": "exp_a7f3d2e9c1b4a8f6",
  "llm_as_a_judge_model": "gemini-2.5-flash-lite",
  "default_threshold": 0.9,
  "scenarios": [
    {
      "id": "scn_b2c4e8f1d3a5c7e9",
      "trace_id": "a1b2c3d4e5f6789012345678901234ab",
      "name": "weather_queries",
      "steps": [
        {
          "id": "stp_c3d5a9f2e4b6d8fa",
          "input": "What's the weather in NYC?",
          "turns": [
            {
              "content": "What's the weather in NYC?",
              "type": "human"
            },
            {
              "content": "Let me check the current weather in New York City for you.",
              "type": "agent",
              "tool_calls": [
                {
                  "name": "get_weather",
                  "args": {"city": "NYC", "units": "imperial"}
                }
              ]
            },
            {
              "content": "{\"temperature\": 70, \"condition\": \"sunny\", \"humidity\": 45}",
              "type": "tool"
            },
            {
              "content": "It's currently sunny and 70°F in New York City with 45% humidity.",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "The weather in NYC is sunny and 70F.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "NYC"}
              }
            ],
            "topics": ["weather", "temperature", "NYC"]
          },
          "metrics": [
            {
              "metric_name": "AnswerAccuracy",
              "threshold": 0.9
            },
            {
              "metric_name": "ToolCallAccuracy",
              "threshold": 1.0,
              "parameters": {"exact_match": true}
            }
          ]
        },
        {
          "id": "stp_d4e6b0a3f5c7d9eb",
          "input": "And in London?",
          "turns": [
            {
              "content": "And in London?",
              "type": "human"
            },
            {
              "content": "I'll get the weather information for London.",
              "type": "agent",
              "tool_calls": [
                {
                  "name": "get_weather",
                  "args": {"city": "London", "units": "metric"}
                }
              ]
            },
            {
              "content": "{\"temperature\": 12, \"condition\": \"rainy\", \"humidity\": 85}",
              "type": "tool"
            },
            {
              "content": "London is currently experiencing rainy weather with a temperature of 12°C and 85% humidity.",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "London is rainy with 12C.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "London"}
              }
            ]
          },
          "metrics": [
            {
              "metric_name": "AnswerAccuracy"
            }
          ]
        }
      ]
    },
    {
      "id": "scn_e5f7c1b4d6a8e0fc",
      "trace_id": "b2c3d4e5f6a7890123456789012345bc",
      "name": "booking_flow",
      "steps": [
        {
          "id": "stp_f6a8d2c5e7b9f1ad",
          "input": "Book a flight to Paris",
          "turns": [
            {
              "content": "Book a flight to Paris",
              "type": "human"
            },
            {
              "content": "I'd be happy to help you book a flight to Paris! To find the best options, could you please tell me what date you'd like to travel?",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "I'll help you book a flight to Paris. What date would you like to travel?",
            "topics": ["booking", "flight", "Paris"]
          },
          "custom_values": {
            "expected_intent": "flight_booking",
            "priority": "high"
          },
          "metrics": [
            {
              "metric_name": "IntentClassification",
              "threshold": 0.95
            }
          ]
        }
      ],
      "evaluations": [
        {
          "metric_name": "ScenarioCoherence",
          "threshold": 0.85,
          "parameters": {"check_continuity": true}
        }
      ]
    }
  ]
}
```

**Key Changes from Example 1:**
- Added `id` at experiment, scenario, and step levels (content-based SHA256 hashes)
- Added `trace_id` at scenario level (OpenTelemetry distributed tracing)
- Added `turns[]` at step level with full A2A conversation history
- Preserved all user input data unchanged

#### Example 3: After evaluate.py (evaluated_experiment.json)

**File**: `data/experiments/evaluated_experiment.json`
**Conforms to**: `evaluated_experiment.schema.json`

```json
{
  "id": "exp_a7f3d2e9c1b4a8f6",
  "llm_as_a_judge_model": "gemini-2.5-flash-lite",
  "default_threshold": 0.9,
  "scenarios": [
    {
      "id": "scn_b2c4e8f1d3a5c7e9",
      "trace_id": "a1b2c3d4e5f6789012345678901234ab",
      "name": "weather_queries",
      "steps": [
        {
          "id": "stp_c3d5a9f2e4b6d8fa",
          "input": "What's the weather in NYC?",
          "turns": [
            {
              "content": "What's the weather in NYC?",
              "type": "human"
            },
            {
              "content": "Let me check the current weather in New York City for you.",
              "type": "agent",
              "tool_calls": [
                {
                  "name": "get_weather",
                  "args": {"city": "NYC", "units": "imperial"}
                }
              ]
            },
            {
              "content": "{\"temperature\": 70, \"condition\": \"sunny\", \"humidity\": 45}",
              "type": "tool"
            },
            {
              "content": "It's currently sunny and 70°F in New York City with 45% humidity.",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "The weather in NYC is sunny and 70F.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "NYC"}
              }
            ],
            "topics": ["weather", "temperature", "NYC"]
          },
          "evaluations": [
            {
              "metric": {
                "metric_name": "AnswerAccuracy",
                "threshold": 0.9
              },
              "result": {
                "result": "pass",
                "score": 0.92,
                "details": {
                  "semantic_similarity": 0.94,
                  "factual_consistency": 0.90,
                  "reasoning": "Response accurately conveys weather information with additional helpful details"
                }
              }
            },
            {
              "metric": {
                "metric_name": "ToolCallAccuracy",
                "threshold": 1.0,
                "parameters": {"exact_match": true}
              },
              "result": {
                "result": "pass",
                "score": 1.0,
                "details": {
                  "tool_name_match": true,
                  "required_args_match": true,
                  "extra_args": ["units"]
                }
              }
            }
          ]
        },
        {
          "id": "stp_d4e6b0a3f5c7d9eb",
          "input": "And in London?",
          "turns": [
            {
              "content": "And in London?",
              "type": "human"
            },
            {
              "content": "I'll get the weather information for London.",
              "type": "agent",
              "tool_calls": [
                {
                  "name": "get_weather",
                  "args": {"city": "London", "units": "metric"}
                }
              ]
            },
            {
              "content": "{\"temperature\": 12, \"condition\": \"rainy\", \"humidity\": 85}",
              "type": "tool"
            },
            {
              "content": "London is currently experiencing rainy weather with a temperature of 12°C and 85% humidity.",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "London is rainy with 12C.",
            "tool_calls": [
              {
                "name": "get_weather",
                "args": {"city": "London"}
              }
            ]
          },
          "evaluations": [
            {
              "metric": {
                "metric_name": "AnswerAccuracy"
              },
              "result": {
                "result": "fail",
                "score": 0.87,
                "details": {
                  "semantic_similarity": 0.91,
                  "factual_consistency": 0.83,
                  "reasoning": "Response contains correct information but fails to meet default threshold of 0.9"
                }
              }
            }
          ]
        }
      ]
    },
    {
      "id": "scn_e5f7c1b4d6a8e0fc",
      "trace_id": "b2c3d4e5f6a7890123456789012345bc",
      "name": "booking_flow",
      "steps": [
        {
          "id": "stp_f6a8d2c5e7b9f1ad",
          "input": "Book a flight to Paris",
          "turns": [
            {
              "content": "Book a flight to Paris",
              "type": "human"
            },
            {
              "content": "I'd be happy to help you book a flight to Paris! To find the best options, could you please tell me what date you'd like to travel?",
              "type": "agent"
            }
          ],
          "reference": {
            "response": "I'll help you book a flight to Paris. What date would you like to travel?",
            "topics": ["booking", "flight", "Paris"]
          },
          "custom_values": {
            "expected_intent": "flight_booking",
            "priority": "high"
          },
          "evaluations": [
            {
              "metric": {
                "metric_name": "IntentClassification",
                "threshold": 0.95
              },
              "result": {
                "result": "pass",
                "score": 0.98,
                "details": {
                  "predicted_intent": "flight_booking",
                  "confidence": 0.98,
                  "alternative_intents": []
                }
              }
            }
          ]
        }
      ],
      "evaluations": [
        {
          "metric": {
            "metric_name": "ScenarioCoherence",
            "threshold": 0.85,
            "parameters": {"check_continuity": true}
          },
          "result": {
            "result": "pass",
            "score": 0.90,
            "details": {
              "conversation_flow": 0.92,
              "topic_consistency": 0.88,
              "reasoning": "Scenario maintains coherent booking flow with appropriate agent responses"
            }
          }
        }
      ]
    }
  ]
}
```

**Key Changes from Example 2:**
- Added `evaluations[]` at step level containing `Evaluation` objects with nested structure:
  - `metric`: The metric configuration (metric_name, threshold, parameters)
  - `result`: Evaluation outcome (result, score, details)
- Scenario-level `evaluations[]` also uses the nested `{ metric, result }` structure
- Step with score 0.87 fails because it's below default_threshold (0.9)
- All IDs, trace_id, turns preserved unchanged
