# src/cli/main.py
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.styles import Style
from prompt_toolkit.history import InMemoryHistory

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.table import Table
from rich import box

from src.config import settings
from src.utils.logger import WorkflowLogger, get_logger
from src.workflow.graph import run_agent

# ------------------------------------------------------------------
# Typer app
# ------------------------------------------------------------------
app = typer.Typer(
    help="🤖 Agentic Coding Assistant CLI.",
    no_args_is_help=True,
    rich_markup_mode="markdown",
)
console = Console()

# ------------------------------------------------------------------
# Static assets
# ------------------------------------------------------------------
BANNER = r"""
[bold magenta]
┌──────────────────────────────────────────────────┐
│                                                  │
│    ██╗   ██╗██╗     ██╗   ██╗███████╗██╗  ██╗    │
│    ██║   ██║██║     ██║   ██║██╔════╝██║ ██╔╝    │
│    ██║   ██║██║     ██║   ██║█████╗  █████╔╝     │
│    ██║   ██║██║     ╚██╗ ██╔╝██╔══╝  ██╔═██╗     │
│    ╚██████╔╝███████╗ ╚████╔╝ ███████╗██║  ██╗    │
│     ╚═════╝ ╚══════╝  ╚═══╝  ╚══════╝╚═╝  ╚═╝    │
│                                                  │
└──────────────────────────────────────────────────┘
[/bold magenta]
[dim]A powerful AI-powered coding assistant.[/dim]
"""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def show_banner() -> None:
    console.print(BANNER)
    table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Description", style="dim")
    for cmd in app.registered_commands:
        if cmd.name and cmd.name != "main-callback":
            desc = (cmd.callback.__doc__ or "").split("\n")[0].strip()
            table.add_row(cmd.name, desc or "No description")
    console.print(table)
    console.print(Rule(style="dim"))


def show_markdown(content: str, title: Optional[str] = None) -> None:
    content = content.strip()
    md = Markdown(content)
    console.print(Panel(md, title=title, border_style="blue") if title else md)


# ------------------------------------------------------------------
# Global callback (banner)
# ------------------------------------------------------------------
@app.callback(invoke_without_command=True)
def main_callback() -> None:
    show_banner()


# ------------------------------------------------------------------
#  CHAT — sticky bottom rounded input
# ------------------------------------------------------------------
@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
) -> None:
    """Start an interactive chat session."""
    logger = get_logger("cli")
    if verbose:
        WorkflowLogger.set_level(10)

    transcript: list[str] = []
    kb = KeyBindings()
    buffer = Buffer(multiline=False)

    # 1. Enter submits
    @kb.add("enter")
    def _accept(event) -> None:  # noqa: ARG001
        event.app.exit(result=buffer.text)

    @kb.add("c-c")
    def _quit(event) -> None:  # noqa: ARG001
        event.app.exit(result=None)

    # Top scroll area
    history_win = Window(FormattedTextControl(""), wrap_lines=True)

    # Bottom rounded bar
    border_top = Window(
        FormattedTextControl([("class:border", "╭─💬 Type message (Ctrl-C to quit)")]),
        height=1,
    )
    input_line = Window(
        BufferControl(buffer=buffer),
        height=1,
        style="class:input",
    )
    border_bottom = Window(
        FormattedTextControl([("class:border", "╰─▶ ")]),
        height=1,
    )

    bottom = HSplit([border_top, input_line, border_bottom], height=3)
    layout = Layout(HSplit([history_win, bottom]), focused_element=input_line)

    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        style=Style.from_dict({"border": "bold #00e0ff", "input": "bold #ffffff"}),
    )

    try:
        while True:
            buffer.text = ""
            user = app.run()  # waits for Enter
            user = buffer.text.strip()
            if not user:
                continue  # noqa: PLR2004
            user = user.strip()
            if user.lower() in {"exit", "quit"}:
                break

            logger.info("User: %s", user)
            console.print(f"[bold green]You:[/bold green] {user}")
            transcript.append(f"**User:**\n{user}")

            with Status("[bold green]Thinking…[/bold green]", console=console):
                answer = asyncio.run(run_agent(user))

            console.print()
            console.print(Rule(style="dim"))
            show_markdown(answer)
            console.print(Rule(style="dim"))
            console.print()
            transcript.append(f"**Assistant:**\n{answer}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Session interrupted.[/yellow]")
    finally:
        if output and transcript:
            output.write_text("\n\n".join(transcript), encoding="utf-8")
            console.print(f"\n:white_check_mark: Saved → [link]{output}[/link]")
        console.print("\n[bold blue]Goodbye! 👋[/bold blue]")


# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
@app.command(name="config")
def show_config() -> None:
    """Display current configuration."""
    cfg = settings.model_dump()
    md = "## 🔧 Current Configuration  \n"
    for k, v in cfg.items():
        if k.upper().endswith("KEY"):
            v = "*" * 10 + str(v)[-4:] if str(v) else "*"
        md += f"- **`{k}`**: `{v}`  \n"
    show_markdown(md)


# ------------------------------------------------------------------
if __name__ == "__main__":
    app()
