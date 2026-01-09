"""
Unit tests for run.py

Tests the agent query execution and experiment functionality.
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from run import (
    initialize_client,
    main,
    single_turn_experiment,
    validate_multi_turn_input,
)


# Fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests"""
    tmp = tempfile.mkdtemp()
    original_cwd = Path.cwd()
    yield tmp, original_cwd
    shutil.rmtree(tmp, ignore_errors=True)


# TestInitializeClient tests
@pytest.mark.asyncio
async def test_initialize_client_creates_client(monkeypatch):
    """Test that initialize_client creates a client correctly"""

    # Mock the agent card
    class MockCard:
        pass

    mock_card = MockCard()

    def mock_agent_card(url):
        return mock_card

    # Mock the factory and client
    class MockClient:
        pass

    mock_client = MockClient()

    class MockFactory:
        def create(self, card):
            return mock_client

    def mock_factory_init(config=None):
        return MockFactory()

    monkeypatch.setattr("run.minimal_agent_card", mock_agent_card)
    monkeypatch.setattr("run.ClientFactory", mock_factory_init)

    # Call the function
    result = await initialize_client("http://test-agent:8000")

    # Verify
    assert result == mock_client


# TestSingleTurnExperiment tests
@pytest.mark.asyncio
async def test_single_turn_experiment_success(monkeypatch):
    """Test successful agent query execution"""

    # Mock the client
    class MockTask:
        def model_dump(self, **kwargs):
            return {
                "artifacts": [{"parts": [{"text": "Agent response text"}]}],
                "history": [],
            }

    mock_task = MockTask()

    class MockClient:
        async def send_message(self, message):
            yield (mock_task, None)

    mock_client = MockClient()

    async def mock_init_client(url):
        return mock_client

    # Mock httpx AsyncClient
    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_httpx_client():
        return MockAsyncClient()

    monkeypatch.setattr("run.initialize_client", mock_init_client)
    monkeypatch.setattr("run.httpx.AsyncClient", mock_httpx_client)

    # Create test row
    test_row = {
        "user_input": "What is the weather?",
        "retrieved_contexts": ["Context about weather"],
        "reference": "Expected answer",
    }

    # Call the function
    result = await single_turn_experiment.func(
        test_row, agent_url="http://test-agent:8000", workflow_name="test-workflow"
    )

    # Verify result structure
    assert "user_input" in result
    assert "retrieved_contexts" in result
    assert "reference" in result
    assert "response" in result
    assert result["user_input"] == "What is the weather?"
    assert result["response"] == "Agent response text"


@pytest.mark.asyncio
async def test_single_turn_experiment_error(monkeypatch):
    """Test agent query with error handling"""

    # Mock client that raises an error
    async def mock_init_client(url):
        raise Exception("Connection failed")

    # Mock httpx AsyncClient
    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_httpx_client():
        return MockAsyncClient()

    monkeypatch.setattr("run.initialize_client", mock_init_client)
    monkeypatch.setattr("run.httpx.AsyncClient", mock_httpx_client)

    # Create test row
    test_row = {
        "user_input": "What is the weather?",
        "retrieved_contexts": ["Context"],
        "reference": "Answer",
    }

    # Call the function
    result = await single_turn_experiment.func(
        test_row, agent_url="http://test-agent:8000", workflow_name="test-workflow"
    )

    # Verify error is captured in response
    assert "response" in result
    assert "ERROR" in result["response"]
    assert "Connection failed" in result["response"]


