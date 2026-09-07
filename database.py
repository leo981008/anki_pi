# database.py - Strangler Fig facade: delegates to new modules while preserving exact same API
from __future__ import annotations
import logging
from config import Config
from adapters.sqlite_adapter import SqliteAdapter
from domain.time_provider import SystemTimeProvider
from repos.card_repo import CardRepoImpl
from repos.folder_deck_repo import FolderDeckRepoImpl
from repos.settings_repo import SettingsRepoImpl
from schedulers.fsrc_scheduler import FsrcSchedulerImpl
from schedulers.exam_scheduler import ExamSchedulerImpl
from domain.protocols import Notifier
from notifiers.discord_notifier import DiscordNotifier
from notifiers.null_notifier import NullNotifier
from domain.models import CardScope, ExamScope

logger = logging.getLogger(__name__)

# Initialize adapter and domain modules (singletons for backward compatibility)
_adapter = SqliteAdapter(Config.DATABASE_PATH)
_time_provider = SystemTimeProvider()
_card_repo = CardRepoImpl(_adapter, _time_provider)
_folder_deck_repo = FolderDeckRepoImpl(_adapter, _time_provider)
_settings_repo = SettingsRepoImpl(_adapter)
_fsrc_scheduler = FsrcSchedulerImpl()
_exam_scheduler = ExamSchedulerImpl(
    _adapter, _card_repo, _folder_deck_repo, _settings_repo, _time_provider
)
_notifier: Notifier
if Config.DISCORD_WEBHOOK_URL:
    _notifier = DiscordNotifier(Config.DISCORD_WEBHOOK_URL)
else:
    _notifier = NullNotifier()


