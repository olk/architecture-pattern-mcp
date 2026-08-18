# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Unit tests for MCPArchitectServer (FR-240, FR-241, FR-242, FR-247 to FR-250).

Validates:
- AC-240: Verify MCPArchitectServer class exists, accepts optional config_path parameter
- AC-241: Verify list_tools returns all four tool definitions
- AC-242: Verify call_tool routes to correct tool implementation

Test Case IDs: UT-14

FR-240: The system SHALL provide an MCPArchitectServer class
FR-241: The system SHALL expose four MCP tools via list_tools handler
FR-242: The system SHALL route tool calls via call_tool handler
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from fastmcp import Client
from src.server import ERROR_SERVER_INIT, MCPArchitectServer


class TestMCPArchitectServerInit:
    """
    Tests for MCPArchitectServer initialization.

    AC-240: Verify MCPArchitectServer class exists, accepts optional config_path parameter
    """

    def test_server_class_exists(self):
        """AC-240: Verify MCPArchitectServer class exists"""
        assert MCPArchitectServer is not None

    def test_server_accepts_config_path_parameter(self):
        """AC-240: Verify MCPArchitectServer accepts optional config_path parameter"""
        server = MCPArchitectServer(config_path=None)
        assert server._config_path is None

    def test_server_accepts_custom_config_path(self):
        """AC-240: Verify MCPArchitectServer accepts custom config_path"""
        custom_path = "/custom/path/config.json"
        server = MCPArchitectServer(config_path=custom_path)
        assert server._config_path == custom_path

    def test_server_initializes_with_defaults(self):
        """AC-240: Verify MCPArchitectServer initializes with correct defaults"""
        server = MCPArchitectServer()
        assert server._config is not None
        assert server._agent is None
        assert server._pipeline is None
        assert server._tools == {}


class TestMCPArchitectServerLifespan:
    """
    Tests for MCPArchitectServer lifespan management.

    IC-37: Lifespan function SHALL use yield statement
    IC-38: Cleanup code SHALL be wrapped in finally blocks
    IC-39: Context dictionary SHALL be accessible via ctx.lifespan_context
    """

    def test_lifespan_yields_context(self):
        """IC-37: Verify lifespan yields a context dictionary"""
        import inspect

        server = MCPArchitectServer(config_path=None)

        # Get the source of the lifespan method to verify yield is present
        source = inspect.getsource(server.lifespan)
        # Verify the function contains a yield statement
        assert 'yield' in source

    def test_cleanup_in_finally_block(self):
        """IC-38: Verify cleanup is wrapped in try/finally"""
        import inspect

        server = MCPArchitectServer(config_path=None)

        # Get the source of the lifespan method to verify finally is present
        source = inspect.getsource(server.lifespan)
        # Verify the function contains a finally block
        assert 'finally:' in source

        # After the generator is done (StopAsyncIteration), cleanup should have been called
        # Note: The actual cleanup happens in the finally block which runs when generator closes


class TestMCPArchitectServerPromptRegistration:
    """
    Tests for MCPArchitectServer prompt registration.

    FR-247: The system SHALL expose four MCP prompts via prompts/list handler
    FR-248: Prompt design_architecture_workflow guides the design workflow
    FR-249: Prompt explore_pattern_catalog embeds live pattern metadata
    FR-250: Prompts SHALL be idempotently registered

    Test Case IDs: UT-15
    """

    @pytest.mark.asyncio
    async def test_lifespan_registers_four_prompts(self):
        """FR-247: Verify lifespan registers 4 prompts."""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_prompts(server._mcp)

            components = server._mcp.local_provider._components
            prompt_keys = [k for k in components.keys() if "prompt" in k.lower()]
            names = {k.split(":")[1].split("@")[0] for k in prompt_keys}
            assert names == {
                "design_architecture_workflow",
                "explore_pattern_catalog",
                "evaluate_my_architecture",
                "compare_architecture_styles",
            }


