from pydantic import BaseModel, Field
from src.app.utils.chunkers import chunk_docs_on_demand, format_chunks_for_memory
from src.app.tools.memory import process_multiple_messages_with_temp_memory
from src.app.tools.search_docs import AsyncContext7Client
from src.app.utils.logger import get_logger

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Pydantic model that groups every “secondary” parameter
# ------------------------------------------------------------------
class SearchConfig(BaseModel):
    limit: int = Field(
        3,
        ge=1,
        description="Maximum number of relevant snippets to return from the memory layer.",
    )
    library_to_search: str = Field(
        ...,
        description="Library or framework name to search on Context7 (e.g. 'react', 'fastapi').",
    )
    search_in_library: str = Field(
        ...,
        description="Free-text query used to retrieve the most relevant snippets from the fetched documentation.",
    )
    threshold: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="Relevance threshold for Mem0 search; higher values return fewer but more relevant snippets.",
    )


async def gather_docs_context(params: SearchConfig) -> list[str] | str:
    """
    Search Context7 for a library and immediately fetch its documentation.

    Parameters
    ----------
    params : SearchConfig
        Configuration object for the search.

    Returns
    -------
    list[str]
        List of documentation strings for the best-matched library.
    str
        Error message if the search failed.
    """
    logger.info(f"Gathering context for {params.model_dump_json()}")

    async with AsyncContext7Client() as client:
        docs, tokens, title = await client.search_and_fetch(
            query=params.library_to_search
        )

    if docs:
        formatted_chunks = format_chunks_for_memory(chunk_docs_on_demand(docs))
        results = process_multiple_messages_with_temp_memory(
            messages_batch=formatted_chunks,
            query=params.search_in_library,
        )
        logger.info(
            f"Gathered {len(results)} results from Mem0 for the docs search for {params.library_to_search} and the query {params.search_in_library}"
        )
        for result in results:
            logger.info(f"Result: {result[:100]}")

        return results
    return "No documentation found for the specified library."


gather_docs_context_description = """💰 EXPENSIVE EXTERNAL API TOOL - Use strategically 💰
    
    Searches Context7 external documentation service and retrieves relevant docs using AI.
    This tool fetches fresh external documentation but has API costs and latency.
    Plan your usage carefully to minimize redundant calls.
    
    🎯 WHEN TO USE:
    - User mentions external libraries/frameworks not in your codebase
    - You need official documentation for third-party tools  
    - Understanding API usage, configuration, or integration patterns
    - Codebase uses libraries but lacks local documentation
    
    ⚠️ AVOID REDUNDANT USAGE:
    - Don't search for the same library multiple times in one session
    - Don't search for built-in language features (use your knowledge instead)
    - Don't search when codebase already contains sufficient examples
    
    Parameters:
    -----------
    params : SearchConfig
        
    params.library_to_search : str
        🔍 Library/framework name for Context7 search.
        
        ✅ EXCELLENT: "fastapi", "react", "sqlalchemy", "pandas", "django"
        ✅ GOOD: "numpy", "pytest", "redis", "celery", "pydantic"
        ✅ ACCEPTABLE: "tensorflow", "kubernetes", "docker"
        
        ❌ TOO GENERIC: "python", "javascript", "database", "api"
        ❌ TOO SPECIFIC: "fastapi.middleware.cors", "react-router-dom" 
        ❌ COMPANY INTERNAL: "our-custom-lib", "internal-utils"
        
        💡 STRATEGY: Use the main library name, not submodules or plugins
        💡 TIP: If uncertain, use the name you'd find on PyPI/npm
        
    params.search_in_library : str  
        🎯 Specific query within the library's documentation.
        
        ✅ EXCELLENT QUERIES:
        - "authentication and JWT token handling"
        - "database connection pooling configuration"  
        - "async/await usage patterns and examples"
        - "middleware creation and request processing"
        - "error handling and exception management"
        - "testing setup and fixture configuration"
        
        ✅ GOOD QUERIES:
        - "file upload handling"
        - "background tasks"
        - "database migrations"
        - "API rate limiting"
        
        ❌ TOO BROAD: "how to use", "getting started", "tutorial"
        ❌ TOO NARROW: "color of submit button", "exact parameter name"
        ❌ CODEBASE SPECIFIC: "how to fix our bug", "why is our X broken"
        
        💡 STRATEGY: Focus on concepts/patterns, not exact implementation details
        💡 TIP: Think "what would I search in official docs?"
        
    params.limit : int (default: 3)
        📊 Number of documentation snippets to retrieve.
        
        ✅ OPTIMAL: 3-5 for most searches
        ✅ FOCUSED: 1-2 for very specific queries
        ✅ COMPREHENSIVE: 5-7 for complex topics needing multiple examples
        
        ❌ WASTEFUL: 10+ (rarely needed, increases cost/processing)
        
        💡 STRATEGY: Start with 3, increase only if results lack sufficient detail
        
    params.threshold : float (default: 0.5)
        🎚️ Relevance filtering threshold (0.0-1.0).
        
        ✅ BALANCED: 0.5 (default - good quality/quantity balance)
        ✅ HIGH PRECISION: 0.7-0.8 (when you need very specific information)
        ✅ HIGH RECALL: 0.3-0.4 (when exploring broad topics)
        
        ❌ TOO STRICT: 0.9+ (may return no results)
        ❌ TOO LOOSE: 0.1-0.2 (may return irrelevant content)
        
        💡 STRATEGY: Use default 0.5 unless you have specific quality requirements
    
    Returns:
    --------
    list[str]: Documentation snippets, each containing:
        - Relevant documentation sections
        - Code examples and usage patterns  
        - Configuration and setup information
        
    str: Error message if library not found or API failure
        → Try alternative library names or check spelling
    
    ⚡ PERFORMANCE & COST:
    - Each call: API request + documentation fetch + AI processing
    - Cost scales with: limit × documentation_size × query_complexity
    - Typical response time: 2-5 seconds
    - Rate limits may apply for frequent usage
    
    🎯 STRATEGIC USAGE PATTERNS:
    
    📋 SINGLE COMPREHENSIVE SEARCH:
    Better than: Multiple narrow searches for same library
    Example: "authentication, middleware, and database integration" 
    vs. 3 separate calls
    
    🎯 ONE-SHOT STRATEGY:
    Plan your query carefully to get what you need in ONE call:
    - Think: "What exactly do I need to know about this library?"
    - Craft a focused query that covers your main concerns
    - Use reasonable defaults (limit=3, threshold=0.5) 
    - Accept that results may not be perfect - work with what you get
    
    🔄 SESSION PLANNING:
    - Identify ALL libraries you need docs for upfront
    - Make ONE strategic call per library
    - Cache results mentally for follow-up questions
    
    💡 EXPERT USAGE:
    ONE library = ONE call. Plan carefully:
    "I need FastAPI auth patterns AND middleware setup AND error handling"
    = 1 comprehensive call with search_in_library="authentication middleware error handling"
    NOT 3 separate calls.
    """


if __name__ == "__main__":
    import asyncio

    asyncio.run(
        gather_docs_context(
            SearchConfig(
                limit=3,
                library_to_search="pydanticai",
                search_in_library="agent definition",
                threshold=0.5,
            )
        )
    )
