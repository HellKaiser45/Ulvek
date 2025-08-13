"""
Centralized logging configuration for the application.
"""

import logging
import sys


class WorkflowLogger:
    """Centralized logger factory for consistent logging across the application."""

    _loggers: dict[str, logging.Logger] = {}

    @classmethod
    def get_logger(
        cls, name: str = "workflow", level: int = logging.INFO
    ) -> logging.Logger:
        """
        Get or create a configured logger with consistent formatting.

        Args:
            name: Logger name (typically __name__ from the calling module)
            level: Logging level (default: INFO)

        Returns:
            Configured logger instance
        """
        if name in cls._loggers:
            return cls._loggers[name]

        # Create logger
        logger = logging.getLogger(name)
        logger.setLevel(level)

        # Avoid duplicate handlers
        if not logger.handlers:
            # Console handler with custom formatting
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            # Prevent propagation to root logger to avoid duplicate logs
            logger.propagate = False

        cls._loggers[name] = logger
        return logger

    @classmethod
    def set_level(cls, level: int) -> None:
        """Set logging level for all created loggers."""
        for logger in cls._loggers.values():
            logger.setLevel(level)

    @classmethod
    def get_all_loggers(cls) -> dict[str, logging.Logger]:
        """Get all created loggers."""
        return cls._loggers.copy()


# Convenience function for easy importing
def get_logger(name: str = "workflow", level: int = logging.INFO) -> logging.Logger:
    """
    Convenience function to get a configured logger.

    Usage:
        from src.app.utils.logger import get_logger
        logger = get_logger(__name__)
    """
    return WorkflowLogger.get_logger(name, level)


# Pre-configured loggers for common use cases
def get_workflow_logger() -> logging.Logger:
    """Get the main workflow logger."""
    return WorkflowLogger.get_logger("workflow")


def get_debug_logger() -> logging.Logger:
    """Get a debug-level logger."""
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
    # Rough token estimation (4 chars ≈ 1 token, very rough approximation)
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


# Module-level logger for the logger module itself
module_logger = WorkflowLogger.get_logger(__name__)
