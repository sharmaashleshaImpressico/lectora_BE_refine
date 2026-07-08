"""Generic CRUD repository shared by all DB-backed services."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Reusable CRUD helper for a single SQLAlchemy model.

    Concrete services should subclass or instantiate this with their own
    model instead of writing raw session queries, so DB access stays
    consistent and easy to test.
    """

    def __init__(self, model: type[ModelType], db: Session) -> None:
        self.model = model
        self.db = db

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.flush()
        self.db.refresh(obj)
        return obj

    def get_by_id(self, record_id: int) -> ModelType | None:
        return self.db.get(self.model, record_id)

    def get_by(self, **filters) -> ModelType | None:
        query = self.db.query(self.model).filter_by(**filters)
        return query.first()

    def list(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        return self.db.query(self.model).offset(skip).limit(limit).all()

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.flush()
