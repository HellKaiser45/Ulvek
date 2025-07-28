from src.tools.codebase import output_directory_tree
from src.config import tokenizer
import asyncio


if __name__ == "__main__":
    result = asyncio.run(output_directory_tree())  # Returns List[str]

    # Join the list into a single string
    full_text = "\n".join(result)

    # Now tokenize the string
    token_count = len(tokenizer.encode(full_text))
    print("tokens used:", token_count)
    print(result)
