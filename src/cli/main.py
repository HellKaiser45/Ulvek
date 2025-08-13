# minimal_cli_with_httpx_sse.py
import asyncio
import httpx
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from typing import Optional

# --- Import httpx-sse ---
from httpx_sse import (
    aconnect_sse,
    ServerSentEvent,
)  # Import ServerSentEvent for type hints if needed
import json

# --- Configuration ---
DEFAULT_BASE_URL = "http://localhost:8000"

# --- Rich Console ---
console = Console()

# --- Typer App ---
app = typer.Typer(help="Minimal Ulvek API CLI with httpx-sse", no_args_is_help=True)

# --- Simplified Core Logic using httpx-sse ---


async def simple_stream_and_respond(conv_id: str, base_url: str):
    """Connects to the SSE stream using httpx-sse and displays basic events."""
    stream_url = f"{base_url}/stream/{conv_id}"
    answer_url = f"{base_url}/answer/{conv_id}"

    timeout = httpx.Timeout(3870.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Use aconnect_sse context manager
        async with aconnect_sse(client, "GET", stream_url) as event_source:
            # Iterate over ServerSentEvent objects
            async for sse in event_source.aiter_sse():
                # Access event fields directly
                # sse.event, sse.data, sse.id, sse.retry are available
                event_type = "message"  # Default SSE event type, adapt if your backend sends custom 'event:' field
                event_name = sse.event  # Use the SSE event type field
                # Parse data if it's JSON (assuming your events are JSON)
                try:
                    event_value = json.loads(sse.data) if sse.data else {}
                except json.JSONDecodeError:
                    event_value = {"raw_data": sse.data}  # Fallback if data isn't JSON

                # --- Process Events (same logic as before, but cleaner data access) ---
                if (
                    event_name == "displayMessage"
                ):  # Adjust condition based on your events
                    # Assuming event_value is the dict you sent, e.g., {"text": "..."}
                    message_text = event_value.get("text", "No text received")
                    console.print(Panel(f"[blue]{message_text}[/blue]", title="Agent"))

                elif event_name == "requestUserInput":  # Adjust condition
                    user_input = Prompt.ask("[bold yellow]Your input[/bold yellow]")
                    answer_body = {
                        "type": "custom",  # Adjust based on your backend expectation
                        "name": "userInput",
                        "value": {"text": user_input},
                    }
                    await client.post(answer_url, json=answer_body)
                    console.print("[dim]Answer sent.[/dim]")

                elif event_name == "workflowComplete":  # Adjust condition
                    console.print("[bold green]Done![/bold green]")
                    return
                # Add other event handlers as needed


async def simple_run_conversation(prompt: str, base_url: str):
    """Starts a conversation and manages the streaming loop."""
    # Pass the prompt as a query parameter using 'params'
    start_url = f"{base_url}/start"
    params = {"prompt": prompt}  # <-- Create a dictionary for query parameters
    timeout = httpx.Timeout(3870.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        # Pass 'params=params' instead of 'json=...'
        start_response = await client.post(start_url, params=params)  # <-- Use 'params'
        start_response.raise_for_status()
        start_data = start_response.json()
        conv_id = start_data["conversation_id"]
        console.print(f"[green]Started conversation ID: {conv_id}[/green]")

        await simple_stream_and_respond(conv_id, base_url)


# --- Minimal Typer Command ---
@app.command()
def chat(
    prompt: str = typer.Argument(..., help="The initial prompt."),
    base_url: Optional[str] = typer.Option(
        None, "--base-url", "-u", help="API base URL."
    ),
):
    """Start a conversation."""
    resolved_base_url = base_url or DEFAULT_BASE_URL
    asyncio.run(simple_run_conversation(prompt, resolved_base_url))


# --- Entry Point ---
if __name__ == "__main__":
    app()
