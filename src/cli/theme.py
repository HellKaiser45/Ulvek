"""Rich console theming and color palette for CLI."""

from rich.console import Console
from rich.theme import Theme

# Consistent color palette
PRIMARY = "blue"
SUCCESS = "green"
WARNING = "yellow"
ERROR = "red"
INFO = "cyan"
SECONDARY = "magenta"
DIM = "bright_black"
HIGHLIGHT = "bright_white"

# Theme definition with semantic color names
custom_theme = Theme({
    "primary": PRIMARY,
    "success": SUCCESS,
    "warning": WARNING,
    "error": ERROR,
    "info": INFO,
    "secondary": SECONDARY,
    "dim": DIM,
    "highlight": HIGHLIGHT,
    "info.dim": f"{INFO} dim",
    "warning.dim": f"{WARNING} dim",
    "error.dim": f"{ERROR} dim",
    "success.dim": f"{SUCCESS} dim",
})

# Single shared console instance
console = Console(theme=custom_theme, record=True)

# Export for CLI-wide usage
__all__ = ["console", "PRIMARY", "SUCCESS", "WARNING", "ERROR", "INFO", "SECONDARY", "DIM", "HIGHLIGHT"]