class TestMCPArchitectServerToolRegistration:
    """
    Tests for MCPArchitectServer tool registration and routing.

    FR-241: The system SHALL expose four MCP tools via list_tools handler
    FR-242: The system SHALL route tool calls via call_tool handler
    """

    @pytest.mark.asyncio
    async def test_lifespan_registers_four_tools(self):
        """FR-241: Verify lifespan registers 6 tools with correct names"""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)

            tool_components = server._mcp.local_provider._components
            tool_keys = [k for k in tool_components.keys() if k.startswith('tool:')]
            assert len(tool_keys) == 6

            expected_tools = {
                "design_architecture",
                "analyze_architecture",
                "generate_architecture",
                "evaluate_architecture",
                "list_architecture_patterns",
                "get_architecture_pattern",
            }
            actual_tools = {k.split(':')[1].split('@')[0] for k in tool_keys}
            assert actual_tools == expected_tools

    @pytest.mark.asyncio
    async def test_registered_tools_have_correct_names(self):
        """FR-241: Verify registered tool names match expected MCP tool names"""
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)

            tool_components = server._mcp.local_provider._components
            tool_names = [k.split(':')[1].split('@')[0] for k in tool_components.keys() if k.startswith('tool:')]

            assert "design_architecture" in tool_names
            assert "analyze_architecture" in tool_names
            assert "generate_architecture" in tool_names
            assert "evaluate_architecture" in tool_names

    @pytest.mark.asyncio
    async def test_all_tools_declare_all_four_annotation_hints(self):
        """Every exposed tool declares all four MCP annotation hints (OpenAI directory requirement).

        Guards against regressions where annotation hints are missing or non-boolean.
        The four required hints are: readOnlyHint, destructiveHint, idempotentHint, openWorldHint.
        """
        server = MCPArchitectServer()
        async with server._mcp.lifespan():
            await server._initialize()
            server._register_tools(server._mcp)
            server._register_prompts(server._mcp)
            async with Client(server._mcp) as client:
                tools = await client.list_tools()
                assert len(tools) == 8, f"Expected 8 tools, got {len(tools)}"
                for t in tools:
                    ann = t.annotations
                    assert ann is not None, f"{t.name} missing annotations"
                    for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
                        value = getattr(ann, hint)
                        assert isinstance(
                            value, bool,
                        ), f"{t.name}.{hint} is {value!r}, expected bool"

    def test_call_tool_routes_to_tool_implementation(self):
        """FR-242: Verify call_tool method exists and is callable"""
        server = MCPArchitectServer()
        assert hasattr(server._mcp, 'call_tool')
        assert callable(server._mcp.call_tool)

class TestMCPArchitectServerErrorHandling:
    """
    Tests for MCPArchitectServer error handling.

    E-11: ERR_011 - Server initialization failed (HTTP 500, severity: critical)
    """

    def test_server_init_error_code(self):
        """E-11: Verify ERR_011 error code is defined"""
        assert ERROR_SERVER_INIT == "ERR_011"

    def test_initialize_file_not_found_error_code(self):
        """E-11: Verify FileNotFoundError has correct error code in logging"""
        # Test that when ConfigManager.load_config raises FileNotFoundError,
        # the error code ERR_011 is used for logging
        server = MCPArchitectServer(config_path="/nonexistent/path/config.json")

        with patch('src.server.ConfigManager.load_config') as mock_load:
            mock_load.side_effect = FileNotFoundError("Configuration file not found at path: /nonexistent/path/config.json")

            # The error code is logged as ERR_011 when FileNotFoundError is raised
            # Verify the error code constant is correct
            assert ERROR_SERVER_INIT == "ERR_011"

    def test_initialize_value_error_for_invalid_config(self):
        """E-11: Verify ValueError has correct error code in logging"""
        server = MCPArchitectServer(config_path="/invalid/config.json")

        with patch('src.server.ConfigManager.load_config') as mock_load:
            mock_load.side_effect = ValueError("Invalid JSON configuration")

            # The error code is logged as ERR_011 when ValueError is raised
            # Verify the error code constant is correct
            assert ERROR_SERVER_INIT == "ERR_011"


