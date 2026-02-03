# Grafana Visualization Strategy

## Overview

The testbench uses two complementary Grafana dashboards for monitoring and debugging agent quality:

1. **Trends Dashboard** - Monitor quality trends over time, spot regressions after deployments
2. **Execution Details Dashboard** - Investigate specific execution failures, identify root causes

This two-dashboard approach separates high-level monitoring from deep debugging, enabling efficient quality assurance workflows.

## User Workflow: Monitoring → Investigation → Debugging

```
Trends Dashboard
    │
    ├─ Spot drop in scores after deployment
    │
    └─ Click execution row → Execution Details Dashboard
                              │
                              ├─ See which scenarios/steps failed
                              │
                              └─ Click [View Trace] → Tempo
                                                        │
                                                        └─ See full agent behavior
```

## Current OTLP Metrics

The current system publishes flat metrics with sample-level labels:

Example OTLP metrics:
```
testbench_evaluation_metric{
  name="faithfulness",
  workflow_name="weather-agent-test",
  execution_id="exec-001",
  execution_number="1",
  trace_id="a1b2c3d4e5f6789012345678901234ab",
  sample_hash="7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a",
  user_input_truncated="What's the weather in NYC?"
} = 0.95

testbench_evaluation_metric{
  name="answer_relevancy",
  workflow_name="weather-agent-test",
  execution_id="exec-001",
  execution_number="1",
  trace_id="a1b2c3d4e5f6789012345678901234ab",
  sample_hash="8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3",
  user_input_truncated="And in London?"
} = 0.92
```

## Enhanced OTLP Metrics

The new system publishes metrics with rich hierarchical labels:

Example OTLP metrics:
```
testbench_evaluation_metric{
  name="AnswerAccuracy",
  workflow_name="weather-agent-test",
  execution_id="exec-001",
  execution_number="1",
  experiment_id="exp_a7f3d2e9c1b4a8f6",
  scenario_id="scn_b2c4e8f1d3a5c7e9",
  scenario_name="weather_queries",
  step_id="stp_c3d5a9f2e4b6d8fa",
  step_index="0",
  trace_id="a1b2c3d4e5f6789012345678901234ab",
  threshold="0.9",
  result="pass",
  user_input_truncated="What's the weather in NYC?"
} = 0.92

testbench_evaluation_metric{
  name="AnswerAccuracy",
  workflow_name="weather-agent-test",
  execution_id="exec-001",
  execution_number="1",
  experiment_id="exp_a7f3d2e9c1b4a8f6",
  scenario_id="scn_b2c4e8f1d3a5c7e9",
  scenario_name="weather_queries",
  step_id="stp_d4e6b0a3f5c7d9eb",
  step_index="1",
  trace_id="a1b2c3d4e5f6789012345678901234ab",
  threshold="0.9",
  result="fail",
  user_input_truncated="And in London?"
} = 0.87
```

## Dashboard 1: Trends Over Time

**Purpose**: Monitor agent quality trends, identify regressions correlated with deployments.

**Use Cases**:
- Continuous monitoring of agent quality metrics
- Spotting degradation after code deployments
- Comparing scenario performance over time
- Identifying which executions need investigation

**Dashboard Mockup**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ RAGAS Trends Dashboard - weather-agent-test                        │
│ Time Range: [Last 30 Days ▼]                                       │
├─────────────────────────────────────────────────────────────────────┤
│ Overall Pass Rate Over Time                                         │
│                                                                     │
│ 100% ┤                                                              │
│      │  ┌─────────────┐                                            │
│  90% │  │  v2.1.0     │     ●─────────●  weather_queries          │
│      │  │  deployed   │    ╱           ╲                           │
│  80% │  └─────────────┘   ●             ●  booking_flow            │
│      │                   ╱               ╲                          │
│  70% ├──────────────────●                 ●  error_handling        │
│      │                                                              │
│  60% ┤                                                              │
│      └─────────────────────────────────────────                   │
│       Jan 15    Jan 22    Jan 29    Feb 5                          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Average Metric Scores Over Time                                     │
│                                                                     │
│ 1.0  ┤                                                              │
│      │                    ●─────●─────●  AnswerAccuracy            │
│ 0.9  │     ●─────●───────╱                                         │
│      │    ╱           ╲                                             │
│ 0.8  ├───●             ●───────────────  ToolCallAccuracy          │
│      │                                                              │
│ 0.7  ┤                                                              │
│      └─────────────────────────────────────────                   │
│       Jan 15    Jan 22    Jan 29    Feb 5                          │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Recent Executions                                [Filter ▼]         │
├─────────────────────────────────────────────────────────────────────┤
│ Exec ID  │ Time       │ Pass Rate │ Avg Score │ Failed │ Status   │
│──────────┼────────────┼───────────┼───────────┼────────┼──────────│
│ exec-005 │ Feb 5 14:30│   85%     │   0.89    │   3    │ [View]   │ ← Click to drill down
│ exec-004 │ Feb 5 12:15│   90%     │   0.91    │   2    │ [View]   │
│ exec-003 │ Feb 4 18:45│   75%     │   0.82    │   5    │ [View]   │
│ exec-002 │ Feb 4 14:20│   95%     │   0.94    │   1    │ [View]   │
│                                                                     │
│ 📊 Click [View] to investigate execution details                    │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **Time-series focus**: All data aggregated over time windows
- **Deployment annotations**: Visual markers showing when agent versions deployed
- **Scenario-level trends**: Compare different test scenarios (weather_queries, booking_flow, etc.)
- **Metric-level trends**: Track specific metrics (AnswerAccuracy, ToolCallAccuracy, etc.)
- **Quick drill-down**: Click execution ID to jump to details dashboard

