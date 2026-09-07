# domain/models.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict

# ===== 核心領域實體 =====


@dataclass(frozen=True)
class CardState:
    """FSRS 排程所需的卡片狀態快照。"""

    id: int
    state: int  # 0=New, 1=Learning, 2=Review, 3=Relearning
    step: int
    stability: float | None
    difficulty: float | None
    last_review: datetime | None
    due: datetime | None
    reps: int
    lapses: int


@dataclass(frozen=True)
class ScheduledReview:
    """排程結果。"""

    next_review: datetime
    state: int
    step: int
    stability: float
    difficulty: float
    last_review: datetime


@dataclass(frozen=True)
class CardRow:
    """卡片列表/詳情的資料列。"""

    id: int
    front: str
    back: str
    card_type: Literal["recognize", "spell"]
    next_review: str  # ISO string
    state: int
    step: int
    stability: float | None
    difficulty: float | None
    last_review: str | None
    reps: int
    lapses: int
    deck_names: list[str]
    deck_ids: list[int]


@dataclass(frozen=True)
class DeckRow:
    id: int
    name: str
    new_count: int = 0
    due_count: int = 0


@dataclass(frozen=True)
class FolderWithDecks:
    id: int
    name: str
    decks: list[DeckRow]


# ===== Scope 類型 =====


class CardScope(TypedDict, total=False):
    deck_id: int
    folder_id: int
    exam_id: int


class ExamScope(TypedDict, total=False):
    deck_id: int
    folder_id: int
    exam_id: int


# ===== 回傳資料結構 =====


@dataclass(frozen=True)
class DueCards:
    new_cards: list[CardRow]
    due_cards: list[CardRow]
    next_due_at: str | None = None


@dataclass(frozen=True)
class SchedulePlan:
    card_id: int
    next_review: datetime


@dataclass(frozen=True)
class Exam:
    id: int
    name: str
    date: datetime
    processed: bool
    decks: list[DeckRow]
    folders: list[FolderWithDecks]
    total_cards: int
    learned_cards: int
    progress_percent: int
    days_remaining: int
    seconds_remaining: int
    countdown_str: str
    is_expired: bool
