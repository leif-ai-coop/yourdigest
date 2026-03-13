import logging
import time
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.llm import LlmTask

logger = logging.getLogger(__name__)


class LlmProvider:
    def __init__(self):
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        self.default_model = settings.openrouter_model

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        response_format: dict | None = None,
    ) -> dict:
        """Send a chat completion request. Returns the response dict."""
        model = model or self.default_model
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        start = time.time()
        response = await self.client.chat.completions.create(**kwargs)
        duration_ms = int((time.time() - start) * 1000)

        choice = response.choices[0]
        usage = response.usage

        return {
            "content": choice.message.content,
            "model": model,
            "prompt_tokens": usage.prompt_tokens if usage else 0,
            "completion_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
            "duration_ms": duration_ms,
            "finish_reason": choice.finish_reason,
        }

    async def chat_and_log(
        self,
        db: AsyncSession,
        task_type: str,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2000,
        response_format: dict | None = None,
    ) -> dict:
        """Chat and log the task to the database."""
        task = LlmTask(
            task_type=task_type,
            model=model or self.default_model,
            status="running",
        )
        db.add(task)
        await db.flush()

        try:
            result = await self.chat(messages, model, temperature, max_tokens, response_format)
            task.status = "completed"
            task.prompt_tokens = result["prompt_tokens"]
            task.completion_tokens = result["completion_tokens"]
            task.total_tokens = result["total_tokens"]
            task.duration_ms = result["duration_ms"]
            task.input_preview = str(messages[-1].get("content", ""))[:500]
            task.output_preview = (result.get("content") or "")[:500]
            await db.flush()
            return result
        except Exception as e:
            task.status = "failed"
            task.error = str(e)[:1000]
            await db.flush()
            raise


_provider = None


def get_llm_provider() -> LlmProvider:
    global _provider
    if _provider is None:
        _provider = LlmProvider()
    return _provider