# TestMain tests
@pytest.mark.asyncio
async def test_main_execution(temp_dir, monkeypatch):
    """Test main function execution flow"""

    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        # Create a mock dataset
        class MockDataset:
            def __len__(self):
                return 2

            def __getitem__(self, index):
                # Return single-turn format for detection
                return {"user_input": "Test question", "retrieved_contexts": [], "reference": "Answer"}

        mock_dataset = MockDataset()

        def mock_dataset_load(path, backend):
            return mock_dataset

        # Mock experiment results
        class MockExperiment:
            pass

        mock_experiment = MockExperiment()

        async def mock_arun(*args, **kwargs):
            return mock_experiment

        calls_to_load = []
        calls_to_arun = []

        def mock_dataset_load_tracked(**kwargs):
            calls_to_load.append(kwargs)
            return mock_dataset

        async def mock_arun_tracked(*args, **kwargs):
            calls_to_arun.append({"args": args, "kwargs": kwargs})
            return mock_experiment

        monkeypatch.setattr("run.Dataset.load", mock_dataset_load_tracked)
        monkeypatch.setattr("run.single_turn_experiment.arun", mock_arun_tracked)

        # Run main
        await main("http://test-agent:8000", "test-workflow")

        # Verify Dataset.load was called
        assert len(calls_to_load) == 1

        # Verify experiment was run
        assert len(calls_to_arun) == 1

        # Verify workflow_name was passed through to arun
        assert calls_to_arun[0]["kwargs"]["workflow_name"] == "test-workflow"
    finally:
        os.chdir(original_cwd)


def test_validate_multi_turn_input_success():
    """Test validation with valid multi-turn input"""
    user_input = [
        {"content": "Hello", "type": "human"},
        {"content": "Hi there!", "type": "ai"},
        {"content": "How are you?", "type": "human"},
    ]

    result = validate_multi_turn_input(user_input)

    assert result == user_input


def test_validate_multi_turn_input_invalid_type():
    """Test validation rejects non-list input"""
    with pytest.raises(ValueError, match="must be list"):
        validate_multi_turn_input("not a list")  # type: ignore


def test_validate_multi_turn_input_missing_fields():
    """Test validation catches missing content/type fields"""
    # Missing content
    with pytest.raises(ValueError, match="missing 'content' field"):
        validate_multi_turn_input([{"type": "human"}])

    # Missing type
    with pytest.raises(ValueError, match="missing 'type' field"):
        validate_multi_turn_input([{"content": "Hello"}])


def test_validate_multi_turn_input_invalid_message_type():
    """Test validation catches invalid message types"""
    with pytest.raises(ValueError, match="has invalid type"):
        validate_multi_turn_input([{"content": "Hello", "type": "invalid"}])


@pytest.mark.asyncio
async def test_main_detects_multi_turn(temp_dir, monkeypatch):
    """Test main calls multi_turn_experiment for list user_input"""
    tmp, original_cwd = temp_dir
    os.chdir(tmp)

    try:
        # Create a mock dataset with multi-turn format
        class MockDataset:
            def __len__(self):
                return 1

            def __getitem__(self, index):
                # Return multi-turn format for detection
                return {
                    "user_input": [{"content": "Hello", "type": "human"}],
                    "reference": "Answer",
                }

        mock_dataset = MockDataset()

        calls_to_multi_turn = []

        async def mock_multi_turn_arun(*args, **kwargs):
            calls_to_multi_turn.append({"args": args, "kwargs": kwargs})
            return None

        def mock_dataset_load(**kwargs):
            return mock_dataset

        monkeypatch.setattr("run.Dataset.load", mock_dataset_load)
        monkeypatch.setattr("run.multi_turn_experiment.arun", mock_multi_turn_arun)

        # Run main
        await main("http://test-agent:8000", "test-workflow")

        # Verify multi_turn_experiment was called
        assert len(calls_to_multi_turn) == 1
        assert calls_to_multi_turn[0]["kwargs"]["workflow_name"] == "test-workflow"
    finally:
        os.chdir(original_cwd)


