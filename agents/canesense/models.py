"""A Gemini model that falls back to the next Flash model when one is rate-limited or under high demand.

Flash models answer 429 (quota) or 503 (high demand) now and then. A mill manager asking one question should
not see an error for that, so the agents use a chain: try the first model, on 429/503/500/504 move to the next.
The chain comes from GEMINI_MODELS (comma separated) or defaults to the single GEMINI_MODEL.
"""
import asyncio
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
FIRST_RESPONSE_SECONDS = int(os.environ.get('FIRST_RESPONSE_SECONDS', '90'))   # a long answer thinks for 20-50 s before its first byte; a stalled model is cut here
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
        # no retries inside the SDK: a rate-limited model hands over to the next one at once
        return Gemini(model=name, retry_options=types.HttpRetryOptions(attempts=1, http_status_codes=sorted(RETRY_CODES)))

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        last = None
        for i, name in enumerate(self.chain):
            agen = self._gemini(name).generate_content_async(llm_request, stream)
            try:
                # a model that has not started answering within FIRST_RESPONSE_SECONDS is left for the next one
                first = await asyncio.wait_for(agen.__anext__(), timeout=FIRST_RESPONSE_SECONDS)
            except StopAsyncIteration:
                return
            except Exception as e:  # noqa: BLE001  (timeouts, connection errors and API errors all fall back)
                last = e
                try:
                    await agen.aclose()
                except Exception:  # noqa: BLE001
                    pass
                code = getattr(e, 'code', None)
                slow = isinstance(e, asyncio.TimeoutError)
                if (slow or code in RETRY_CODES or not isinstance(e, errors.APIError)) and i + 1 < len(self.chain):
                    log.warning('model %s %s; falling back to %s', name, 'gave no answer in %ds' % FIRST_RESPONSE_SECONDS if slow else f'returned {code or type(e).__name__}', self.chain[i + 1])
                    continue
                raise
            yield first
            async for resp in agen:
                yield resp
            return
        if last:
            raise last
