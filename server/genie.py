"""Databricks Genie tool for the analytics agent.

Genie is the analytics engine: it translates natural-language questions into
governed SQL over the shop's trusted Gold-layer tables in Unity Catalog and returns
the answer. The agent calls this as a tool; Genie enforces Unity Catalog governance.
"""

import os
from functools import lru_cache

from databricks.sdk import WorkspaceClient
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# Cap how many result rows we feed back into the LLM context.
_MAX_ROWS = 20

# Genie is itself conversational. Keep one Genie conversation per agent thread so
# follow-up questions retain Genie's own context. This is a best-effort in-memory
# cache; the authoritative agent state lives in Lakebase via the checkpointer.
_genie_conversations: dict[str, str] = {}


@lru_cache(maxsize=1)
def _client() -> WorkspaceClient:
    return WorkspaceClient()


@tool
def query_genie(question: str, config: RunnableConfig) -> str:
    """Answer a question about the shop's trusted retail analytics with Databricks Genie.

    Use this for anything quantitative: sales, revenue, units sold, stock on hand,
    days of cover, slow-moving or dead stock, expiries, and reorder needs. Genie
    turns the natural-language question into governed SQL over Unity Catalog
    Gold-layer data and returns the answer plus any table it produced. Pass a
    specific, self-contained question.
    """
    space_id = os.environ["GENIE_SPACE_ID"]
    thread_id = (config.get("configurable") or {}).get("thread_id", "default")
    client = _client()

    try:
        conversation_id = _genie_conversations.get(thread_id)
        if conversation_id is None:
            message = client.genie.start_conversation_and_wait(space_id, question)
            _genie_conversations[thread_id] = message.conversation_id
        else:
            message = client.genie.create_message_and_wait(
                space_id, conversation_id, question
            )
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, never crash the chat
        # Drop the possibly-poisoned conversation so the next turn starts fresh.
        _genie_conversations.pop(thread_id, None)
        return (
            "Genie could not answer that question. It may fall outside this Genie "
            "space's data (for example asking about sales when the space only covers "
            f"the product catalog), or the query failed to run. Details: {exc}"
        )

    return _render_message(client, space_id, message)


def _render_message(client: WorkspaceClient, space_id: str, message) -> str:
    if message.error is not None:
        return f"Genie could not answer: {message.error.error}"

    parts: list[str] = []
    for attachment in message.attachments or []:
        if attachment.text and attachment.text.content:
            parts.append(attachment.text.content.strip())
        if attachment.query:
            if attachment.query.description:
                parts.append(attachment.query.description.strip())
            table = _render_query_result(
                client, space_id, message, attachment.attachment_id
            )
            if table:
                parts.append(table)

    return "\n\n".join(part for part in parts if part) or "Genie returned no answer."


def _render_query_result(
    client: WorkspaceClient, space_id: str, message, attachment_id: str
) -> str:
    response = client.genie.get_message_attachment_query_result(
        space_id, message.conversation_id, message.message_id, attachment_id
    )
    statement = response.statement_response
    if statement is None or statement.result is None:
        return ""

    rows = statement.result.data_array or []
    if not rows:
        return ""

    columns: list[str] = []
    if statement.manifest and statement.manifest.schema:
        columns = [column.name for column in statement.manifest.schema.columns]

    lines: list[str] = []
    if columns:
        lines.append(" | ".join(columns))
    for row in rows[:_MAX_ROWS]:
        lines.append(" | ".join("" if value is None else str(value) for value in row))
    if len(rows) > _MAX_ROWS:
        lines.append(f"... ({len(rows) - _MAX_ROWS} more rows)")

    return "\n".join(lines)