# Backward compatibility: expose get_db_connection for tests
def get_db_connection():
    import sqlite3

    conn = sqlite3.connect(Config.DATABASE_PATH, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


# Re-export time utilities for backward compatibility
_tp = SystemTimeProvider()
parse_db_datetime = _tp.parse_iso
format_datetime_for_db = _tp.format_iso
get_day_cutoff_utc = _tp.day_cutoff_utc


# Re-export send_discord_message for backward compatibility
def send_discord_message(content: str) -> None:
    if Config.DISCORD_WEBHOOK_URL:
        import threading
        import requests

        def run_send():
            try:
                requests.post(
                    Config.DISCORD_WEBHOOK_URL, json={"content": content}, timeout=5
                )
            except Exception as e:
                print(f"Error sending Discord Webhook: {e}")

        threading.Thread(target=run_send, daemon=True).start()


class StudyCardsResult(tuple):
    """Backwards-compatible result tuple for study cards.
    Unpacks as `new_cards, due_cards = res`, and provides `.next_due_at` attribute.
    """

    new_cards: list
    due_cards: list
    next_due_at: str | None

    def __new__(cls, new_cards, due_cards, next_due_at=None):
        instance = super().__new__(cls, (new_cards, due_cards))
        instance.new_cards = new_cards
        instance.due_cards = due_cards
        instance.next_due_at = next_due_at
        return instance


def get_all_folders():
    return _adapter.execute("SELECT * FROM folders")


def get_all_decks():
    return _adapter.execute("SELECT * FROM decks")


def get_folders_with_decks():
    folders, unassigned = _folder_deck_repo.list_folders_with_decks()
    # Convert to old dict format for backward compatibility
    folder_list = []
    for f in folders:
        f_dict = {"id": f.id, "name": f.name, "decks": []}
        for d in f.decks:
            f_dict["decks"].append(
                {
                    "id": d.id,
                    "name": d.name,
                    "new_count": d.new_count,
                    "due_count": d.due_count,
                }
            )
        folder_list.append(f_dict)
    unassigned_list = []
    for d in unassigned:
        unassigned_list.append(
            {
                "id": d.id,
                "name": d.name,
                "new_count": d.new_count,
                "due_count": d.due_count,
            }
        )
    return folder_list, unassigned_list


def create_folder(name):
    return _folder_deck_repo.create_folder(name)


def delete_folder(folder_id):
    _folder_deck_repo.delete_folder(folder_id)


def create_deck(name, folder_ids=None):
    return _folder_deck_repo.create_deck(name, folder_ids or [])


def update_deck(deck_id, name, folder_ids=None):
    _folder_deck_repo.update_deck(deck_id, name, folder_ids or [])


def delete_deck(deck_id):
    _folder_deck_repo.delete_deck(deck_id)


def get_deck_folders(deck_id):
    return _folder_deck_repo.get_deck_folders(deck_id)


# --- Card Management ---


def get_all_cards_paged(search="", page=1, limit=50, deck_id=None):
    scope = CardScope(deck_id=deck_id) if deck_id else CardScope()
    cards, total = _card_repo.list(scope, search, page, limit)
    # Convert to old dict format
    card_list = []
    for c in cards:
        c_dict = {
            "id": c.id,
            "front": c.front,
            "back": c.back,
            "card_type": c.card_type,
            "next_review": c.next_review,
            "state": c.state,
            "step": c.step,
            "stability": c.stability,
            "difficulty": c.difficulty,
            "last_review": c.last_review,
            "reps": c.reps,
            "lapses": c.lapses,
            "deck_names": c.deck_names,
            "deck_ids": c.deck_ids,
        }
        card_list.append(c_dict)
    return card_list, total


def get_card_by_id(card_id):
    card = _card_repo.get_by_id(card_id)
    if card:
        return {
            "id": card.id,
            "front": card.front,
            "back": card.back,
            "card_type": card.card_type,
            "next_review": card.next_review,
            "state": card.state,
            "step": card.step,
            "stability": card.stability,
            "difficulty": card.difficulty,
            "last_review": card.last_review,
            "reps": card.reps,
            "lapses": card.lapses,
            "deck_names": card.deck_names,
            "deck_ids": card.deck_ids,
        }
    return None


def add_card(front, back, card_type, deck_ids):
    card_id, merged = _card_repo.add(front, back, card_type, deck_ids)
    if merged:
        from domain.events import CardsImportedEvent

        _notifier.notify(CardsImportedEvent(imported=0, merged=1))
    return card_id, merged


def update_card(card_id, front, back, card_type, deck_ids):
    _card_repo.update(card_id, front, back, card_type, deck_ids)


def delete_card(card_id):
    _card_repo.delete(card_id)


def import_csv_data(csv_text, deck_ids, card_type="recognize"):
    return _card_repo.import_csv(csv_text, deck_ids, card_type)


# --- Spaced Repetition (FSRS) Study ---


def get_study_cards(deck_id=None, folder_id=None, exam_id=None):
    scope = ExamScope()
    if deck_id:
        scope["deck_id"] = deck_id
    elif folder_id:
        scope["folder_id"] = folder_id
    elif exam_id:
        scope["exam_id"] = exam_id

    try:
        daily_new_limit = int(_settings_repo.get("daily_new_limit", "0") or "0")
    except (TypeError, ValueError):
        daily_new_limit = 0
    due_cards = _exam_scheduler.get_due_cards(
        scope, _time_provider.now_utc(), daily_new_limit
    )

    # Convert to old dict format
    new_cards = []
    for c in due_cards.new_cards:
        new_cards.append(
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "card_type": c.card_type,
                "next_review": c.next_review,
                "state": c.state,
                "step": c.step,
                "stability": c.stability,
                "difficulty": c.difficulty,
                "last_review": c.last_review,
                "reps": c.reps,
                "lapses": c.lapses,
                "deck_names": c.deck_names,
                "deck_ids": c.deck_ids,
            }
        )
    due_list = []
    for c in due_cards.due_cards:
        due_list.append(
            {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "card_type": c.card_type,
                "next_review": c.next_review,
                "state": c.state,
                "step": c.step,
                "stability": c.stability,
                "difficulty": c.difficulty,
                "last_review": c.last_review,
                "reps": c.reps,
                "lapses": c.lapses,
                "deck_names": c.deck_names,
                "deck_ids": c.deck_ids,
            }
        )
    return StudyCardsResult(new_cards, due_list, due_cards.next_due_at)


