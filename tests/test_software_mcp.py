from unittest.mock import Mock

from app.application.services.misc_services import McpService


def test_software_tool_is_exposed_to_mcp_with_registered_service():
    kb = Mock()
    software = Mock()
    software.list_tools.return_value = [{"id": "tool-1", "name": "echo", "description": "Echo", "input_schema": {"type": "object"}}]
    service = McpService(kb, software_service=software)
    tools = {tool["name"] for tool in service.list_tools()["tools"]}
    assert "invoke_software_tool" in tools
