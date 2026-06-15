"""Web search and fetch tools."""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from urllib.parse import quote_plus


def web_search(query: str, limit: int = 5) -> dict:
    """Search the web using DuckDuckGo HTML (no API key needed).

    Returns {"ok": True, "results": [{title, url, description}]}
    """
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Next-Agent/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "error": f"Search failed: {e}"}

    # Parse results from DuckDuckGo HTML
    results = []
    # Extract result blocks: <a class="result__a" href="...">title</a>
    link_pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        re.DOTALL,
    )
    snippet_pattern = re.compile(
        r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    links = link_pattern.findall(html)
    snippets = snippet_pattern.findall(html)

    for i, (href, title) in enumerate(links[:limit]):
        title_clean = re.sub(r"<[^>]*>", "", title).strip()
        snippet_clean = ""
        if i < len(snippets):
            snippet_clean = re.sub(r"<[^>]*>", "", snippets[i]).strip()

        results.append({
            "title": title_clean or query,
            "url": href,
            "description": snippet_clean[:300],
        })

    if not results:
        return {"ok": True, "output": f"No results for '{query}'"}

    output = "\n\n".join(
        f"**{r['title']}**\n{r['description']}\n{r['url']}"
        for r in results
    )
    return {"ok": True, "output": output, "results": results}


def web_fetch(url: str) -> dict:
    """Fetch content from a URL.

    Returns {"ok": True, "content": "plain text or JSON"}
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Next-Agent/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": f"Fetch failed: {e}"}

    # Auto-parse JSON
    if "json" in content_type:
        try:
            parsed = json.loads(raw)
            return {"ok": True, "content": json.dumps(parsed, indent=2, ensure_ascii=False)[:20000]}
        except json.JSONDecodeError:
            pass

    # Strip HTML tags for plain text
    if "html" in content_type:
        raw = re.sub(r"<style[^>]*>.*?</style>", "", raw, flags=re.DOTALL)
        raw = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL)
        raw = re.sub(r"<[^>]*>", " ", raw)
        raw = re.sub(r"\s+", " ", raw)
        raw = raw.strip()

    if len(raw) > 10000:
        raw = raw[:10000] + "... [truncated]"

    return {"ok": True, "content": raw}


def web_extract(urls: str) -> dict:
    """Extract content from multiple URLs (comma-separated)."""
    url_list = [u.strip() for u in urls.split(",") if u.strip()]
    if not url_list:
        return {"ok": False, "error": "No URLs provided"}
    if len(url_list) > 5:
        return {"ok": False, "error": "Max 5 URLs at a time"}

    results = []
    for url in url_list:
        result = web_fetch(url)
        results.append({"url": url, **result})

    output_lines = []
    for r in results:
        if r.get("ok"):
            content = r.get("content", r.get("output", ""))
            output_lines.append(f"## {r['url']}\n{content[:5000]}")
        else:
            output_lines.append(f"## {r['url']}\n❌ {r.get('error', '')}")

    return {"ok": True, "output": "\n\n".join(output_lines), "results": results}
