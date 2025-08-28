"""
Centralized logging configuration with file output support.
"""

import logging
import sys
import os
from typing import Optional
from datetime import datetime


class WorkflowLogger:
    """Centralized logger factory with global level control and file output."""

    _loggers: dict[str, logging.Logger] = {}
    _global_level: Optional[int] = None
    _initialized = False
    _log_file: Optional[str] = None

    @classmethod
    def set_log_file(cls, log_file: str) -> None:
        """Set log file path for all loggers."""
        cls._log_file = log_file
        # Update existing loggers to include file handler
        for logger in cls._loggers.values():
            cls._update_file_handler(logger)

    @classmethod
    def _update_file_handler(cls, logger: logging.Logger) -> None:
        """Update file handler for logger, removing existing ones first."""
        # Remove any existing file handlers
        for handler in logger.handlers[:]:
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)

        if not cls._log_file:
            return

        # Create logs directory if it doesn't exist
        os.makedirs(os.path.dirname(cls._log_file), exist_ok=True)

        file_handler = logging.FileHandler(cls._log_file)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # ✅ "asctime" is correct
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    @classmethod
    def set_global_level(cls, level: int) -> None:
        """Set global logging level."""
        cls._global_level = level
        # Update level for all existing loggers
        for logger in cls._loggers.values():
            logger.setLevel(level)

    @classmethod
    def configure_from_settings(
        cls, log_level: Optional[str] = None, log_file: Optional[str] = None
    ) -> None:
        """Configure logger from settings."""
        if log_level:
            level_name = log_level.upper()
            cls._global_level = getattr(logging, level_name, logging.INFO)
            print(f"Setting log level to: {level_name} ({cls._global_level})")

        if log_file:
            cls.set_log_file(log_file)
            print(f"Log file set to: {log_file}")

    @classmethod
    def get_logger(
        cls, name: str = "workflow", level: int = logging.INFO
    ) -> logging.Logger:
        """Get or create a configured logger with global level override."""
        effective_level = cls._global_level if cls._global_level is not None else level

        if name in cls._loggers:
            logger = cls._loggers[name]
            logger.setLevel(effective_level)
            return logger

        logger = logging.getLogger(name)
        logger.setLevel(effective_level)

        if not logger.handlers:
            # Console handler
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            # File handler if log file is set
            if cls._log_file:
                cls._update_file_handler(logger)

            logger.propagate = False

        cls._loggers[name] = logger
        return logger


# Convenience functions
def get_logger(name: str = "workflow", level: int = logging.INFO) -> logging.Logger:
    return WorkflowLogger.get_logger(name, level)


def setup_file_logging(log_file: Optional[str] = None) -> str:
    """
    Setup file logging with automatic timestamped filename.
    """
    if not log_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = f"logs/app_run_{timestamp}.log"

    WorkflowLogger.set_log_file(log_file)
    return log_file


def configure_logging(settings) -> None:
    """
    Configure logging from a settings object that has LOG_LEVEL and LOG_FILE attributes.
    """
    # Get log settings from the settings object
    log_level = getattr(settings, "LOG_LEVEL", None)
    log_file = getattr(settings, "LOG_FILE", None)

    WorkflowLogger.configure_from_settings(log_level, log_file)
