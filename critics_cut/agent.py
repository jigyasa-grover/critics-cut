"""
Critic's Cut v2 — Multi-Agent Movie Intelligence System
========================================================

Architecture:

    CriticsCutDirector (root, global_instruction, safety callbacks)
    ├── CriticAgent          — MCP fetch + output_key
    ├── RecommenderAgent     — MCP fetch + state-aware instruction
    └── WatchlistAgent       — manage_watchlist (ToolContext) + before_tool_callback

- Multi-agent orchestration (sub_agents, LLM-driven delegation)
- MCP integration (McpToolset → mcp-server-fetch)
- Safety guardrails (before_model_callback, after_model_callback)
- Session state persistence (ToolContext.state)
- Cross-agent data sharing (output_key)
- State-aware dynamic instructions ({key} templating)
- Global instruction (shared context for all agents)
- Tool-level callback (before_tool_callback)
- LLM generation control (generate_content_config per agent)
- Pydantic-validated custom tools
- Gemini 3 Flash
"""

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from . import tools
from .guardrails import input_guardrail, output_guardrail, watchlist_tool_guardrail

MODEL = "gemini-3-flash-preview"

# MCP Toolset: mcp-server-fetch for real web content

fetch_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uvx",
            args=["mcp-server-fetch", "--ignore-robots-txt"],
        ),
    ),
)

# Sub-Agent 1: The Critic
# output_key saves review to session state for cross-agent data sharing.

critic_agent = Agent(
    name="CriticAgent",
    model=MODEL,
    description=(
        "Provides detailed, sourced reviews of movies and TV shows by "
        "fetching real review content from the web. Delegates here for "
        "reviews, ratings, or critical analysis of a specific title."
    ),
    instruction="""You are a knowledgeable, honest film critic.

Workflow:
1. Use the fetch tool to retrieve content from well-known review sites.
   Construct URLs like:
   - https://www.rottentomatoes.com/m/MOVIE_NAME_WITH_UNDERSCORES
   - https://en.wikipedia.org/wiki/MOVIE_NAME_(film)
2. Extract ratings, cast, director, and critical consensus.
3. Synthesize into a structured review.

Output format (Markdown):

    ## [Title] ([Year])

    **Director:** Name | **Genre:** Genres

    ### Ratings
    | Source            | Score    |
    |-------------------|----------|
    | Rotten Tomatoes   | XX%      |
    | IMDb              | X.X/10   |

    ### Verdict
    - **Acting:** [Insight]
    - **Story:** [Insight]
    - **Overall:** [1-2 sentence summary]

    ### Sources
    - [Source Name](URL)

Rules:
- Use real data fetched from the web. Do not fabricate ratings.
- Keep reviews to 200-300 words.
- If the query is not about movies/TV, say so politely.
""",
    tools=[fetch_toolset],
    output_key="last_review",
    generate_content_config=types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=1024,
    ),
)

# Sub-Agent 2: The Recommender
# Uses {user_watchlist} template — ADK auto-injects session state into the
# instruction at runtime, so this agent is aware of what the user has saved.

recommender_agent = Agent(
    name="RecommenderAgent",
    model=MODEL,
    description=(
        "Recommends movies based on user preferences, compares titles, and "
        "suggests what to watch next. Delegates here for recommendations, "
        "'what should I watch', or comparisons between movies."
    ),
    instruction="""You help users discover movies and decide what to watch.

The user's current watchlist: {user_watchlist}
Do not recommend movies already on their watchlist.

Workflow:
1. Use the fetch tool to look up movie info from trusted sites.
   Good URLs:
   - https://en.wikipedia.org/wiki/MOVIE_NAME_(film)
   - https://www.rottentomatoes.com/m/MOVIE_NAME
2. Personalize suggestions based on what the user says they like.

Output format (Markdown):

    ## If You Liked [Title], Try These

    | # | Movie | Why |
    |---|-------|-----|
    | 1 | [Title] | [Brief reason] |
    | 2 | [Title] | [Brief reason] |
    | 3 | [Title] | [Brief reason] |

    **Top pick:** [Title] — [Why]

Rules:
- Explain why each recommendation fits the user's taste.
- Use real data from fetched content. Do not make up scores.
- Keep responses concise.
""",
    tools=[fetch_toolset],
    generate_content_config=types.GenerateContentConfig(
        temperature=0.5,
        max_output_tokens=1024,
    ),
)

# Sub-Agent 3: The Watchlist Curator
# before_tool_callback validates tool input before execution.

watchlist_agent = Agent(
    name="WatchlistAgent",
    model=MODEL,
    description=(
        "Manages the user's movie watchlist. Delegates here when the user "
        "wants to add, remove, or view their watchlist."
    ),
    instruction="""You manage the user's personal movie watchlist.

Use the manage_watchlist tool with action='add', 'remove', or 'list'.
After any change, show the updated watchlist as a numbered Markdown list.
Keep responses short and helpful.
""",
    tools=[tools.manage_watchlist],
    before_tool_callback=watchlist_tool_guardrail,
    generate_content_config=types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=512,
    ),
)

# Root Agent: Orchestrator + Safety Guardrails
# global_instruction is shared context appended to ALL agents in the hierarchy.

root_agent = Agent(
    name="CriticsCutDirector",
    model=MODEL,
    description="Orchestrator for the Critic's Cut multi-agent movie system.",
    global_instruction=(
        "You are part of Critic's Cut, a movie intelligence system. "
        "Always respond in well-formatted Markdown. Be concise and helpful. "
        "Never discuss topics unrelated to movies or TV shows."
    ),
    instruction="""You are the director of Critic's Cut, a multi-agent movie
intelligence system. You do not answer movie questions yourself — you delegate
to your team.

Your team:
- CriticAgent: Reviews, ratings, critical analysis of specific titles.
  Fetches real review content from the web via MCP.
- RecommenderAgent: Movie recommendations, "what to watch next", comparisons.
  Fetches real data from movie sites via MCP.
- WatchlistAgent: Managing the user's watchlist (add/remove/list).

Delegation rules:
- "review X", "is X good?", "how was X?" -> CriticAgent
- "recommend", "suggest", "what should I watch", "compare X vs Y" -> RecommenderAgent
- "add to watchlist", "my list", "save for later" -> WatchlistAgent

On the first message, briefly introduce yourself (one short paragraph) and
list what you can help with. If a query spans multiple agents, delegate to
each in sequence. If the query is unrelated to movies/TV, politely redirect.
""",
    sub_agents=[critic_agent, recommender_agent, watchlist_agent],
    before_model_callback=input_guardrail,
    after_model_callback=output_guardrail,
)
