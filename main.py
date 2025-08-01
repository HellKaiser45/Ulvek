from src.tools.prompt_eval import is_complex, needs_context, predictor
import asyncio
from src.agents.agent import orchestrator_agent
from src.tools.codebase import get_non_ignored_files, process_file
from src.tools.search_files import search_files


async def main():
    # raw = "Build a CLI tool in python main to chose a coding agent among those available and start a conversation with it"
    # non_ignored = await get_non_ignored_files()
    # files = await process_file(non_ignored)
    # promt = f"""
    #         File analysis:
    #         {[f.model_dump() for f in files]}
    #         ---
    #
    #         Raw prompt:
    #         {raw}
    #     """
    # print("Complexe ?        ", is_complex(predictor, promt))
    # print("Besoin de contexte ?", needs_context(predictor, promt))
    #
    # # Synchronous
    # plan = await orchestrator_agent.run(promt)
    # print("📋 Plan:")
    # print(plan)

    query = "memory.search(**search_params)"
    paths = await get_non_ignored_files()
    # print(paths)
    matches = await search_files(query, paths)


if __name__ == "__main__":
    asyncio.run(main())
