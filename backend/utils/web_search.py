from typing import List, Dict


def web_search(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """
    Perform a DuckDuckGo text search and return a list of result dicts.

    Each result dict has:
        title   – page title
        url     – source URL
        snippet – short text excerpt

    Falls back to an empty list if the search library is unavailable or
    the network request fails, so it never hard-crashes the chat endpoint.
    """
    try:
        from ddgs import DDGS  # lazy import

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return results
    except Exception as exc:
        print(f"[web_search] search failed: {exc}")
        return []


def format_web_results(results: List[Dict[str, str]]) -> str:
    """
    Convert a list of web-search result dicts into a readable block
    that can be appended to the LLM system prompt.
    """
    if not results:
        return ""
    lines = ["Live web search results:"]
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['title']}")
        lines.append(f"Source: {r['url']}")
        lines.append(r["snippet"])
    return "\n".join(lines)
