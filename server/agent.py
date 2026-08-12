"""Custom stateful analytics agent built on LangGraph.

The agent orchestrates a reasoning LLM (Databricks model serving) with a single
tool, Databricks Genie, which queries trusted Gold-layer data governed by Unity
Catalog. Conversation state and per-step checkpoints are persisted in Lakebase
through the LangGraph PostgresSaver, so each thread resumes exactly where it left off.
"""

import os
import threading
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from server.checkpointer import get_checkpointer
from server.genie import query_genie

SYSTEM_PROMPT = (
    "You are the analytics assistant for a small retail shop owner. You answer "
    "questions about stock, sales, reorders, dead stock, and expiries. Always ground "
    "quantitative answers in data from the query_genie tool, which reads the shop's "
    "trusted Gold-layer tables governed by Unity Catalog. Never invent numbers. If "
    "Genie returns nothing useful, say so plainly. Reply in short, plain sentences a "
    "busy shopkeeper can act on, and use rupees for currency."
)

# Chat-capable Foundation Model endpoints, in order of preference. The workspace
# provisions these as pay-per-token system endpoints (no setup required); we pick
# the first one that actually exists. Override with DATABRICKS_LLM_ENDPOINT.
_PREFERRED_ENDPOINTS = [
    "databricks-claude-3-7-sonnet",
    "databricks-meta-llama-3-3-70b-instruct",
    "databricks-meta-llama-3-1-70b-instruct",
    "databricks-gpt-oss-120b",
    "databricks-gpt-oss-20b",
    "databricks-llama-4-maverick",
    "databricks-mixtral-8x7b-instruct",
]

_CHAT_TASK = "llm/v1/chat"

_TOOLS = [query_genie]

_agent = None
_lock = threading.Lock()


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def _resolve_endpoint() -> str:
    """Return the LLM serving endpoint to use.

    Uses DATABRICKS_LLM_ENDPOINT when set, otherwise discovers a chat-capable
    Foundation Model endpoint already available in the workspace.
    """
    configured = os.environ.get("DATABRICKS_LLM_ENDPOINT")
    if configured:
        return configured

    from databricks.sdk import WorkspaceClient

    available: list[str] = []
    for endpoint in WorkspaceClient().serving_endpoints.list():
        name = endpoint.name or ""
        task = getattr(endpoint, "task", None)
        if task == _CHAT_TASK or name.startswith("databricks-"):
            available.append(name)

    for preferred in _PREFERRED_ENDPOINTS:
        if preferred in available:
            return preferred
    if available:
        return available[0]

    raise RuntimeError(
        "No chat LLM serving endpoint found in this workspace. Open the Databricks "
        "Playground to confirm an available model, then set DATABRICKS_LLM_ENDPOINT "
        "(or run scripts/list_llm_endpoints.py to see your options)."
    )


def _build_agent():
    from databricks_langchain import ChatDatabricks

    llm = ChatDatabricks(endpoint=_resolve_endpoint())
    llm_with_tools = llm.bind_tools(_TOOLS)

    def agent_node(state: AgentState) -> dict:
        response = llm_with_tools.invoke(
            [SystemMessage(content=SYSTEM_PROMPT), *state["messages"]]
        )
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(_TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")

    return graph.compile(checkpointer=get_checkpointer())


def get_agent():
    """Lazily compile the agent once and reuse it across requests."""
    global _agent
    if _agent is None:
        with _lock:
            if _agent is None:
                _agent = _build_agent()
    return _agent


def run_turn(thread_id: str, message: str) -> str:
    """Run one conversational turn, resuming any prior state for ``thread_id``."""
    agent = get_agent()
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"messages": [HumanMessage(content=message)]}, config)

    reply = result["messages"][-1].content
    if isinstance(reply, list):
        # Some providers return content as a list of blocks.
        reply = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in reply
        )
    return reply or "I couldn't produce an answer."
