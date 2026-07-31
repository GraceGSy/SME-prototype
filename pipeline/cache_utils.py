"""Shared helper for Anthropic prompt caching across the extraction scripts.

Each extraction script (extract_graph.py, extract_sections.py,
extract_fine_grained.py) calls the same model repeatedly with an identical
system prompt + tool schema and only the user message changing. Marking the
system prompt as an ephemeral cache breakpoint caches everything before it in
the request too (tool definitions), so repeated calls within a script's ~5
minute run only pay full price on the first call.
"""
from __future__ import annotations


def cached_system(system_prompt: str) -> list[dict]:
    """Wrap a static system prompt as a cache breakpoint. Anthropic caches
    everything up to and including this block (tools + system), so later
    calls with the same prefix are read from cache instead of reprocessed."""
    return [{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}]


def log_cache_usage(label: str, response) -> None:
    """Print cache hit/miss info for one call, if the response reports any --
    useful for confirming caching is actually kicking in during a batch run."""
    u = response.usage
    created = getattr(u, "cache_creation_input_tokens", None) or 0
    read = getattr(u, "cache_read_input_tokens", None) or 0
    if created or read:
        status = "wrote cache" if created else "read from cache"
        print(f"    [{label}] {status}: created={created} read={read} input={u.input_tokens} output={u.output_tokens}")