def submit_card_review(card_id, rating_val, request_id=None):
    if request_id:
        prior = _adapter.execute(
            """
            SELECT c.next_review FROM review_requests rr
            JOIN cards c ON c.id = rr.card_id
            WHERE rr.request_id = ? AND rr.card_id = ?
            """,
            (request_id, card_id),
        )
        if prior:
            return prior[0]["next_review"]
    card_state = _card_repo.get_card_state(card_id)
    if not card_state:
        logger.warning("嘗試複習不存在的卡片: card_id=%d", card_id)
        return None

    retention = float(_settings_repo.get("desired_retention", "0.9") or "0.9")
    weights_str = _settings_repo.get("fsrs_weights", "")
    if weights_str:
        try:
            weights = tuple(float(w.strip()) for w in weights_str.split(","))
            if len(weights) == 21:
                _fsrc_scheduler.set_parameters(weights)
                logger.info("使用自定義 FSRS 參數（%d 維）", len(weights))
            else:
                logger.warning(
                    "FSRS 參數數量錯誤（需 21 個，目前 %d 個）", len(weights)
                )
        except ValueError as e:
            logger.error("FSRS 參數解析失敗: %s", e)

    exam_cutoff = _exam_scheduler.get_earliest_exam_cutoff(card_id)
    scheduled = _fsrc_scheduler.review(
        card_state, rating_val, _time_provider.now_utc(), retention, exam_cutoff
    )

    # Get reps and lapses from current card state
    reps = card_state.reps + 1
    lapses = card_state.lapses + (1 if rating_val == 1 else 0)

    saved = _card_repo.save_review_with_log(
        card_id,
        scheduled,
        reps,
        lapses,
        _time_provider.now_utc(),
        rating_val,
        card_state.state,
        request_id=request_id,
    )
    if not saved:
        prior = _adapter.execute(
            "SELECT next_review FROM cards WHERE id = ?", (card_id,)
        )
        return prior[0]["next_review"] if prior else None

    # Get deck names for notification
    card_row = _card_repo.get_by_id(card_id)
    deck_names = card_row.deck_names if card_row else []

    # Send notification
    from domain.events import CardReviewedEvent

    _notifier.notify(
        CardReviewedEvent(
            card_id=card_id,
            front=card_state.front if hasattr(card_state, "front") else "",
            rating=rating_val,
            deck_names=deck_names,
            next_review=scheduled.next_review,
        )
    )

    return _time_provider.format_iso(scheduled.next_review)


# --- System/Settings Operations ---


def reset_all_learning_progress():
    now_str = _time_provider.format_iso(_time_provider.now_utc())
    _adapter.execute(
        """
        UPDATE cards
        SET state = 0, step = 0, stability = NULL, difficulty = NULL, last_review = NULL, next_review = ?, reps = 0, lapses = 0
    """,
        (now_str,),
    )
    from domain.events import ProgressResetEvent

    _notifier.notify(ProgressResetEvent())


def delete_all_app_data():
    _adapter.execute("DELETE FROM cards")
    _adapter.execute("DELETE FROM card_decks")
    _adapter.execute("DELETE FROM decks")
    _adapter.execute("DELETE FROM folders")
    _adapter.execute("DELETE FROM deck_folders")
    _adapter.execute("DELETE FROM exams")
    _adapter.execute("DELETE FROM exam_decks")
    _adapter.execute("DELETE FROM exam_folders")
    _adapter.execute("DELETE FROM sqlite_sequence")
    from domain.events import DataClearedEvent

    _notifier.notify(DataClearedEvent())


def get_setting(key, default=None):
    return _settings_repo.get(key, default)


def set_setting(key, value):
    _settings_repo.set(key, value)


# --- Exam Schedule & Vocabulary Adjustments ---


def parse_input_datetime(date_str):
    return _time_provider.parse_iso(date_str)


def distribute_exam_cards(exam_id, conn=None):
    return _exam_scheduler.distribute(
        exam_id, None, _time_provider.now_utc(), conn=conn
    )


