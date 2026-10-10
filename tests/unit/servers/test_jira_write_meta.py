"""Tests for UNI-335: write-tagged tools carry anthropic/requiresUserInteraction meta."""

import pytest
from fastmcp import Client

from mcp_atlassian.servers.jira import jira_mcp

EXPECTED_WRITE_COUNT = 25


@pytest.mark.anyio
async def test_write_tools_have_meta_and_read_tools_do_not():
    """Every tool: 'write' in tags ⟺ meta['anthropic/requiresUserInteraction'] is True."""
    tools = await jira_mcp.list_tools()
    assert tools, "jira_mcp has no registered tools"

    failures: list[str] = []
    for tool in tools:
        is_write = "write" in (tool.tags or set())
        has_flag = (tool.meta or {}).get("anthropic/requiresUserInteraction") is True
        if is_write != has_flag:
            failures.append(f"{tool.name}: write={is_write} has_meta_flag={has_flag}")

    assert not failures, "Mismatch between write tag and meta flag:\n" + "\n".join(
        failures
    )


@pytest.mark.anyio
async def test_exactly_25_write_tagged_tools():
    """Exactly 25 tools are tagged 'write'; fails if upstream adds or removes one."""
    tools = await jira_mcp.list_tools()
    write_tools = [t for t in tools if "write" in (t.tags or set())]
    assert len(write_tools) == EXPECTED_WRITE_COUNT, (
        f"Expected {EXPECTED_WRITE_COUNT} write-tagged tools, "
        f"got {len(write_tools)}: {[t.name for t in write_tools]}"
    )


@pytest.mark.anyio
async def test_wire_create_issue_has_requires_user_interaction():
    """Wire: jira_create_issue (create_issue) carries _meta.anthropic/requiresUserInteraction=true."""
    async with Client(jira_mcp) as client:
        tools = await client.list_tools()
        tool_map = {t.name: t.model_dump(by_alias=True) for t in tools}

    assert "create_issue" in tool_map, "create_issue not found in wire tool list"
    raw_meta = tool_map["create_issue"].get("_meta") or {}
    assert raw_meta.get("anthropic/requiresUserInteraction") is True, (
        f"create_issue _meta on wire: {raw_meta}"
    )


@pytest.mark.anyio
async def test_wire_get_issue_lacks_requires_user_interaction():
    """Wire: get_issue does NOT carry anthropic/requiresUserInteraction."""
    async with Client(jira_mcp) as client:
        tools = await client.list_tools()
        tool_map = {t.name: t.model_dump(by_alias=True) for t in tools}

    assert "get_issue" in tool_map, "get_issue not found in wire tool list"
    raw_meta = tool_map["get_issue"].get("_meta") or {}
    assert raw_meta.get("anthropic/requiresUserInteraction") is not True, (
        f"get_issue should NOT have requiresUserInteraction, but _meta={raw_meta}"
    )
