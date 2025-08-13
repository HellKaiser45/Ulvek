"""
Terminal command execution tools with improved safety and escaping handling.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Union
import subprocess
import time
import os
import logging
from pathlib import Path

from src.app.utils.logger import get_logger

# Setup module-specific logger
logger = get_logger(__name__)


class TerminalCommand(BaseModel):
    """Configuration for a single terminal command with safe argument handling."""

    command: str = Field(
        ..., description="The command to execute (e.g., 'python', 'ls')"
    )
    args: List[str] = Field(
        default_factory=list,
        description="Command arguments as a list of strings (automatically escaped)",
    )
    working_directory: Optional[str] = Field(
        None, description="Working directory for command execution"
    )
    timeout: Optional[int] = Field(30, description="Command timeout in seconds")
    env_vars: Optional[Dict[str, str]] = Field(
        None, description="Additional environment variables"
    )
    capture_output: bool = Field(
        True, description="Whether to capture stdout and stderr"
    )

    @field_validator("command")
    @classmethod
    def _validate_command(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Command cannot be empty")
        return v.strip()

    @field_validator("working_directory")
    @classmethod
    def _validate_working_directory(cls, v: Optional[str]) -> Optional[str]:
        if v and not Path(v).exists():
            raise ValueError(f"Working directory does not exist: {v}")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "command": "python",
                "args": ["-c", "print('Hello World')"],
                "working_directory": "/home/user",
                "timeout": 10,
                "capture_output": True,
            }
        }
    }


class CommandResult(BaseModel):
    """Result of a single command execution."""

    command: str
    full_command: str
    return_code: int
    stdout: Optional[str] = None
    stderr: Optional[str] = None
    execution_time: float
    success: bool
    error_message: Optional[str] = None


class TerminalExecutor:
    """Terminal command execution utility with improved safety."""

    @staticmethod
    def execute_single(command_config: TerminalCommand) -> CommandResult:
        """
        Execute a single terminal command with proper argument separation.

        Args:
            command_config: TerminalCommand configuration

        Returns:
            CommandResult: Execution result
        """
        start_time = time.time()

        # Build the full command string for display
        full_command = command_config.command
        if command_config.args:
            full_command += " " + " ".join(repr(arg) for arg in command_config.args)

        logger.info("🔧 Executing command: %s", full_command)
        logger.debug(
            "🔧 Command config: working_dir=%s, timeout=%s, capture_output=%s",
            command_config.working_directory,
            command_config.timeout,
            command_config.capture_output,
        )

        env = os.environ.copy()
        if command_config.env_vars:
            env.update(command_config.env_vars)
            logger.debug(
                "🔧 Added %d environment variables", len(command_config.env_vars)
            )

        cwd = command_config.working_directory or os.getcwd()
        process = None
        stdout = stderr = None

        try:
            # Build command list - this automatically handles escaping
            cmd_list = [command_config.command] + command_config.args

            logger.debug("🔧 Command list: %s", cmd_list)

            process = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE if command_config.capture_output else None,
                stderr=subprocess.PIPE if command_config.capture_output else None,
                env=env,
                cwd=cwd,
                text=True,
            )

            stdout, stderr = process.communicate(timeout=command_config.timeout)
            execution_time = time.time() - start_time
            success = process.returncode == 0

            # Log command output
            if stdout:
                logger.debug(
                    "✅ Command stdout (%d chars): %s",
                    len(stdout),
                    stdout[:200] + "..." if len(stdout) > 200 else stdout,
                )
            if stderr:
                logger.debug(
                    "⚠️  Command stderr (%d chars): %s",
                    len(stderr),
                    stderr[:200] + "..." if len(stderr) > 200 else stderr,
                )

            result = CommandResult(
                command=command_config.command,
                full_command=full_command,
                return_code=process.returncode,
                stdout=stdout if command_config.capture_output else None,
                stderr=stderr if command_config.capture_output else None,
                execution_time=execution_time,
                success=success,
                error_message=None
                if success
                else f"Command failed with return code {process.returncode}",
            )

            if success:
                logger.info("✅ Command succeeded in %.2fs", execution_time)
            else:
                logger.warning(
                    "❌ Command failed with return code %d after %.2fs",
                    process.returncode,
                    execution_time,
                )

            return result

        except subprocess.TimeoutExpired:
            if process is not None:
                process.kill()
                stdout, stderr = process.communicate()
            execution_time = time.time() - start_time

            logger.warning(
                "⏰ Command timed out after %d seconds", command_config.timeout
            )

            return CommandResult(
                command=command_config.command,
                full_command=full_command,
                return_code=-1,
                stdout=stdout if command_config.capture_output else None,
                stderr=stderr if command_config.capture_output else None,
                execution_time=execution_time,
                success=False,
                error_message=f"Command timed out after {command_config.timeout} seconds",
            )

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error("💥 Command execution failed: %s", e, exc_info=True)

            return CommandResult(
                command=command_config.command,
                full_command=full_command,
                return_code=-1,
                stdout=None,
                stderr=None,
                execution_time=execution_time,
                success=False,
                error_message=str(e),
            )


# ------------------ Pydantic AI Tools ------------------------------------
def run_command(
    command: str, args: Optional[List[str]] = None, **kwargs
) -> CommandResult:
    """
    Execute a single command with separate arguments (safe from escaping issues).

    Args:
        command: The command to execute (e.g., 'python', 'ls')
        args: List of arguments as separate strings
        **kwargs: Additional configuration (timeout, working_directory, etc.)

    Example:
        run_command("python", ["-c", "import sys; print(sys.version)"])
        run_command("ls", ["-la", "/home"])
    """
    if args is None:
        args = []

    logger.info("🚀 Running single command: %s", command)
    logger.debug("📝 Command args: %s, kwargs: %s", args, kwargs)

    config = TerminalCommand(command=command, args=args, **kwargs)
    result = TerminalExecutor.execute_single(config)

    logger.info(
        "🏁 Single command completed: success=%s, return_code=%d",
        result.success,
        result.return_code,
    )

    return result


class RunCommandsConfig(BaseModel):
    """Configuration for running multiple commands."""

    commands: List[Dict[str, Union[str, List[str]]]] = Field(
        ...,
        description="List of commands, each with 'command' and optional 'args' keys",
    )
    working_directory: Optional[str] = None
    timeout: Optional[int] = 30
    env_vars: Optional[Dict[str, str]] = None
    capture_output: bool = True
    stop_on_error: bool = True


def run_commands(cfg: RunCommandsConfig) -> List[CommandResult]:
    """
    Execute multiple commands sequentially.

    Args:
        cfg: RunCommandsConfig with list of commands and configuration

    Example:
        run_commands({
            "commands": [
                {"command": "echo", "args": ["Starting process..."]},
                {"command": "python", "args": ["-c", "print('Hello')"]}
            ],
            "working_directory": "/home/user"
        })
    """
    logger.info("🚀 Running %d commands", len(cfg.commands))
    logger.debug(
        "📝 Config: working_dir=%s, timeout=%s, stop_on_error=%s",
        cfg.working_directory,
        cfg.timeout,
        cfg.stop_on_error,
    )

    results = []

    for i, cmd_spec in enumerate(cfg.commands):
        logger.info("🔧 Executing command %d/%d", i + 1, len(cfg.commands))

        # Extract command and args with proper type handling
        command_value = cmd_spec["command"]
        args_value = cmd_spec.get("args", [])

        # Ensure proper types
        if isinstance(command_value, list):
            # Handle case where command might be passed as a list (error case)
            command = command_value[0] if command_value else ""
            # Merge any additional command parts with args
            additional_args = command_value[1:] if len(command_value) > 1 else []
            args = additional_args + (
                args_value
                if isinstance(args_value, list)
                else [args_value]
                if args_value
                else []
            )
        else:
            command = command_value
            args = (
                args_value
                if isinstance(args_value, list)
                else [args_value]
                if args_value
                else []
            )

        logger.debug("📝 Command: %s, Args: %s", command, args)

        cmd_config = TerminalCommand(
            command=command,
            args=args,
            working_directory=cfg.working_directory,
            timeout=cfg.timeout,
            env_vars=cfg.env_vars,
            capture_output=cfg.capture_output,
        )

        result = TerminalExecutor.execute_single(cmd_config)
        results.append(result)

        # Log result
        logger.info(
            "📊 Command %d result: success=%s, return_code=%d, time=%.2fs",
            i + 1,
            result.success,
            result.return_code,
            result.execution_time,
        )

        # Stop on error if configured
        if not result.success and cfg.stop_on_error:
            logger.warning("🛑 Stopping execution due to command failure")
            break

    logger.info(
        "🏁 Completed %d/%d commands",
        len([r for r in results if r.success]),
        len(results),
    )
    return results
