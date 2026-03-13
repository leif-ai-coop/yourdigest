import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.classification import ClassificationRule, MailClassification
from app.schemas.classification import (
    ClassificationRuleCreate, ClassificationRuleUpdate, ClassificationRuleOut,
    ClassificationOut,
)
from app.schemas.common import MessageResponse
from app.exceptions import NotFoundError

router = APIRouter()


@router.get("/rules", response_model=list[ClassificationRuleOut])
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ClassificationRule).order_by(ClassificationRule.priority.desc()))
    return result.scalars().all()


@router.post("/rules", response_model=ClassificationRuleOut, status_code=201)
async def create_rule(data: ClassificationRuleCreate, db: AsyncSession = Depends(get_db)):
    rule = ClassificationRule(**data.model_dump())
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.patch("/rules/{rule_id}", response_model=ClassificationRuleOut)
async def update_rule(rule_id: uuid.UUID, data: ClassificationRuleUpdate, db: AsyncSession = Depends(get_db)):
    rule = await db.get(ClassificationRule, rule_id)
    if not rule:
        raise NotFoundError("Rule not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)
    await db.flush()
    await db.refresh(rule)
    return rule


@router.delete("/rules/{rule_id}", response_model=MessageResponse)
async def delete_rule(rule_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(ClassificationRule, rule_id)
    if not rule:
        raise NotFoundError("Rule not found")
    await db.delete(rule)
    return MessageResponse(message="Rule deleted")


@router.get("/messages/{message_id}", response_model=list[ClassificationOut])
async def get_message_classifications(message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MailClassification)
        .where(MailClassification.message_id == message_id)
        .order_by(desc(MailClassification.created_at))
    )
    return result.scalars().all()


@router.post("/classify/{message_id}", response_model=ClassificationOut)
async def classify_message(message_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.services.classification_service import classify_message as do_classify
    classification = await do_classify(db, message_id)
    return classification
