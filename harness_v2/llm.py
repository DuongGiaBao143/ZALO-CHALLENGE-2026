"""Client mỏng cho API chat kiểu OpenAI (vLLM hoặc Ollama /v1), chỉ dùng thư viện chuẩn."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


def chat(base_url: str, model: str, messages: list[dict], tools: list[dict] | None = None, *, max_tokens: int = 4096,
         temperature: float = 0.0, timeout: float = 300, extra_body: dict | None = None, seed: int | None = 0) -> dict:
    """Một lượt gọi model. Trả {content, reasoning, tool_calls:[{id,name,arguments(str)}], finish, usage}."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = tools
    if seed is not None:
        body["seed"] = seed
    body.update(extra_body or {})
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer local"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    choice = data["choices"][0]
    msg = choice.get("message") or {}
    calls = [{"id": c.get("id") or f"call_{i}", "name": (c.get("function") or {}).get("name", ""),
              "arguments": (c.get("function") or {}).get("arguments") or "{}"} for i, c in enumerate(msg.get("tool_calls") or [])]
    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning") or msg.get("reasoning_content") or "",
            "tool_calls": calls, "finish": choice.get("finish_reason"), "usage": data.get("usage") or {}}
