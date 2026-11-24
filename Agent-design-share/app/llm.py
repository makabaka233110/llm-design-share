"""One LLM entry point: text or validated JSON, bounded retries, usage logging.

Supports any OpenAI-compatible service (DeepSeek, Qwen, MiniMax, OpenAI ...)
and Anthropic via LLM_PROVIDER=claude.
"""

import json
import os
import re
import time

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app import db

PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
MODEL = os.getenv("LLM_MODEL", "")
# USD per 1M tokens (input / output); 0 = unknown. Used for the cost column of the usage log.
PRICE_IN, PRICE_OUT = float(os.getenv("LLM_PRICE_IN") or 0), float(os.getenv("LLM_PRICE_OUT") or 0)


def cost(tokens_in: int | None, tokens_out: int | None) -> float:
    return round(((tokens_in or 0) * PRICE_IN + (tokens_out or 0) * PRICE_OUT) / 1e6, 4)
MAX_RETRIES = 1  # one corrective retry after invalid structured output

_client = None


class LLMError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        key = os.getenv("LLM_API_KEY")
        if not key or not MODEL:
            raise HTTPException(503, "LLM 未配置：在 .env 中设置 LLM_API_KEY / LLM_MODEL")
        if PROVIDER in ("claude", "anthropic"):
            from anthropic import Anthropic
            _client = Anthropic(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
        else:
            from openai import OpenAI
            _client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL") or None)
    return _client


def complete(system: str, messages: list[dict], max_tokens: int) -> tuple[str, int, int]:
    """Raw call. Returns (text, tokens_in, tokens_out). Tests monkeypatch this."""
    client = _get_client()
    if PROVIDER in ("claude", "anthropic"):
        r = client.messages.create(model=MODEL, system=system, messages=messages, max_tokens=max_tokens)
        return r.content[0].text, r.usage.input_tokens, r.usage.output_tokens
    r = client.chat.completions.create(
        model=MODEL, max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, *messages])
    u = r.usage
    return r.choices[0].message.content or "", getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0)


def chat(task: str, system: str, prompt: str, user: str = "", max_tokens: int = 800) -> str:
    return _call(task, system, [{"role": "user", "content": prompt}], user, max_tokens)[0]


def _call(task, system, messages, user, max_tokens) -> tuple[str, int]:
    """Returns (text, llm_log row id)."""
    t0 = time.perf_counter()
    try:
        text, tin, tout = complete(system, messages, max_tokens)
    except HTTPException:
        raise
    except Exception as e:
        db.insert("llm_log", user_id=user, task=task, model=MODEL, ms=int((time.perf_counter() - t0) * 1000),
                  ok=0, error=str(e)[:300])
        raise LLMError(f"LLM 调用失败: {e}") from e
    log_id = db.insert("llm_log", user_id=user, task=task, model=MODEL, ms=int((time.perf_counter() - t0) * 1000),
                       tokens_in=tin, tokens_out=tout, ok=1)
    return re.sub(r"<think>[\s\S]*?</think>", "", text).strip(), log_id


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for open_, close in (("{", "}"), ("[", "]")):
        s, e = text.find(open_), text.rfind(close)
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object in output")


def chat_json(task: str, system: str, prompt: str, schema: type[BaseModel], user: str = "",
              max_tokens: int = 1200) -> BaseModel:
    """Call the model and validate against `schema`; one corrective retry, then LLMError."""
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(MAX_RETRIES + 1):
        text, log_id = _call(task, system, messages, user, max_tokens)
        try:
            return schema.model_validate(_extract_json(text))
        except (ValueError, ValidationError) as e:
            err = str(e)[:500]
            db.update("llm_log", log_id, ok=0, error=f"invalid output: {err[:200]}")
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"输出不符合要求：{err}\n只返回符合格式的 JSON。"}]
    raise LLMError(f"{task}: 结构化输出无效（{err}）")