## Dashboard 2: Execution Details

**Purpose**: Deep-dive into a specific execution to diagnose failures.

**Use Cases**:
- Investigating why an execution failed
- Identifying which scenarios/steps caused failures
- Finding patterns in failed evaluations
- Linking to distributed traces for root cause analysis

**Dashboard Mockup**:

```
┌─────────────────────────────────────────────────────────────────────┐
│ Execution Details - exec-005 (Feb 5, 2026 14:30)                   │
│ Workflow: weather-agent-test  |  Experiment: exp_a7f3d2e9          │
│ [← Back to Trends]                                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │  Scenarios   │  │  Pass Rate   │  │  Avg Score   │             │
│  │      3       │  │     85%      │  │     0.89     │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ Failed Steps │  │ Total Steps  │  │  Metrics     │             │
│  │      3       │  │      20      │  │      5       │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Pass Rate by Scenario (This Execution)                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  weather_queries    ██████████ 100%  (6/6 passed)                  │
│  booking_flow       ████████░░  80%  (4/5 passed) ⚠                │
│  error_handling     ███████░░░  70%  (7/10 passed) ⚠               │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Failed Steps (This Execution)                                      │
├─────────────────────────────────────────────────────────────────────┤
│ Scenario         │ Step │ Metric          │ Score │ Thresh │ Trace │
│──────────────────┼──────┼─────────────────┼───────┼────────┼───────│
│ booking_flow     │  2   │ IntentAccuracy  │ 0.87  │ 0.90   │[View] │
│ error_handling   │  1   │ ErrorRecovery   │ 0.75  │ 0.80   │[View] │
│ error_handling   │  5   │ Faithfulness    │ 0.82  │ 0.85   │[View] │
│                                                                     │
│ 🔍 Click [View] to see full trace in Tempo                         │
├─────────────────────────────────────────────────────────────────────┤
│ All Steps Results                          [Search: ___] [Filter]  │
├─────────────────────────────────────────────────────────────────────┤
│ Scenario         │ Step │ Metric          │ Result │ Score         │
│──────────────────┼──────┼─────────────────┼────────┼───────────────│
│ weather_queries  │  0   │ AnswerAccuracy  │ PASS ✓ │ 0.95          │
│ weather_queries  │  1   │ AnswerAccuracy  │ PASS ✓ │ 0.92          │
│ booking_flow     │  0   │ IntentAccuracy  │ PASS ✓ │ 0.98          │
│ booking_flow     │  2   │ IntentAccuracy  │ FAIL ✗ │ 0.87          │
│ ... (showing 10 of 20)                                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Features**:
- **Single execution focus**: All data filtered by `execution_id`
- **Summary cards**: Quick overview of execution health
- **Scenario breakdown**: See which scenarios passed/failed
- **Failed steps detail**: Pinpoint exact failures with threshold comparisons
- **All steps results**: Searchable/filterable table of every evaluation
- **Trace linking**: Direct links to Tempo for deep debugging

## Trace Linking to Tempo

Each scenario has a `trace_id` that links to OpenTelemetry traces in Tempo, enabling deep debugging of agent behavior.

**User Workflow**:
1. Identify failed step in Grafana "Execution Details" dashboard
2. Click [View Trace] link next to failed step
3. Opens Tempo showing full execution trace for that scenario
4. Drill down into agent spans, tool calls, LLM requests
5. Correlate evaluation failure with runtime behavior