def process_expired_exams():
    _exam_scheduler.process_expired(_time_provider.now_utc())
    # The new scheduler already handles redistribution internally


def get_all_exams():
    exams = _exam_scheduler.get_all_exams()
    # Convert to old dict format
    exam_list = []
    for e in exams:
        e_dict = {
            "id": e.id,
            "name": e.name,
            "date": _time_provider.format_iso(e.date),
            "processed": e.processed,
            "decks": [{"id": d.id, "name": d.name} for d in e.decks],
            "folders": [{"id": f.id, "name": f.name} for f in e.folders],
            "total_cards": e.total_cards,
            "learned_cards": e.learned_cards,
            "progress_percent": e.progress_percent,
            "days_remaining": e.days_remaining,
            "seconds_remaining": e.seconds_remaining,
            "countdown_str": e.countdown_str,
            "is_expired": e.is_expired,
        }
        exam_list.append(e_dict)
    return exam_list


def create_exam(name, date_str, deck_ids=None, folder_ids=None):
    exam_id = _exam_scheduler.create_exam(
        name, date_str, deck_ids or [], folder_ids or []
    )
    utc_dt = _time_provider.parse_iso(date_str)
    from domain.events import ExamCreatedEvent

    _notifier.notify(ExamCreatedEvent(name=name, date=utc_dt))
    return exam_id


def delete_exam(exam_id):
    # Get name before deletion for notification
    exams = _exam_scheduler.get_all_exams()
    exam_name = None
    for e in exams:
        if e.id == exam_id:
            exam_name = e.name
            break
    _exam_scheduler.delete_exam(exam_id)
    if exam_name:
        from domain.events import ExamDeletedEvent

        _notifier.notify(ExamDeletedEvent(name=exam_name))


def import_exams_csv(csv_text):
    # Delegate to exam scheduler (simplified)
    return _exam_scheduler.import_exams_csv(csv_text)


def get_today_cards(only_exams=True):
    # Use the new exam scheduler's get_due_cards for all decks
    # This is a simplified implementation for backward compatibility
    all_decks = _folder_deck_repo.list_all_decks()
    try:
        daily_new_limit = int(_settings_repo.get("daily_new_limit", "0") or "0")
    except (TypeError, ValueError):
        daily_new_limit = 0

    new_cards_dict = {}
    due_cards_dict = {}

    for d in all_decks:
        scope = ExamScope(deck_id=d.id)
        due = _exam_scheduler.get_due_cards(
            scope, _time_provider.now_utc(), daily_new_limit
        )
        for c in due.new_cards:
            new_cards_dict[c.id] = c
        for c in due.due_cards:
            due_cards_dict[c.id] = c

    # Filter by only_exams flag
    # Get exam deck ids
    active_exams = _adapter.execute(
        "SELECT id FROM exams WHERE date > ? AND processed = 0",
        (_time_provider.format_iso(_time_provider.now_utc()),),
    )
    exam_deck_ids = set()
    for e in active_exams:
        direct = _adapter.execute(
            "SELECT deck_id FROM exam_decks WHERE exam_id = ?", (e["id"],)
        )
        for d in direct:
            exam_deck_ids.add(d["deck_id"])
        folder_decks = _adapter.execute(
            """
            SELECT df.deck_id FROM deck_folders df
            JOIN exam_folders ef ON df.folder_id = ef.folder_id
            WHERE ef.exam_id = ?
        """,
            (e["id"],),
        )
        for d in folder_decks:
            exam_deck_ids.add(d["deck_id"])

    filtered_new = []
    filtered_due = []
    for c in list(new_cards_dict.values()) + list(due_cards_dict.values()):
        is_exam_deck = any(deck_id in exam_deck_ids for deck_id in c.deck_ids)
        if (only_exams and is_exam_deck) or (not only_exams and not is_exam_deck):
            c_dict = {
                "id": c.id,
                "front": c.front,
                "back": c.back,
                "card_type": c.card_type,
                "next_review": c.next_review,
                "state": c.state,
                "step": c.step,
                "stability": c.stability,
                "difficulty": c.difficulty,
                "last_review": c.last_review,
                "reps": c.reps,
                "lapses": c.lapses,
                "deck_names": c.deck_names,
                "deck_ids": c.deck_ids,
            }
            if c in new_cards_dict.values():
                filtered_new.append(c_dict)
            else:
                filtered_due.append(c_dict)

    # Compute earliest next_due_at for today's scope
    now_utc = _time_provider.now_utc()
    next_due_dt = None
    for d in all_decks:
        is_exam_deck = d.id in exam_deck_ids
        if (only_exams and is_exam_deck) or (not only_exams and not is_exam_deck):
            due = _exam_scheduler.get_due_cards(
                ExamScope(deck_id=d.id), now_utc, daily_new_limit
            )
            if due.next_due_at:
                dt = _time_provider.parse_iso(due.next_due_at)
                if dt and (next_due_dt is None or dt < next_due_dt):
                    next_due_dt = dt

    next_due_at_str = _time_provider.format_iso(next_due_dt) if next_due_dt else None
    return StudyCardsResult(filtered_new, filtered_due, next_due_at_str)