@pytest.mark.asyncio
async def test_multi_turn_experiment_with_tool_calls(monkeypatch):
    """Test multi_turn_experiment extracts tool calls from agent responses"""
    from a2a.types import Message, Part, Role, TextPart
    from run import multi_turn_experiment

    # Mock row data with multi-turn input
    row = {
        "user_input": [
            {"content": "What's the weather in NYC?", "type": "human"},
            {"content": "How about London?", "type": "human"}
        ],
        "reference": "Weather info provided"
    }

    # Create mock task objects with tool calls
    class MockTask:
        def __init__(self, context_id, turn_idx, has_tool_calls=False):
            self.context_id = context_id
            self.turn_idx = turn_idx
            self.id = f"task_{turn_idx}"

            # Create history with agent message
            agent_metadata = None
            if has_tool_calls:
                agent_metadata = {
                    "tool_calls": [
                        {
                            "name": "get_weather",
                            "args": {"location": "NYC" if turn_idx == 1 else "London"}
                        }
                    ]
                }

            self.history = [
                Message(
                    role=Role.user,
                    parts=[Part(TextPart(text=row["user_input"][turn_idx - 1]["content"]))],
                    message_id=f"user_msg_{turn_idx}"
                ),
                Message(
                    role=Role.agent,
                    parts=[Part(TextPart(text=f"Weather response {turn_idx}"))],
                    message_id=f"agent_msg_{turn_idx}",
                    metadata=agent_metadata
                )
            ]

        def model_dump(self, mode=None, include=None):
            return {
                "artifacts": [
                    {
                        "parts": [
                            {"text": f"Weather response {self.turn_idx}"}
                        ]
                    }
                ]
            }

    # Mock client that accumulates history
    class MockClient:
        def __init__(self):
            self.turn_count = 0
            self.accumulated_history = []

        async def send_message(self, message):
            self.turn_count += 1
            context_id = "test_context_123"

            # Add user message to history
            self.accumulated_history.append(message)

            # Add agent response message to history
            has_tool_calls = (self.turn_count == 1)
            agent_metadata = None
            if has_tool_calls:
                agent_metadata = {
                    "tool_calls": [
                        {
                            "name": "get_weather",
                            "args": {"location": "NYC" if self.turn_count == 1 else "London"}
                        }
                    ]
                }

            agent_message = Message(
                role=Role.agent,
                parts=[Part(TextPart(text=f"Weather response {self.turn_count}"))],
                message_id=f"agent_msg_{self.turn_count}",
                metadata=agent_metadata
            )
            self.accumulated_history.append(agent_message)

            # Create task with complete history
            class FinalTask:
                def __init__(self, ctx_id, history, turn_num):
                    self.context_id = ctx_id
                    self.id = f"task_{turn_num}"
                    self.history = list(history)  # Copy the history
                    self.turn_num = turn_num

                def model_dump(self, mode=None, include=None):
                    return {"artifacts": [{"parts": [{"text": f"Weather response {self.turn_num}"}]}]}

            task = FinalTask(context_id, self.accumulated_history, self.turn_count)
            yield (task, None)

    mock_client = MockClient()

    # Mock initialize_client
    async def mock_initialize_client(agent_url):
        return mock_client

    monkeypatch.setattr("run.initialize_client", mock_initialize_client)

    # Mock setup_otel (to avoid actual OTEL setup)
    def mock_setup_otel():
        pass

    monkeypatch.setattr("run.setup_otel", mock_setup_otel)

    # Run the experiment
    result = await multi_turn_experiment(
        row,
        agent_url="http://test-agent:8000",
        workflow_name="test-workflow"
    )

    # Verify result structure
    assert "user_input" in result
    assert "trace_id" in result
    assert isinstance(result["user_input"], list)

    # Verify conversation contains 5 messages
    # Turn 1: human → ai(empty+tool_calls) → ai(text)
    # Turn 2: human → ai(text)
    conversation = result["user_input"]
    assert len(conversation) == 5, f"Expected 5 messages, got {len(conversation)}"

    # Verify first turn
    # Message 0: Human message
    assert conversation[0]["type"] == "human"
    assert conversation[0]["content"] == "What's the weather in NYC?"

    # Message 1: AI message with empty content and tool_calls
    assert conversation[1]["type"] == "ai"
    assert conversation[1]["content"] == ""
    assert "tool_calls" in conversation[1], "AI message should have tool_calls"
    assert len(conversation[1]["tool_calls"]) == 1
    assert conversation[1]["tool_calls"][0]["name"] == "get_weather"
    assert conversation[1]["tool_calls"][0]["args"]["location"] == "NYC"

    # Message 2: AI message with text content (no tool_calls)
    assert conversation[2]["type"] == "ai"
    assert conversation[2]["content"] == "Weather response 1"
    assert "tool_calls" not in conversation[2], "Text AI message should not have tool_calls"

    # Verify second turn (no tool calls)
    # Message 3: Human message
    assert conversation[3]["type"] == "human"
    assert conversation[3]["content"] == "How about London?"

    # Message 4: AI message with text content
    assert conversation[4]["type"] == "ai"
    assert conversation[4]["content"] == "Weather response 2"
    assert "tool_calls" not in conversation[4], "Second AI message should not have tool_calls"


