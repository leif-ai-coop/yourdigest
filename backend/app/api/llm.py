import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.llm import LlmProviderConfig, LlmTask, LlmPromptVersion
from app.schemas.llm import (
    LlmProviderConfigCreate, LlmProviderConfigOut,
    LlmTaskOut, LlmPromptVersionCreate, LlmPromptVersionOut,
    DraftReplyRequest, DraftReplyResponse,
)
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError
from app.services.connector_service import encrypt_value

router = APIRouter()


@router.get("/models")
async def list_models():
    """List available models from OpenRouter."""
    from app.llm.provider import get_llm_provider
    provider = get_llm_provider()
    try:
        models = await provider.client.models.list()
        return [
            {"id": m.id, "name": getattr(m, "name", m.id)}
            for m in models.data
        ]
    except Exception as e:
        return []


@router.get("/active-model")
async def get_active_model():
    """Get the currently active model."""
    from app.llm.provider import get_llm_provider
    provider = get_llm_provider()
    return {"model": provider.default_model}


@router.put("/active-model")
async def set_active_model(model: str, db: AsyncSession = Depends(get_db)):
    """Set the active model. Persists to DB and updates runtime."""
    from app.llm.provider import get_llm_provider
    from app.models.audit import AppSetting

    provider = get_llm_provider()
    provider.default_model = model

    # Persist to app_settings
    result = await db.execute(select(AppSetting).where(AppSetting.key == "llm_active_model"))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = model
    else:
        db.add(AppSetting(key="llm_active_model", value=model))

    return {"model": provider.default_model}


@router.get("/providers", response_model=list[LlmProviderConfigOut])
async def list_providers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(LlmProviderConfig))
    return result.scalars().all()


@router.post("/providers", response_model=LlmProviderConfigOut, status_code=201)
async def create_provider(data: LlmProviderConfigCreate, db: AsyncSession = Depends(get_db)):
    provider = LlmProviderConfig(
        name=data.name,
        provider_type=data.provider_type,
        base_url=data.base_url,
        api_key_encrypted=encrypt_value(data.api_key) if data.api_key else None,
        default_model=data.default_model,
        enabled=data.enabled,
        extra_config=data.extra_config,
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


@router.get("/tasks", response_model=list[LlmTaskOut])
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LlmTask)
        .order_by(desc(LlmTask.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return result.scalars().all()


@router.get("/prompts", response_model=list[LlmPromptVersionOut])
async def list_prompts(task_type: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(LlmPromptVersion).order_by(LlmPromptVersion.task_type, desc(LlmPromptVersion.version))
    if task_type:
        query = query.where(LlmPromptVersion.task_type == task_type)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/prompts", response_model=LlmPromptVersionOut, status_code=201)
async def create_prompt(data: LlmPromptVersionCreate, db: AsyncSession = Depends(get_db)):
    # Get next version number
    result = await db.execute(
        select(LlmPromptVersion.version)
        .where(LlmPromptVersion.task_type == data.task_type)
        .order_by(desc(LlmPromptVersion.version))
        .limit(1)
    )
    last_version = result.scalar_one_or_none() or 0
    prompt = LlmPromptVersion(
        task_type=data.task_type,
        version=last_version + 1,
        system_prompt=data.system_prompt,
        user_prompt_template=data.user_prompt_template,
        description=data.description,
    )
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.post("/prompts/{prompt_id}/activate", response_model=MessageResponse)
async def activate_prompt(prompt_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(LlmPromptVersion, prompt_id)
    if not prompt:
        raise NotFoundError("Prompt not found")
    # Deactivate others of same type
    result = await db.execute(
        select(LlmPromptVersion).where(
            LlmPromptVersion.task_type == prompt.task_type,
            LlmPromptVersion.is_active == True,
        )
    )
    for p in result.scalars():
        p.is_active = False
    prompt.is_active = True
    return MessageResponse(message=f"Prompt v{prompt.version} activated for {prompt.task_type}")


@router.post("/draft-reply", response_model=DraftReplyResponse)
async def draft_reply(data: DraftReplyRequest, db: AsyncSession = Depends(get_db)):
    from app.llm.tasks.draft import generate_draft_reply
    from app.models.mail import MailMessage, MailAccount
    from app.services.connector_service import decrypt_value
    from app.services.imap_client import save_draft

    result = await generate_draft_reply(db, data.message_id, data.instructions, data.tone)

    # Save draft to IMAP Drafts folder
    try:
        message = await db.get(MailMessage, data.message_id)
        if message:
            account = await db.get(MailAccount, message.account_id)
            if account and account.imap_host:
                password = decrypt_value(account.password_encrypted)
                reply_subject = message.subject or ""
                if not reply_subject.lower().startswith("re:"):
                    reply_subject = f"Re: {reply_subject}"

                save_draft(
                    host=account.imap_host,
                    port=account.imap_port,
                    username=account.username,
                    password=password,
                    use_ssl=account.imap_use_ssl if account.imap_use_ssl is not None else True,
                    from_addr=account.email,
                    to_addr=message.from_address,
                    subject=reply_subject,
                    body_text=result["draft"],
                    in_reply_to=message.message_id,
                    references=message.message_id,
                )
                result["saved_to_drafts"] = True
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to save draft to IMAP: {e}")
        result["saved_to_drafts"] = False

    return result