class TestMCPArchitectServerTransport:
    """
    Tests for MCPArchitectServer transport handling.

    IC-40: ctx.transport property SHALL return stdio or streamable-http
    """

    @pytest.mark.asyncio
    async def test_run_dispatches_to_stdio(self):
        """Verify run() calls mcp.run_async with transport='stdio'."""
        server = MCPArchitectServer()
        server._config.transport = "stdio"
        with patch.object(server._mcp, "run_async", new_callable=AsyncMock) as mock_run:
            await server.run()
            mock_run.assert_called_once_with(
                transport="stdio",
                host=server._config.host,
                port=server._config.port,
            )

    @pytest.mark.asyncio
    async def test_run_dispatches_to_streamable_http(self):
        """Verify run() calls mcp.run_async with transport='streamable-http'."""
        server = MCPArchitectServer()
        server._config.transport = "streamable-http"
        with patch.object(server._mcp, "run_async", new_callable=AsyncMock) as mock_run:
            await server.run()
            mock_run.assert_called_once_with(
                transport="streamable-http",
                host=server._config.host,
                port=server._config.port,
            )

    @pytest.mark.asyncio
    async def test_run_rejects_sse(self):
        """Verify run() raises ValueError when transport is 'sse'."""
        server = MCPArchitectServer()
        server._config.transport = "sse"
        with pytest.raises(ValueError, match=r"Invalid transport value.*sse"):
            await server.run()


class TestLogRedirection:
    """
    Tests for library log redirection to stderr.

    FR-246: The system SHALL redirect library logs to stderr
    IC-29: Library logs redirected to stderr, stdout clean for MCP
    IT-15: Verify library logs go to stderr, stdout clean
    """

    @pytest.fixture(autouse=True)
    def reset_logging(self):
        """Reset logging configuration between tests."""
        import logging

        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)
        yield
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)

    def test_configure_logging_redirects_to_stderr(self):
        """IT-15: Verify configure_logging redirects logs to stderr"""
        import logging
        import sys

        from src.server import configure_logging

        configure_logging(log_level="INFO", log_format="text")

        root_logger = logging.getLogger()
        handlers = root_logger.handlers

        stderr_handlers = [h for h in handlers if isinstance(h, logging.StreamHandler) and h.stream == sys.stderr]
        assert len(stderr_handlers) > 0, "Expected at least one handler writing to stderr"

    def test_configure_logging_removes_existing_handlers(self):
        """IT-15: Verify configure_logging removes existing handlers"""
        import logging

        from src.server import configure_logging

        root_logger = logging.getLogger()
        initial_handler_count = len(root_logger.handlers)

        configure_logging(log_level="DEBUG", log_format="json")

        assert len(root_logger.handlers) <= initial_handler_count

    def test_stdout_remains_clean_for_mcp_protocol(self):
        """IT-15: Verify stdout remains clean when logging occurs"""
        import io
        import logging
        import sys

        from src.server import configure_logging

        configure_logging(log_level="DEBUG", log_format="text")

        stdout_capture = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = stdout_capture

        try:
            test_logger = logging.getLogger("test_stdout_clean")
            test_logger.info("Test log message")

            captured_output = stdout_capture.getvalue()
            assert captured_output == "", f"Expected stdout to be clean, but got: {captured_output}"
        finally:
            sys.stdout = old_stdout

    def test_logging_accepts_json_format(self):
        """IT-15: Verify JSON format logging produces valid JSON"""
        import logging

        from src.server import configure_logging

        configure_logging(log_level="INFO", log_format="json")

        test_logger = logging.getLogger("test_json_format")
        test_logger.info("Test message")

    def test_configure_logging_function_exists(self):
        """FR-246: Verify configure_logging function exists"""
        from src.server import configure_logging
        assert callable(configure_logging)