@pytest.mark.asyncio
async def test_multi_turn_experiment_no_tool_calls(monkeypatch):
    """Test multi_turn_experiment works without tool calls"""
    from a2a.types import Message, Part, Role, TextPart
    from run import multi_turn_experiment

    # Mock row data with multi-turn input
    row = {
        "user_input": [
            {"content": "Hello", "type": "human"},
        ],
        "reference": "Greeting response"
    }

    # Create mock task without tool calls
    class MockTask:
        def __init__(self, context_id):
            self.context_id = context_id
            self.id = "task_1"

            # History without tool calls in metadata
            self.history = [
                Message(
                    role=Role.user,
                    parts=[Part(TextPart(text="Hello"))],
                    message_id="user_msg_1"
                ),
                Message(
                    role=Role.agent,
                    parts=[Part(TextPart(text="Hi there!"))],
                    message_id="agent_msg_1",
                    metadata=None  # No metadata, no tool calls
                )
            ]

        def model_dump(self, mode=None, include=None):
            return {
                "artifacts": [
                    {
                        "parts": [
                            {"text": "Hi there!"}
                        ]
                    }
                ]
            }

    # Mock client
    class MockClient:
        async def send_message(self, message):
            task = MockTask("test_context_456")
            yield (task, None)

    mock_client = MockClient()

    # Mock initialize_client
    async def mock_initialize_client(agent_url):
        return mock_client

    monkeypatch.setattr("run.initialize_client", mock_initialize_client)

    # Mock setup_otel
    def mock_setup_otel():
        pass

    monkeypatch.setattr("run.setup_otel", mock_setup_otel)

    # Run the experiment
    result = await multi_turn_experiment(
        row,
        agent_url="http://test-agent:8000",
        workflow_name="test-workflow"
    )

    # Verify result structure
    assert "user_input" in result
    assert isinstance(result["user_input"], list)

    conversation = result["user_input"]
    assert len(conversation) == 2  # 1 turn = 2 messages

    # Verify messages don't have tool_calls field (or it's None/empty)
    assert conversation[0]["type"] == "human"
    assert conversation[1]["type"] == "ai"
    assert conversation[1]["content"] == "Hi there!"

    # Tool calls should either not exist or be None/empty
    if "tool_calls" in conversation[1]:
        assert conversation[1]["tool_calls"] is None or len(conversation[1]["tool_calls"]) == 0


