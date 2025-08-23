"""
Centralized logging configuration for the application.
"""

import logging
import sys
import os
import argparse
from typing import Optional


class WorkflowLogger:
    """Centralized logger factory with global level control."""

    _loggers: dict[str, logging.Logger] = {}
    _global_level: Optional[int] = None
    _initialized = False

    @classmethod
    def _initialize_global_level(cls) -> None:
        """Initialize global logging level from environment or CLI args."""
        if cls._initialized:
            return

        cls._initialized = True

        # Check environment variable first
        env_level = os.getenv("LOG_LEVEL", "").upper()
        if env_level:
            cls._global_level = getattr(logging, env_level, None)
            if cls._global_level:
                return

        # Check CLI args if available
        try:
            # Parse only known args to avoid conflicts with main app args
            parser = argparse.ArgumentParser(add_help=False)
            parser.add_argument("--log-level", type=str, help="Set logging level")
            args, _ = parser.parse_known_args()

            if args.log_level:
                level_name = args.log_level.upper()
                cls._global_level = getattr(logging, level_name, None)
                if not cls._global_level:
                    print(f"Warning: Invalid log level '{args.log_level}', using INFO")
                    cls._global_level = logging.INFO
        except:
            # If CLI parsing fails, continue with defaults
            pass

    @classmethod
    def get_logger(
        cls, name: str = "workflow", level: int = logging.INFO
    ) -> logging.Logger:
        """
        Get or create a configured logger with global level override.

        Args:
            name: Logger name (typically __name__ from calling module)
            level: Default logging level (overridden by global setting)

        Returns:
            Configured logger instance
        """
        cls._initialize_global_level()

        # Use global level if set, otherwise use provided level
        effective_level = cls._global_level if cls._global_level is not None else level

        if name in cls._loggers:
            logger = cls._loggers[name]
            # Update level if global level changed
            logger.setLevel(effective_level)
            return logger

        # Create logger
        logger = logging.getLogger(name)
        logger.setLevel(effective_level)

        # Avoid duplicate handlers
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.propagate = False

        cls._loggers[name] = logger
        return logger

    @classmethod
    def set_global_level(cls, level: int) -> None:
        """Set global logging level for all current and future loggers."""
        cls._global_level = level
        # Update existing loggers
        for logger in cls._loggers.values():
            logger.setLevel(level)

    @classmethod
    def get_all_loggers(cls) -> dict[str, logging.Logger]:
        """Get all created loggers."""
        return cls._loggers.copy()


# Convenience functions
def get_logger(name: str = "workflow", level: int = logging.INFO) -> logging.Logger:
    """
    Convenience function to get a configured logger with global level support.

    Usage:
        from src.app.utils.logger import get_logger
        logger = get_logger(__name__)

    Global level can be set via:
        - Environment: LOG_LEVEL=DEBUG python -m src.app.tools.search_files
        - CLI arg: python -m src.app.tools.search_files --log-level debug
    """
    return WorkflowLogger.get_logger(name, level)


def get_workflow_logger() -> logging.Logger:
    """Get the main workflow logger."""
    return WorkflowLogger.get_logger("workflow")


def get_debug_logger() -> logging.Logger:
    """Get a debug-level logger (respects global level override)."""
    return WorkflowLogger.get_logger("debug", logging.DEBUG)


def log_context_size(
    logger: logging.Logger, context: str, context_name: str = "context"
) -> None:
    """
    Log detailed size information for context strings.

    Args:
        logger: Logger instance to use
        context: The context string to analyze
        context_name: Name/description of the context for logging
    """
    if not isinstance(context, str):
        logger.debug(
            "🔍 %s: Non-string context of type %s", context_name, type(context).__name__
        )
        return

    char_count = len(context)
    line_count = context.count("\n") + 1 if context else 0
    estimated_tokens = char_count // 4

    logger.debug(
        "🔍 %s size - Chars: %d, Lines: %d, Est. Tokens: %d",
        context_name,
        char_count,
        line_count,
        estimated_tokens,
    )

    # Log preview for large contexts
    if char_count > 1000:
        preview = (
            context[:500] + "..." + context[-300:]
            if len(context) > 800
            else context[:800] + "..."
        )
        logger.debug("🔍 %s preview: %s", context_name, preview)


# Module-level logger
module_logger = WorkflowLogger.get_logger(__name__)
