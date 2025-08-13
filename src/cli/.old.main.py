"""
Interactive command-line interface for the Agentic Coding Assistant.
"""

import asyncio
import sys
from typing import Optional

import rich_click as click

from src.app.utils.logger import get_logger, WorkflowLogger
from src.app.workflow.graph import run_agent


# Setup CLI-specific logger
logger = get_logger("cli")


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """
    Agentic Coding Assistant CLI.

    A powerful AI-powered coding assistant that helps with code generation,
    analysis, and project management tasks.
    """
    if ctx.invoked_subcommand is None:
        # Show help if no command provided
        click.echo(cli.get_help(ctx))


@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--output", "-o", type=click.Path(), help="Save final session result to file"
)
def chat(verbose: bool, output: Optional[str]) -> None:
    """
    Start an interactive chat session with the agentic coding assistant.
    """
    # Configure logging level
    if verbose:
        WorkflowLogger.set_level(10)  # DEBUG level
        logger.info("Verbose logging enabled")

    logger.info("Starting interactive chat session")

    click.echo("Agentic Coding Assistant - Interactive Mode")
    click.echo("Type your requests and I'll help you with coding tasks.")
    click.echo("Type 'exit' or 'quit' to end the session.")
    click.echo("-" * 50)

    session_results = []

    try:
        while True:
            # Get user input
            prompt = click.prompt("You", type=str, prompt_suffix=" > ")

            # Check for exit commands
            if prompt.lower().strip() in ["exit", "quit"]:
                break

            # Skip empty prompts
            if not prompt.strip():
                continue

            logger.info("Processing user request: %s", prompt)

            try:
                # Run the workflow
                result = asyncio.run(run_agent(prompt))
                session_results.append(f"## Request\n{prompt}\n\n## Response\n{result}")

                # Display result
                click.echo("\nAssistant:")
                click.echo("-" * 20)
                click.echo(result)
                click.echo("-" * 20)
                click.echo()

                logger.info("Request processed successfully")

            except Exception as e:
                error_msg = f"Error processing request: {e}"
                logger.error(error_msg, exc_info=True)
                click.echo(f"\nError: {e}\n", err=True)

    except KeyboardInterrupt:
        click.echo("\n\nSession interrupted by user.")
    except Exception as e:
        logger.error("Chat session error: %s", e, exc_info=True)
        click.echo(f"\nSession error: {e}", err=True)
    finally:
        # Handle session output
        if output and session_results:
            try:
                from pathlib import Path

                final_output = "\n\n".join(session_results)
                Path(output).write_text(final_output, encoding="utf-8")
                click.echo(f"\nSession saved to {output}")
                logger.info("Session saved to %s", output)
            except Exception as e:
                logger.error("Failed to save session: %s", e)
                click.echo(f"\nFailed to save session: {e}", err=True)

        click.echo("\nGoodbye!")
        logger.info("Chat session ended")


@cli.command()
@click.option(
    "--format",
    "-f",
    type=click.Choice(["mermaid", "png"]),
    default="mermaid",
    help="Output format for workflow visualization",
)
@click.option("--output", "-o", type=click.Path(), help="Save diagram to file")
def visualize(format: str, output: Optional[str]) -> None:
    """
    Visualize the workflow graph structure.
    """
    try:
        from src.app.workflow.graph import graph

        if format == "mermaid":
            diagram = graph.get_graph().draw_mermaid()
            if output:
                from pathlib import Path

                Path(output).write_text(diagram, encoding="utf-8")
                click.echo(f"Mermaid diagram saved to {output}")
            else:
                click.echo(diagram)
        else:  # png
            try:
                png_data = graph.get_graph().draw_mermaid_png()
                if output:
                    from pathlib import Path

                    Path(output).write_bytes(png_data)
                    click.echo(f"PNG diagram saved to {output}")
                else:
                    click.echo("PNG output requires --output parameter", err=True)
                    sys.exit(1)
            except Exception as e:
                click.echo(f"PNG generation failed (requires pyppeteer): {e}", err=True)
                sys.exit(1)

    except Exception as e:
        logger.error("Visualization failed: %s", e, exc_info=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def version() -> None:
    """
    Show version information.
    """
    click.echo("Agentic Coding Assistant v0.1.0")


def main() -> None:
    """Main entry point."""
    try:
        cli()
    except SystemExit:
        raise
    except Exception as e:
        logger = get_logger("cli")
        logger.error("CLI error: %s", e, exc_info=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