@pytest.mark.asyncio
async def test_multi_turn_experiment_with_datapart_tool_calls(monkeypatch):
    """Test multi_turn_experiment extracts tool calls from DataPart objects (framework-agnostic)"""
    from a2a.types import DataPart, Message, Part, Role, TextPart
    from run import multi_turn_experiment

    # Mock row data with multi-turn input
    row = {
        "user_input": [
            {"content": "What time is it in New York?", "type": "human"},
        ],
        "reference": "Time info provided"
    }

    # Create mock task with DataPart tool calls
    class MockTask:
        def __init__(self, context_id):
            self.context_id = context_id
            self.id = "task_1"

            # History with DataPart containing both tool call and tool response
            self.history = [
                Message(
                    role=Role.user,
                    parts=[Part(TextPart(text="What time is it in New York?"))],
                    message_id="user_msg_1"
                ),
                # Tool call DataPart (has name + args)
                Message(
                    role=Role.agent,
                    parts=[Part(DataPart(
                        kind="data",
                        data={
                            "id": "call_get_current_time",
                            "name": "get_current_time",
                            "args": {"city": "New York"}
                        },
                        metadata={"adk_type": "function_call"}
                    ))],
                    message_id="agent_msg_1",
                    metadata=None
                ),
                # Tool response DataPart (has name + response) - should be ignored
                Message(
                    role=Role.agent,
                    parts=[Part(DataPart(
                        kind="data",
                        data={
                            "id": "call_get_current_time",
                            "name": "get_current_time",
                            "response": {"status": "success", "report": "The current time in New York is 11:22:05 EST"}
                        },
                        metadata={"adk_type": "function_response"}
                    ))],
                    message_id="agent_msg_2",
                    metadata=None
                ),
                # Final text response
                Message(
                    role=Role.agent,
                    parts=[Part(TextPart(text="The current time in New York is 11:22:05 EST"))],
                    message_id="agent_msg_3",
                    metadata=None
                )
            ]

        def model_dump(self, mode=None, include=None):
            return {
                "artifacts": [
                    {
                        "parts": [
                            {"text": "The current time in New York is 11:22:05 EST"}
                        ]
                    }
                ]
            }

    # Mock client
    class MockClient:
        async def send_message(self, message):
            task = MockTask("test_context_789")
            yield (task, None)

    mock_client = MockClient()

    # Mock initialize_client
    async def mock_initialize_client(agent_url):
        return mock_client

    monkeypatch.setattr("run.initialize_client", mock_initialize_client)

    # Mock setup_otel
    def mock_setup_otel():
        pass

    monkeypatch.setattr("run.setup_otel", mock_setup_otel)

    # Run the experiment
    result = await multi_turn_experiment(
        row,
        agent_url="http://test-agent:8000",
        workflow_name="test-workflow"
    )

    # Verify result structure
    assert "user_input" in result
    assert isinstance(result["user_input"], list)

    conversation = result["user_input"]
    # Should have 4 messages: human → ai(empty+tool_calls) → tool(response) → ai(text)
    assert len(conversation) == 4, f"Expected 4 messages, got {len(conversation)}: {conversation}"

    # Message 0: Human message
    assert conversation[0]["type"] == "human"
    assert conversation[0]["content"] == "What time is it in New York?"

    # Message 1: AI message with empty content but with tool_calls
    assert conversation[1]["type"] == "ai"
    assert conversation[1]["content"] == "", "AI message with tool_calls should have empty content"
    assert "tool_calls" in conversation[1], "AI message should have tool_calls from DataPart"
    assert len(conversation[1]["tool_calls"]) == 1, "Should have exactly one tool call"
    assert conversation[1]["tool_calls"][0]["name"] == "get_current_time"
    assert conversation[1]["tool_calls"][0]["args"]["city"] == "New York"

    # Message 2: Tool response message
    assert conversation[2]["type"] == "tool"
    assert "content" in conversation[2]
    assert "The current time in New York is 11:22:05 EST" in conversation[2]["content"]

    # Message 3: Final AI message with text content (no tool_calls)
    assert conversation[3]["type"] == "ai"
    assert conversation[3]["content"] == "The current time in New York is 11:22:05 EST"
    assert "tool_calls" not in conversation[3], "Final AI message should not have tool_calls"
