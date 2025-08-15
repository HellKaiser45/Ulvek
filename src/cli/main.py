import asyncio
import json
from typing import Optional, Dict, Any
import httpx
import typer
from httpx_sse import aconnect_sse
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.live import Live
from rich.markdown import Markdown

# --- Configuration ---
DEFAULT_BASE_URL = "http://localhost:8000"

# --- Rich Console ---
console = Console()

# --- Typer App ---
app = typer.Typer(help="Ulvek API CLI with unified event support", no_args_is_help=True)


class UnifiedEventProcessor:
    """
    Processes all event types from the unified event system.
    Handles both workflow events (converted to AG-UI text messages)
    and direct AG-UI events from agents and tools.
    """

    def __init__(self, client: httpx.AsyncClient, conv_id: str, answer_url: str):
        self.client = client
        self.conv_id = conv_id
        self.answer_url = answer_url
        self.current_message = ""
        self.current_message_id: Optional[str] = None
        self.tool_calls: Dict[str, str] = {}
        self.events_received = 0

    async def process_event(self, event_data: Dict[str, Any]) -> Optional[str]:
        """
        Process any event type, await user input if needed, and return
        displayable content.
        Returns:
            str: Content for live display, or None if handled statically.
        """
        self.events_received += 1
        event_type = event_data.get("type")

        # Debug: log all events
        console.print(
            f"[dim]Event #{self.events_received}: {event_type}[/dim]", end=" "
        )

        match event_type:
            case "text_message_start":
                self.current_message = ""
                self.current_message_id = event_data.get("message_id")
                console.print("[dim green]✓[/dim green]")
                # Clear the live display for the new message
                return ""

            case "text_message_content":
                if event_data.get("message_id") == self.current_message_id:
                    self.current_message += event_data.get("delta", "")
                    console.print("[dim green]✓[/dim green]")
                    return self.current_message
                console.print("[dim yellow]⚠[/dim yellow]")
                return None

            case "text_message_end":
                if event_data.get("message_id") == self.current_message_id:
                    # The message is complete, print it statically and clear the live view
                    console.print("[dim green]✓[/dim green]")
                    console.print("\n" + "=" * 50)
                    console.print(Markdown(self.current_message))
                    console.print("=" * 50 + "\n")
                    self.current_message = ""
                    self.current_message_id = None
                    return ""
                console.print("[dim yellow]⚠[/dim yellow]")
                return None

            case "tool_call_start":
                tool_call_id = str(event_data.get("tool_call_id"))
                tool_name = event_data.get("tool_call_name", "unknown_tool")
                self.tool_calls[tool_call_id] = tool_name
                console.print("[dim green]✓[/dim green]")
                console.print(f"\n🔧 [cyan]Calling tool:[/cyan] {tool_name}")
                return None

            case "tool_call_end":
                tool_call_id = str(event_data.get("tool_call_id"))
                tool_name = self.tool_calls.get(tool_call_id, "unknown")
                console.print("[dim green]✓[/dim green]")
                console.print(f"✅ [green]Tool completed:[/green] {tool_name}")
                return None

            case "tool_call_result":
                content = event_data.get("content", "")
                console.print("[dim green]✓[/dim green]")
                console.print(
                    Panel(
                        content,
                        title="🔧 Tool Result",
                        border_style="yellow",
                        padding=(1, 2),
                    )
                )
                return None

            case "custom":
                console.print("[dim green]✓[/dim green]")
                if event_data.get("name") == "requestInput":
                    # This method is async and will handle prompting the user
                    await self._handle_user_input(event_data.get("value", {}))
                return None

            case "error":
                error_msg = event_data.get("message", "Unknown error")
                console.print("[dim red]✗[/dim red]")
                console.print(f"❌ [bold red]Error:[/bold red] {error_msg}")
                return None

            case _:
                # Unknown event types
                console.print(f"[dim cyan]?[/dim cyan]")
                return None

    async def _handle_user_input(self, value: Dict[str, Any]):
        """Prompt user and send response back to the API."""
        prompt_text = value.get("prompt", "Input required:")
        kind = value.get("kind", "input")
        response_text = ""
        if kind == "confirm":
            response = Prompt.ask(
                f"[bold yellow]{prompt_text}[/bold yellow]",
                choices=["y", "n"],
                default="y",
            )
            response_text = "true" if response.lower() == "y" else "false"
        else:
            response_text = Prompt.ask(f"[bold yellow]{prompt_text}[/bold yellow]")

        answer_body = {
            "type": "custom",
            "name": "userInput",
            "value": {"text": response_text},
        }
        try:
            await self.client.post(self.answer_url, json=answer_body)
            console.print("[dim]✓ Response sent[/dim]")
        except httpx.HTTPError as e:
            console.print(f"[red]Failed to send response:[/red] {e}")


