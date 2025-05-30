"""
Critic's Cut v2 — Custom Tools
================================
Typed Python functions auto-converted to ADK tools.
Uses Pydantic for validation and ToolContext for session state persistence.
"""

from google.adk.tools import ToolContext

from .models import WatchlistAction, WatchlistResult

WATCHLIST_STATE_KEY = "user_watchlist"


def manage_watchlist(action: str, title: str = "", tool_context: ToolContext = None) -> dict:
    """Add, remove, or list movies in the user's personal watchlist.

    Args:
        action: The operation to perform — 'add', 'remove', or 'list'.
        title: The movie title (required for add/remove, ignored for list).

    Returns:
        A dict with status, current watchlist, and count.
    """
    watchlist: list[str] = list(tool_context.state.get(WATCHLIST_STATE_KEY, [])) if tool_context else []

    try:
        op = WatchlistAction(action.strip().lower())
    except ValueError:
        return WatchlistResult(
            status="error",
            message=f"Unknown action '{action}'. Use 'add', 'remove', or 'list'.",
        ).model_dump()

    if op == WatchlistAction.LIST:
        return WatchlistResult(
            status="listed",
            watchlist=watchlist,
            count=len(watchlist),
            message=f"{len(watchlist)} movie(s) on your watchlist." if watchlist else "Your watchlist is empty.",
        ).model_dump()

    clean = title.strip()
    if not clean:
        return WatchlistResult(
            status="error",
            message="A movie title is required for add/remove.",
        ).model_dump()

    if op == WatchlistAction.ADD:
        if clean not in watchlist:
            watchlist.append(clean)
            if tool_context:
                tool_context.state[WATCHLIST_STATE_KEY] = watchlist
            return WatchlistResult(
                status="added", title=clean,
                watchlist=watchlist, count=len(watchlist),
                message=f"'{clean}' added to your watchlist.",
            ).model_dump()
        return WatchlistResult(
            status="already_exists", title=clean,
            watchlist=watchlist, count=len(watchlist),
            message=f"'{clean}' is already on your watchlist.",
        ).model_dump()

    if op == WatchlistAction.REMOVE:
        if clean in watchlist:
            watchlist.remove(clean)
            if tool_context:
                tool_context.state[WATCHLIST_STATE_KEY] = watchlist
            return WatchlistResult(
                status="removed", title=clean,
                watchlist=watchlist, count=len(watchlist),
                message=f"'{clean}' removed from your watchlist.",
            ).model_dump()
        return WatchlistResult(
            status="not_found", title=clean,
            watchlist=watchlist, count=len(watchlist),
            message=f"'{clean}' was not on your watchlist.",
        ).model_dump()
