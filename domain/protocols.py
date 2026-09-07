# domain/protocols.py
from __future__ import annotations
from typing import Protocol, Callable, TypeVar, Any, List, Tuple
from datetime import datetime
from domain.models import (
    CardState,
    ScheduledReview,
    CardRow,
    CardScope,
    DueCards,
    SchedulePlan,
    FolderWithDecks,
    DeckRow,
    ExamScope,
)

T = TypeVar("T")


class DatabaseAdapter(Protocol):
    """持久化縫合線：所有 SQL 執行通過此介面。"""

    def execute(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]: ...
    def execute_many(self, sql: str, params_list: list[tuple]) -> None: ...
    def transaction(
        self, fn: Callable[[Any], T]
    ) -> T: ...  # fn 接收 sqlite3.Connection
    def last_row_id(self) -> int: ...


class TimeProvider(Protocol):
    """時間存取抽象：測試可控制時間流逝。"""

    def now_utc(self) -> datetime: ...
    def day_cutoff_utc(
        self, tz_offset_hours: int = 8, rollover_hour: int = 4
    ) -> datetime: ...
    def parse_iso(self, text: str) -> datetime | None: ...
    def format_iso(self, dt: datetime | str | None) -> str: ...


class Notifier(Protocol):
    """通知發送抽象：領域模組回傳事件，app.py dispatch。"""

    def notify(self, event: NotificationEvent) -> None: ...


class CardRepo(Protocol):
    def get_by_id(self, card_id: int) -> CardRow | None: ...
    def list(
        self, scope: CardScope, search: str = "", page: int = 1, limit: int = 50
    ) -> Tuple[List[CardRow], int]: ...
    def add(
        self, front: str, back: str, card_type: str, deck_ids: List[int]
    ) -> Tuple[int, bool]: ...
    def update(
        self, card_id: int, front: str, back: str, card_type: str, deck_ids: List[int]
    ) -> None: ...
    def delete(self, card_id: int) -> None: ...
    def import_csv(
        self, csv_text: str, deck_ids: List[int], card_type: str
    ) -> Tuple[int, int]: ...
    def get_card_state(self, card_id: int) -> CardState | None: ...
    def save_review(
        self, card_id: int, review: ScheduledReview, reps: int, lapses: int
    ) -> None: ...
    def save_revlog(
        self,
        card_id: int,
        review_time: datetime,
        rating: int,
        state: int,
        duration: int,
    ) -> None: ...
    def save_review_with_log(
        self,
        card_id: int,
        review: ScheduledReview,
        reps: int,
        lapses: int,
        review_time: datetime,
        rating: int,
        previous_state: int,
        duration: int = 0,
        request_id: str | None = None,
    ) -> bool: ...


class FolderDeckRepo(Protocol):
    def list_folders_with_decks(
        self,
    ) -> Tuple[List[FolderWithDecks], List[DeckRow]]: ...
    def create_folder(self, name: str) -> int: ...
    def delete_folder(self, folder_id: int) -> None: ...
    def create_deck(self, name: str, folder_ids: List[int]) -> int: ...
    def update_deck(self, deck_id: int, name: str, folder_ids: List[int]) -> None: ...
    def delete_deck(self, deck_id: int) -> None: ...
    def get_deck_folders(self, deck_id: int) -> List[int]: ...
    def list_all_decks(self) -> List[DeckRow]: ...
    def list_all_folders(self) -> List[FolderWithDecks]: ...


class SettingsRepo(Protocol):
    def get(self, key: str, default: str | None = None) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...


class FsrcScheduler(Protocol):
    """FSRS 排程核心：純演算法，無 DB 相依。"""

    def review(
        self,
        card: CardState,
        rating: int,
        now: datetime,
        retention: float,
        exam_cutoff: datetime | None = None,
    ) -> ScheduledReview: ...
    def get_parameters(self) -> tuple[float, ...] | None: ...
    def set_parameters(self, weights: tuple[float, ...]) -> None: ...


class ExamScheduler(Protocol):
    """考試排程：分發、到期查詢、過期處理。"""

    def distribute(
        self, exam_id: int, card_ids: List[int], now: datetime
    ) -> List[SchedulePlan]: ...
    def get_due_cards(
        self, scope: ExamScope, now: datetime, daily_new_limit: int
    ) -> DueCards: ...
    def process_expired(self, now: datetime) -> List[SchedulePlan]: ...


class NotificationEvent(Protocol):
    """所有通知事件的標記介面。"""

    pass
