"""HTTP layer. Every request carries the learner id in `X-User` (local, no auth)."""

import asyncio
import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app import llm


def current_user(x_user: str = Header("default")) -> str:
    if not re.fullmatch(r"[\w\-.@]{1,64}", x_user):
        raise HTTPException(400, "invalid X-User")
    return x_user


User = Annotated[str, Depends(current_user)]


async def call(fn, *args, **kw):
    """Run a blocking agent/LLM step off the event loop; LLM failures become explicit 502s."""
    try:
        return await asyncio.to_thread(fn, *args, **kw)
    except llm.LLMError as e:
        raise HTTPException(502, str(e))