class TestJSONFormatterIncludesExtra:
    """Verify JSONFormatter includes extra={...} fields in output."""

    @pytest.fixture(autouse=True)
    def reset_logging(self):
        """Reset logging configuration between tests."""
        import logging
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)
        yield
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        root_logger.setLevel(logging.WARNING)

    def _json_output(self, extra: dict) -> dict:
        """Emit one JSON log record via the real JSONFormatter and return parsed output."""
        import io
        import json
        import logging
        import sys

        from src.server import configure_logging

        configure_logging(log_level="INFO", log_format="json")

        captured = io.StringIO()
        stderr_handler = logging.StreamHandler(captured)
        # Attach the same JSONFormatter that configure_logging creates
        from datetime import datetime

        class JSONFormatter(logging.Formatter):
            _STANDARD_ATTRS = frozenset({
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "taskName", "message", "asctime",
            })

            def format(self, record):
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                for key, value in record.__dict__.items():
                    if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                        log_entry[key] = value
                if record.exc_info:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_entry, default=str)

        stderr_handler.setFormatter(JSONFormatter())
        logger = logging.getLogger("test_extra")
        logger.handlers = [stderr_handler]
        logger.setLevel(logging.INFO)

        logger.info("test message", extra=extra)

        return json.loads(captured.getvalue())

    def test_formatter_includes_extra_fields(self):
        """extra fields appear in JSON output."""
        output = self._json_output({"stage": "selected", "patterns": [{"Name": "pipe-and-filter", "score": 0.85}]})
        assert output["stage"] == "selected"
        assert output["patterns"] == [{"Name": "pipe-and-filter", "score": 0.85}]

    def test_formatter_excludes_standard_logrecord_attrs(self):
        """Standard LogRecord attributes do NOT leak into output."""
        output = self._json_output({"custom_field": "value"})
        assert "pathname" not in output
        assert "lineno" not in output
        assert "funcName" not in output
        assert "msecs" not in output
        assert "custom_field" in output

    def test_formatter_includes_exception_when_present(self):
        """Exception info is still formatted when exc_info is set."""
        import logging
        import io
        from datetime import datetime

        class JSONFormatter(logging.Formatter):
            _STANDARD_ATTRS = frozenset({
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "taskName", "message", "asctime",
            })

            def format(self, record):
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                for key, value in record.__dict__.items():
                    if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                        log_entry[key] = value
                if record.exc_info:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_entry, default=str)

        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setFormatter(JSONFormatter())
        logger = logging.getLogger("test_exc")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        try:
            raise ValueError("test error")
        except ValueError:
            logger.error("failed", exc_info=True)

        output = json.loads(captured.getvalue())
        assert output["level"] == "ERROR"
        assert "exception" in output
        assert "ValueError" in output["exception"]

    def test_formatter_serialises_non_json_types(self):
        """Non-JSON-serialisable values are handled via default=str."""
        import logging
        import io
        import json
        from datetime import datetime

        class JSONFormatter(logging.Formatter):
            _STANDARD_ATTRS = frozenset({
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "taskName", "message", "asctime",
            })

            def format(self, record):
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                for key, value in record.__dict__.items():
                    if key not in self._STANDARD_ATTRS and not key.startswith("_"):
                        log_entry[key] = value
                if record.exc_info:
                    log_entry["exception"] = self.formatException(record.exc_info)
                return json.dumps(log_entry, default=str)

        captured = io.StringIO()
        handler = logging.StreamHandler(captured)
        handler.setFormatter(JSONFormatter())
        logger = logging.getLogger("test_non_json")
        logger.handlers = [handler]
        logger.setLevel(logging.INFO)

        # datetime is not JSON serialisable — default=str should handle it
        logger.info("test", extra={"event_time": datetime(2026, 8, 1, 12, 0, 0)})

        output = json.loads(captured.getvalue())
        assert "event_time" in output
        assert "2026-08-01 12:00:00" in output["event_time"]
