"""List (and optionally create) LLM serving endpoints for the analytics agent.

Databricks provides Foundation Model APIs as ready-to-use pay-per-token endpoints,
so in most workspaces you do NOT need to create anything - you just need the name
of an existing chat endpoint. This script prints the chat-capable endpoints in your
workspace so you can set DATABRICKS_LLM_ENDPOINT.

Usage (with Databricks auth configured via the CLI or env vars):

    python scripts/list_llm_endpoints.py

    # Attempt to create an endpoint that serves your own external model via key:
    python scripts/list_llm_endpoints.py --create-external \
        --name shop-assistant-llm \
        --provider openai --model gpt-4o-mini \
        --api-key-env OPENAI_API_KEY
"""

import argparse
import os

from databricks.sdk import WorkspaceClient

CHAT_TASK = "llm/v1/chat"


def list_endpoints(client: WorkspaceClient) -> None:
    print("Serving endpoints in this workspace:\n")
    found = False
    for endpoint in client.serving_endpoints.list():
        found = True
        name = endpoint.name or "(unnamed)"
        task = getattr(endpoint, "task", None) or "-"
        state = getattr(endpoint.state, "ready", None) if endpoint.state else None
        marker = "  <- chat" if task == CHAT_TASK or name.startswith("databricks-") else ""
        print(f"  {name:45}  task={task:14}  ready={state}{marker}")

    if not found:
        print("  (none)")
        print(
            "\nNo endpoints listed. Open the Databricks Playground (AI/ML > Playground) "
            "to confirm which Foundation Models your Free Edition workspace exposes, "
            "then set DATABRICKS_LLM_ENDPOINT to that model's name."
        )
    else:
        print(
            "\nCopy a chat endpoint name above into DATABRICKS_LLM_ENDPOINT "
            "(in .env or app.yaml)."
        )


def create_external(
    client: WorkspaceClient,
    name: str,
    provider: str,
    model: str,
    api_key_env: str,
) -> None:
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput,
        ExternalModel,
        ExternalModelConfig,
        ServedEntityInput,
    )

    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise SystemExit(
            f"Set {api_key_env} to your {provider} API key before running --create-external."
        )

    external_model = ExternalModel(
        name=model,
        provider=provider,
        task=CHAT_TASK,
        config=ExternalModelConfig(
            openai_config={"openai_api_key_plaintext": api_key}
        )
        if provider == "openai"
        else ExternalModelConfig(
            anthropic_config={"anthropic_api_key_plaintext": api_key}
        ),
    )

    print(f"Creating external model endpoint '{name}' ({provider}/{model})...")
    client.serving_endpoints.create_and_wait(
        name=name,
        config=EndpointCoreConfigInput(
            served_entities=[
                ServedEntityInput(name=model, external_model=external_model)
            ]
        ),
    )
    print(f"Done. Set DATABRICKS_LLM_ENDPOINT={name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create-external", action="store_true")
    parser.add_argument("--name", default="shop-assistant-llm")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic"])
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    args = parser.parse_args()

    client = WorkspaceClient()

    if args.create_external:
        create_external(client, args.name, args.provider, args.model, args.api_key_env)
    else:
        list_endpoints(client)


if __name__ == "__main__":
    main()