def get_today_summary_stats():
    all_decks = _folder_deck_repo.list_all_decks()
    try:
        daily_new_limit = int(_settings_repo.get("daily_new_limit", "0") or "0")
    except (TypeError, ValueError):
        daily_new_limit = 0

    # Get exam deck ids
    active_exams = _adapter.execute(
        "SELECT id FROM exams WHERE date > ? AND processed = 0",
        (_time_provider.format_iso(_time_provider.now_utc()),),
    )
    exam_deck_ids = set()
    for e in active_exams:
        direct = _adapter.execute(
            "SELECT deck_id FROM exam_decks WHERE exam_id = ?", (e["id"],)
        )
        for d in direct:
            exam_deck_ids.add(d["deck_id"])
        folder_decks = _adapter.execute(
            """
            SELECT df.deck_id FROM deck_folders df
            JOIN exam_folders ef ON df.folder_id = ef.folder_id
            WHERE ef.exam_id = ?
        """,
            (e["id"],),
        )
        for d in folder_decks:
            exam_deck_ids.add(d["deck_id"])

    exam_new = {}
    exam_due = {}
    general_new = {}
    general_due = {}

    for d in all_decks:
        deck_id = d.id
        is_exam_deck = deck_id in exam_deck_ids

        scope = ExamScope(deck_id=deck_id)
        due = _exam_scheduler.get_due_cards(
            scope, _time_provider.now_utc(), daily_new_limit
        )

        if is_exam_deck:
            for c in due.new_cards:
                exam_new[c.id] = c
            for c in due.due_cards:
                exam_due[c.id] = c
        else:
            for c in due.new_cards:
                general_new[c.id] = c
            for c in due.due_cards:
                general_due[c.id] = c

    return {
        "exam_new_count": len(exam_new),
        "exam_due_count": len(exam_due),
        "exam_total": len(exam_new) + len(exam_due),
        "general_new_count": len(general_new),
        "general_due_count": len(general_due),
        "general_total": len(general_new) + len(general_due),
        "today_total": len(exam_new)
        + len(exam_due)
        + len(general_new)
        + len(general_due),
    }


def get_revlog_csv_string():
    import csv
    import io
    import time

    rows = _adapter.execute(
        "SELECT card_id, review_time, review_rating, review_state, review_duration FROM revlog ORDER BY card_id, review_time"
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["card_id", "review_time", "review_rating", "review_state", "review_duration"]
    )

    for r in rows:
        dt = _time_provider.parse_iso(r["review_time"])
        ts_ms = int(dt.timestamp() * 1000) if dt else int(time.time() * 1000)
        writer.writerow(
            [
                r["card_id"],
                ts_ms,
                r["review_rating"],
                r["review_state"],
                r["review_duration"],
            ]
        )

    return output.getvalue()


def init_db_schema():
    # Already handled by SqliteAdapter auto_init
    pass


# Ensure schema is initialized
init_db_schema()
