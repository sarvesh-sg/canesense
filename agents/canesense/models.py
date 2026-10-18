"""A Gemini model that falls back to the next Flash model when one is rate-limited or under high demand.

Flash models answer 429 (quota) or 503 (high demand) now and then. A mill manager asking one question should
not see an error for that, so the agents use a chain: try the first model, on 429/503/500/504 move to the next.
The chain comes from GEMINI_MODELS (comma separated) or defaults to the single GEMINI_MODEL.
"""
import logging
import os
from typing import AsyncGenerator

from google.adk.models import Gemini
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import errors, types

log = logging.getLogger(__name__)
RETRY_CODES = {429, 500, 503, 504}
DEFAULT_CHAIN = 'gemini-3.5-flash,gemini-3-flash-preview,gemini-2.5-flash'


def model_chain() -> list[str]:
    raw = os.environ.get('GEMINI_MODELS') or os.environ.get('GEMINI_MODEL') or DEFAULT_CHAIN
    return [m.strip() for m in raw.split(',') if m.strip()]


class FallbackGemini(BaseLlm):
    """Tries each model in `chain` in turn; the first that answers wins."""
    chain: list[str]

    def __init__(self, chain: list[str] | None = None):
        chain = chain or model_chain()
        super().__init__(model=chain[0], chain=chain)

    def _gemini(self, name: str) -> Gemini:
        # one quick retry per model for a passing blip; the chain handles the rest
        return Gemini(model=name, retry_options=types.HttpRetryOptions(attempts=2, initial_delay=1, http_status_codes=sorted(RETRY_CODES)))

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        last = None
        for i, name in enumerate(self.chain):
            try:
                async for resp in self._gemini(name).generate_content_async(llm_request, stream):
                    yield resp
                return
            except errors.APIError as e:
                last = e
                if getattr(e, 'code', None) in RETRY_CODES and i + 1 < len(self.chain):
                    log.warning('model %s returned %s; falling back to %s', name, e.code, self.chain[i + 1])
                    continue
                raise
        if last:
            raise last