async def stream_and_process_events(conv_id: str, base_url: str) -> None:
    """Connect to SSE stream and process all unified events."""
    stream_url = f"{base_url}/stream/{conv_id}"
    answer_url = f"{base_url}/answer/{conv_id}"
    timeout = httpx.Timeout(300.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        processor = UnifiedEventProcessor(client, conv_id, answer_url)

        try:
            console.print(f"[dim]Connecting to {stream_url}...[/dim]")

            async with aconnect_sse(client, "GET", stream_url) as event_source:
                console.print(
                    "[dim green]Connected! Listening for events...[/dim green]\n"
                )

                with Live(console=console, auto_refresh=False) as live:
                    event_timeout = 30  # seconds

                    try:
                        async for sse in event_source.aiter_sse():
                            if not sse.data:
                                continue

                            try:
                                event_data = json.loads(sse.data)
                            except json.JSONDecodeError as e:
                                console.print(
                                    f"[red]Invalid JSON:[/red] {sse.data[:100]}..."
                                )
                                continue

                            display_content = await processor.process_event(event_data)
                            if display_content is not None:
                                live.update(Markdown(display_content), refresh=True)

                    except asyncio.TimeoutError:
                        console.print(
                            f"[yellow]No events received in {event_timeout}s[/yellow]"
                        )

            # Session completed
            console.print(
                f"\n[green]Session completed! Processed {processor.events_received} events.[/green]"
            )

        except httpx.HTTPStatusError as e:
            console.print(f"[red]Stream error {e.response.status_code}[/red]")
            if e.response.status_code == 404:
                console.print(
                    "[red]Conversation not found. Check the conversation ID.[/red]"
                )
        except httpx.ConnectError:
            console.print(
                f"[red]Cannot connect to {base_url}. Is the server running?[/red]"
            )
        except Exception as e:
            console.print(f"[red]Unexpected error during stream: {e}[/red]")


async def run_conversation(prompt: str, base_url: str) -> None:
    """Start a conversation and manage the full interaction loop."""
    start_url = f"{base_url}/start"
    params = {"prompt": prompt}
    timeout = httpx.Timeout(30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            console.print(f"[dim]Starting conversation at {start_url}...[/dim]")
            start_response = await client.post(start_url, params=params)
            start_response.raise_for_status()
            start_data = start_response.json()
            conv_id = start_data["conversation_id"]

            console.print(
                Panel(
                    f"Conversation ID: [bold]{conv_id}[/bold]\n"
                    f"Prompt: [italic]{prompt}[/italic]",
                    title="🚀 Starting Ulvek Session",
                    border_style="green",
                )
            )

            await stream_and_process_events(conv_id, base_url)

        except httpx.HTTPStatusError as e:
            console.print(
                f"[red]Failed to start ({e.response.status_code}):[/red] {e.response.text}"
            )
        except httpx.ConnectError:
            console.print(
                f"[red]Cannot connect to {base_url}. Is the server running?[/red]"
            )
        except httpx.RequestError as e:
            console.print(f"[red]Connection error:[/red] {e}")


@app.command()
def chat(
    prompt: str = typer.Argument(..., help="The initial prompt to send to the agent"),
    base_url: str = typer.Option(
        DEFAULT_BASE_URL, "--base-url", "-u", help="API base URL"
    ),
) -> None:
    """Start an interactive conversation with the Ulvek agents."""
    asyncio.run(run_conversation(prompt, base_url))


@app.command()
def debug(
    prompt: str = typer.Argument(..., help="The prompt to send for debugging"),
    base_url: str = typer.Option(
        DEFAULT_BASE_URL, "--base-url", "-u", help="API base URL"
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show all event details"
    ),
) -> None:
    """Debug mode with detailed event logging."""

    async def debug_conversation():
        console.print("[bold blue]🐛 DEBUG MODE ENABLED[/bold blue]")
        start_url = f"{base_url}/start"
        params = {"prompt": prompt}

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            try:
                start_response = await client.post(start_url, params=params)
                start_response.raise_for_status()
                start_data = start_response.json()
                conv_id = start_data["conversation_id"]
                answer_url = f"{base_url}/answer/{conv_id}"
                stream_url = f"{base_url}/stream/{conv_id}"

                console.print(f"[green]Started conversation {conv_id}[/green]\n")

                processor = UnifiedEventProcessor(client, conv_id, answer_url)

                async with aconnect_sse(client, "GET", stream_url) as event_source:
                    async for sse in event_source.aiter_sse():
                        if not sse.data:
                            continue

                        try:
                            event_data = json.loads(sse.data)
                            event_type = event_data.get("type", "unknown")

                            if verbose:
                                console.print(
                                    Panel(
                                        json.dumps(event_data, indent=2),
                                        title=f"Event: {event_type}",
                                        border_style="blue",
                                    )
                                )
                            else:
                                console.print(f"[blue]Event:[/blue] {event_type}")

                            await processor.process_event(event_data)
                        except json.JSONDecodeError:
                            console.print("[red]Invalid JSON in event[/red]")

                console.print("\n[green]Debug session completed.[/green]")
            except Exception as e:
                console.print(f"[red]Debug session failed:[/red] {e}")

    asyncio.run(debug_conversation())


if __name__ == "__main__":
    app()
