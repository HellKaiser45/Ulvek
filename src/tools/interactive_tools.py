"""
interactive_tools.py – synchronous utilities for interactive CLI prompts.
"""

from typing import List, Union


def prompt_user(prompt: Union[str, List[str]]) -> str:
    """
    Prompt the user interactively and return the raw string response.

    Parameters
    ----------
    prompt : str | list[str]
        A single question or a list of questions to display to the user.
        If a list is provided, each element is printed on its own line.

    Returns
    -------
    str
        The exact text entered by the user (empty string if the user just presses Enter).
    """
    if isinstance(prompt, list):
        for line in prompt:
            print(line)
        question = "> "
    else:
        question = f"{prompt} "

    try:
        return input(question).rstrip("\n")
    except (KeyboardInterrupt, EOFError):
        # Gracefully return empty string on Ctrl-C / Ctrl-D
        print()
        return ""
