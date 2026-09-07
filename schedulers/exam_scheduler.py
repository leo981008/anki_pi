# schedulers/exam_scheduler.py
from __future__ import annotations
import csv
import io
import random
from datetime import datetime, timedelta
from domain.protocols import (
    DatabaseAdapter,
    CardRepo,
    FolderDeckRepo,
    SettingsRepo,
    ExamScope,
    TimeProvider,
)
from domain.models import (
    SchedulePlan,
    DueCards,
    CardRow,
    Exam,
    DeckRow,
    FolderWithDecks,
)


class ExamSchedulerImpl:
    def __init__(
        self,
        adapter: DatabaseAdapter,
        card_repo: CardRepo,
        folder_deck_repo: FolderDeckRepo,
        settings_repo: SettingsRepo,
        time_provider: TimeProvider,
    ):
        self.adapter = adapter
        self.card_repo = card_repo
        self.folder_deck_repo = folder_deck_repo
        self.settings_repo = settings_repo
        self.time = time_provider

    def _get_earliest_exam_date(
        self,
        conn,
        deck_id: int | None = None,
        folder_id: int | None = None,
        exam_id: int | None = None,
        now: datetime | None = None,
    ) -> datetime | None:
        if now is None:
            now = self.time.now_utc()
        now_str = self.time.format_iso(now)

        if exam_id:
            row = conn.execute(
                "SELECT date as min_date FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
            if row and row["min_date"]:
                return self.time.parse_iso(row["min_date"])
            return None

        if deck_id:
            row = conn.execute(
                """
                SELECT MIN(e.date) as min_date FROM exams e
                WHERE e.date > ? AND e.processed = 0
                AND (
                    e.id IN (SELECT exam_id FROM exam_decks WHERE deck_id = ?)
                    OR e.id IN (
                        SELECT exam_id FROM exam_folders WHERE folder_id IN (
                            SELECT folder_id FROM deck_folders WHERE deck_id = ?
                        )
                    )
                )
            """,
                (now_str, deck_id, deck_id),
            ).fetchone()
        elif folder_id:
            row = conn.execute(
                """
                SELECT MIN(e.date) as min_date FROM exams e
                WHERE e.date > ? AND e.processed = 0
                AND (
                    e.id IN (
                        SELECT exam_id FROM exam_decks WHERE deck_id IN (
                            SELECT deck_id FROM deck_folders WHERE folder_id = ?
                        )
                    )
                    OR e.id IN (SELECT exam_id FROM exam_folders WHERE folder_id = ?)
                )
            """,
                (now_str, folder_id, folder_id),
            ).fetchone()
        else:
            return None

        if row and row["min_date"]:
            return self.time.parse_iso(row["min_date"])
        return None

    def get_earliest_exam_cutoff(self, card_id: int) -> datetime | None:
        """Get the earliest exam cutoff for a card (for FSRS exam capping)."""
        # Find decks this card belongs to
        deck_rows = self.adapter.execute(
            "SELECT deck_id FROM card_decks WHERE card_id = ?", (card_id,)
        )
        if not deck_rows:
            return None

        deck_ids = [r["deck_id"] for r in deck_rows]
        now = self.time.now_utc()
        now_str = self.time.format_iso(now)

        earliest_exam = None
        for deck_id in deck_ids:
            rows = self.adapter.execute(
                """
                SELECT MIN(e.date) as min_date FROM exams e
                WHERE e.date > ? AND e.processed = 0
                AND (
                    e.id IN (SELECT exam_id FROM exam_decks WHERE deck_id = ?)
                    OR e.id IN (
                        SELECT exam_id FROM exam_folders WHERE folder_id IN (
                            SELECT folder_id FROM deck_folders WHERE deck_id = ?
                        )
                    )
                )
            """,
                (now_str, deck_id, deck_id),
            )
            if rows:
                row = rows[0]
                if row and row["min_date"]:
                    exam_date = self.time.parse_iso(row["min_date"])
                    if earliest_exam is None or exam_date < earliest_exam:
                        earliest_exam = exam_date
        return earliest_exam

    def distribute(
        self,
        exam_id: int,
        card_ids: list[int] | None = None,
        now: datetime | None = None,
        conn=None,
    ) -> list[SchedulePlan]:
        if now is None:
            now = self.time.now_utc()

        def _tx(c):
            cur = c.cursor()
            exam = cur.execute(
                "SELECT date FROM exams WHERE id = ?", (exam_id,)
            ).fetchone()
            if not exam:
                return []

            exam_date = self.time.parse_iso(exam["date"])
            if not exam_date:
                return []

            if card_ids is not None and len(card_ids) > 0:
                if len(card_ids) > 10000:
                    raise ValueError("card_ids 數量過大（最多 10000）")
                placeholders = ",".join("?" for _ in card_ids)
                rows = cur.execute(
                    f"""
                    SELECT id, reps, next_review FROM cards
                    WHERE id IN ({placeholders})
                """,
                    card_ids,
                ).fetchall()
            else:
                rows = cur.execute(
                    """
                    SELECT DISTINCT c.id, c.reps, c.next_review
                    FROM cards c
                    INNER JOIN card_decks cd ON c.id = cd.card_id
                    INNER JOIN exam_decks ed ON cd.deck_id = ed.deck_id
                    WHERE ed.exam_id = ?
                    UNION
                    SELECT DISTINCT c.id, c.reps, c.next_review
                    FROM cards c
                    INNER JOIN card_decks cd ON c.id = cd.card_id
                    INNER JOIN deck_folders df ON cd.deck_id = df.deck_id
                    INNER JOIN exam_folders ef ON df.folder_id = ef.folder_id
                    WHERE ef.exam_id = ?
                """,
                    (exam_id, exam_id),
                ).fetchall()

            if not rows:
                return []

            total_days = (exam_date.date() - now.date()).days
            if total_days <= 0:
                return []

            new_card_ids = []
            late_card_ids = []

            for r in rows:
                reps = r["reps"] or 0
                next_review = (
                    self.time.parse_iso(r["next_review"]) if r["next_review"] else None
                )

                if reps == 0:
                    new_card_ids.append(r["id"])
                elif next_review and next_review > exam_date:
                    late_card_ids.append(r["id"])

            if not new_card_ids and not late_card_ids:
                return []

            cutoff_date = exam_date - timedelta(days=7)
            days_to_cutoff = (cutoff_date.date() - now.date()).days

            if days_to_cutoff > 0:
                days_for_new = days_to_cutoff
            else:
                days_for_new = max(1, total_days)

            updates = []
            plans = []

            if new_card_ids:
                random.shuffle(new_card_ids)
                for i, card_id in enumerate(new_card_ids):
                    day_offset = i % days_for_new
                    jitter_minutes = 0 if day_offset == 0 else random.randint(0, 60)
                    scheduled_dt = now + timedelta(
                        days=day_offset, minutes=jitter_minutes
                    )

                    cap_date = cutoff_date if days_to_cutoff > 0 else exam_date
                    if scheduled_dt >= cap_date:
                        scheduled_dt = cap_date - timedelta(minutes=1)

                    scheduled_str = self.time.format_iso(scheduled_dt)
                    updates.append((scheduled_str, card_id))
                    plans.append(
                        SchedulePlan(card_id=card_id, next_review=scheduled_dt)
                    )

            if late_card_ids:
                random.shuffle(late_card_ids)
                slots = days_for_new
                for i, card_id in enumerate(late_card_ids):
                    day_offset = i % slots
                    jitter_minutes = random.randint(0, 60)
                    scheduled_dt = now + timedelta(
                        days=day_offset, minutes=jitter_minutes
                    )

                    cap_date = cutoff_date if days_to_cutoff > 0 else exam_date
                    if scheduled_dt >= cap_date:
                        scheduled_dt = cap_date - timedelta(minutes=1)

                    scheduled_str = self.time.format_iso(scheduled_dt)
                    updates.append((scheduled_str, card_id))
                    plans.append(
                        SchedulePlan(card_id=card_id, next_review=scheduled_dt)
                    )

            if updates:
                cur.executemany(
                    "UPDATE cards SET next_review = ? WHERE id = ?", updates
                )

            return plans

        if conn is not None:
            return _tx(conn)
        return self.adapter.transaction(_tx)

    def get_due_cards(
        self, scope: ExamScope, now: datetime, daily_new_limit: int
    ) -> DueCards:
        # Determine card_ids based on scope
        if scope.get("deck_id"):
            card_rows = self.adapter.execute(
                """
                SELECT DISTINCT c.* FROM cards c
                JOIN card_decks cd ON c.id = cd.card_id
                WHERE cd.deck_id = ?
            """,
                (scope["deck_id"],),
            )
        elif scope.get("folder_id"):
            card_rows = self.adapter.execute(
                """
                SELECT DISTINCT c.* FROM cards c
                JOIN card_decks cd ON c.id = cd.card_id
                JOIN deck_folders df ON cd.deck_id = df.deck_id
                WHERE df.folder_id = ?
            """,
                (scope["folder_id"],),
            )
        elif scope.get("exam_id"):
            card_rows = self.adapter.execute(
                """
                SELECT DISTINCT c.* FROM cards c
                JOIN card_decks cd ON c.id = cd.card_id
                WHERE cd.deck_id IN (
                    SELECT deck_id FROM exam_decks WHERE exam_id = ?
                    UNION
                    SELECT deck_id FROM deck_folders WHERE folder_id IN (
                        SELECT folder_id FROM exam_folders WHERE exam_id = ?
                    )
                )
            """,
                (scope["exam_id"], scope["exam_id"]),
            )
        else:
            return DueCards(new_cards=[], due_cards=[])

        new_cards = []
        due_cards = []
        day_cutoff_utc = self.time.day_cutoff_utc()

        card_ids = [r["id"] for r in card_rows]
        deck_names_map: dict[int, list[str]] = {}
        deck_ids_map: dict[int, list[int]] = {}

        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            deck_rows = self.adapter.execute(
                f"""
                SELECT cd.card_id, d.name
                FROM decks d
                JOIN card_decks cd ON d.id = cd.deck_id
                WHERE cd.card_id IN ({placeholders})
            """,
                tuple(card_ids),
            )
            for row in deck_rows:
                deck_names_map.setdefault(row["card_id"], []).append(row["name"])

            deck_links = self.adapter.execute(
                f"""
                SELECT card_id, deck_id FROM card_decks
                WHERE card_id IN ({placeholders})
            """,
                tuple(card_ids),
            )
            for row in deck_links:
                deck_ids_map.setdefault(row["card_id"], []).append(row["deck_id"])

        for r in card_rows:
            c_dict = dict(r)
            c_dict["deck_names"] = deck_names_map.get(r["id"], [])
            c_dict["deck_ids"] = deck_ids_map.get(r["id"], [])

            reps = r["reps"] or 0
            next_review_str = r["next_review"]
            next_review = self.time.parse_iso(next_review_str)

            if reps == 0:
                if not next_review or next_review <= now:
                    new_cards.append(CardRow(**c_dict))
            else:
                db_state = r["state"]
                if db_state in (1, 3):
                    is_due = next_review and next_review <= now
                else:
                    is_due = next_review and next_review <= day_cutoff_utc

                if is_due:
                    due_cards.append(CardRow(**c_dict))

        # Apply daily new limit (0, negative, or None means unlimited)
        try:
            limit_val = int(daily_new_limit) if daily_new_limit is not None else 0
        except (TypeError, ValueError):
            limit_val = 0

        if limit_val > 0:
            scope_card_ids = [r["id"] for r in card_rows]
            learned_today = 0
            if scope_card_ids:
                day_start_utc = day_cutoff_utc - timedelta(days=1)
                placeholders = ",".join("?" for _ in scope_card_ids)
                rows = self.adapter.execute(
                    f"""
                    SELECT COUNT(DISTINCT card_id) as cnt
                    FROM revlog
                    WHERE review_state = 0
                      AND review_time >= ?
                      AND card_id IN ({placeholders})
                """,
                    tuple([self.time.format_iso(day_start_utc), *scope_card_ids]),
                )
                learned_today = rows[0]["cnt"] if rows else 0

            remaining_new = max(0, limit_val - learned_today)
            random.shuffle(new_cards)
            new_cards = new_cards[:remaining_new]

        return DueCards(new_cards=new_cards, due_cards=due_cards)

    def process_expired(self, now: datetime) -> list[SchedulePlan]:
        def _tx(conn):
            cur = conn.cursor()
            now_str = self.time.format_iso(now)

            expired = cur.execute(
                "SELECT id FROM exams WHERE date <= ? AND processed = 0", (now_str,)
            ).fetchall()
            all_plans = []

            for row in expired:
                expired_id = row["id"]

                expired_decks = cur.execute(
                    """
                    SELECT deck_id FROM exam_decks WHERE exam_id = ?
                    UNION
                    SELECT deck_id FROM deck_folders WHERE folder_id IN (
                        SELECT folder_id FROM exam_folders WHERE exam_id = ?
                    )
                """,
                    (expired_id, expired_id),
                ).fetchall()
                expired_deck_ids = [d["deck_id"] for d in expired_decks]

                cur.execute(
                    "UPDATE exams SET processed = 1 WHERE id = ?", (expired_id,)
                )

                if expired_deck_ids:
                    remaining_decks = set(expired_deck_ids)
                    upcoming = cur.execute(
                        "SELECT id FROM exams WHERE date > ? AND processed = 0 ORDER BY date ASC",
                        (now_str,),
                    ).fetchall()
                    for u_row in upcoming:
                        if not remaining_decks:
                            break
                        u_id = u_row["id"]
                        u_decks = cur.execute(
                            """
                            SELECT deck_id FROM exam_decks WHERE exam_id = ?
                            UNION
                            SELECT deck_id FROM deck_folders WHERE folder_id IN (
                                SELECT folder_id FROM exam_folders WHERE exam_id = ?
                            )
                        """,
                            (u_id, u_id),
                        ).fetchall()
                        u_deck_ids = [d["deck_id"] for d in u_decks]

                        overlap = [d for d in u_deck_ids if d in remaining_decks]
                        if overlap:
                            # 找出屬於這些重疊牌組的卡片
                            placeholders = ",".join("?" for _ in overlap)
                            card_rows = cur.execute(
                                f"""
                                SELECT DISTINCT card_id FROM card_decks
                                WHERE deck_id IN ({placeholders})
                            """,
                                tuple(overlap),
                            ).fetchall()
                            card_ids = [c["card_id"] for c in card_rows]
                            if card_ids:
                                plans = self.distribute(u_id, card_ids, now, conn=conn)
                                all_plans.extend(plans)
                            for d in overlap:
                                remaining_decks.remove(d)

            return all_plans

        return self.adapter.transaction(_tx)

    def get_all_exams(self) -> list[Exam]:
        exams = self.adapter.execute("SELECT * FROM exams ORDER BY date ASC")
        now = self.time.now_utc()
        exam_list = []

        for e in exams:
            e_dict = dict(e)
            exam_id = e["id"]

            decks = self.adapter.execute(
                """
                SELECT d.id, d.name FROM decks d
                JOIN exam_decks ed ON d.id = ed.deck_id
                WHERE ed.exam_id = ?
            """,
                (exam_id,),
            )
            e_dict["decks"] = [DeckRow(**dict(d)) for d in decks]

            folders = self.adapter.execute(
                """
                SELECT f.id, f.name FROM folders f
                JOIN exam_folders ef ON f.id = ef.folder_id
                WHERE ef.exam_id = ?
            """,
                (exam_id,),
            )
            e_dict["folders"] = [
                FolderWithDecks(id=f["id"], name=f["name"], decks=[]) for f in folders
            ]

            cards = self.adapter.execute(
                """
                SELECT c.id, c.reps, c.next_review FROM cards c
                WHERE c.id IN (
                    SELECT cd.card_id FROM card_decks cd
                    WHERE cd.deck_id IN (
                        SELECT deck_id FROM exam_decks WHERE exam_id = ?
                        UNION
                        SELECT deck_id FROM deck_folders WHERE folder_id IN (
                            SELECT folder_id FROM exam_folders WHERE exam_id = ?
                        )
                    )
                )
            """,
                (exam_id, exam_id),
            )

            total_cards = len(cards)
            learned_cards = sum(1 for c in cards if (c["reps"] or 0) > 0)

            e_dict["total_cards"] = total_cards
            e_dict["learned_cards"] = learned_cards
            e_dict["progress_percent"] = (
                int((learned_cards / total_cards * 100)) if total_cards > 0 else 0
            )

            exam_date = self.time.parse_iso(e["date"])
            if not exam_date:
                exam_date = now
            e_dict["date"] = exam_date
            e_dict["processed"] = bool(e["processed"])

            delta = exam_date - now
            e_dict["days_remaining"] = delta.days
            e_dict["seconds_remaining"] = int(delta.total_seconds())

            if delta.total_seconds() <= 0:
                e_dict["countdown_str"] = "已結束"
                e_dict["is_expired"] = True
            else:
                e_dict["is_expired"] = False
                days = delta.days
                hours = int((delta.total_seconds() % 86400) // 3600)
                if days > 0:
                    e_dict["countdown_str"] = f"剩餘 {days} 天 {hours} 小時"
                else:
                    minutes = int((delta.total_seconds() % 3600) // 60)
                    e_dict["countdown_str"] = f"剩餘 {hours} 小時 {minutes} 分鐘"

            exam_list.append(Exam(**e_dict))

        return exam_list

    def create_exam(
        self,
        name: str,
        date_str: str,
        deck_ids: list[int] | None = None,
        folder_ids: list[int] | None = None,
    ) -> int:
        utc_dt = self.time.parse_iso(date_str)
        if not utc_dt:
            raise ValueError("無效的考試日期與時間格式")

        def _tx(conn):
            cur = conn.cursor()
            date_formatted = self.time.format_iso(utc_dt)

            cur.execute(
                "INSERT INTO exams (name, date) VALUES (?, ?)",
                (name.strip()[:500], date_formatted),
            )
            exam_id = cur.lastrowid

            if deck_ids:
                for did in deck_ids:
                    cur.execute(
                        "INSERT INTO exam_decks (exam_id, deck_id) VALUES (?, ?)",
                        (exam_id, did),
                    )
            if folder_ids:
                for fid in folder_ids:
                    cur.execute(
                        "INSERT INTO exam_folders (exam_id, folder_id) VALUES (?, ?)",
                        (exam_id, fid),
                    )
            return exam_id

        exam_id = self.adapter.transaction(_tx)

        # Distribute cards for the new exam
        self.distribute(exam_id, None, self.time.now_utc())

        return exam_id

    def delete_exam(self, exam_id: int) -> None:
        def _tx(conn):
            conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))

        self.adapter.transaction(_tx)

    def import_exams_csv(self, csv_text: str) -> int:
        if not csv_text or not csv_text.strip():
            return 0

        # 限制大小
        if len(csv_text) > 1024 * 1024:
            raise ValueError("CSV 內容過大（最大 1MB）")

        imported_exam_ids: set[int] = set()

        def _tx(conn):
            cur = conn.cursor()
            try:
                reader = csv.reader(io.StringIO(csv_text.strip()))
            except csv.Error as e:
                raise ValueError(f"CSV 格式解析失敗：{str(e)}")

            imported_count = 0
            for row_num, row in enumerate(reader, 1):
                if not row or len(row) < 4:
                    continue

                name = row[0].strip()[:500]
                date_str = row[1].strip()
                scope_type = row[2].strip().lower()
                scope_name = row[3].strip()

                if not name or not date_str or not scope_name:
                    continue

                deck_ids = []
                folder_ids = []

                if scope_type == "deck":
                    deck = cur.execute(
                        "SELECT id FROM decks WHERE name = ?", (scope_name,)
                    ).fetchone()
                    if deck:
                        deck_ids.append(deck["id"])
                elif scope_type == "folder":
                    folder = cur.execute(
                        "SELECT id FROM folders WHERE name = ?", (scope_name,)
                    ).fetchone()
                    if folder:
                        folder_ids.append(folder["id"])

                if not deck_ids and not folder_ids:
                    continue

                utc_dt = self.time.parse_iso(date_str)
                if not utc_dt:
                    continue
                date_formatted = self.time.format_iso(utc_dt)

                existing = cur.execute(
                    "SELECT id FROM exams WHERE name = ? AND date = ?",
                    (name, date_formatted),
                ).fetchone()

                if existing:
                    exam_id = existing["id"]
                    if deck_ids:
                        for did in deck_ids:
                            link = cur.execute(
                                "SELECT 1 FROM exam_decks WHERE exam_id = ? AND deck_id = ?",
                                (exam_id, did),
                            ).fetchone()
                            if not link:
                                cur.execute(
                                    "INSERT INTO exam_decks (exam_id, deck_id) VALUES (?, ?)",
                                    (exam_id, did),
                                )
                    if folder_ids:
                        for fid in folder_ids:
                            link = cur.execute(
                                "SELECT 1 FROM exam_folders WHERE exam_id = ? AND folder_id = ?",
                                (exam_id, fid),
                            ).fetchone()
                            if not link:
                                cur.execute(
                                    "INSERT INTO exam_folders (exam_id, folder_id) VALUES (?, ?)",
                                    (exam_id, fid),
                                )
                else:
                    cur.execute(
                        "INSERT INTO exams (name, date) VALUES (?, ?)",
                        (name, date_formatted),
                    )
                    exam_id = cur.lastrowid
                    if deck_ids:
                        for did in deck_ids:
                            cur.execute(
                                "INSERT INTO exam_decks (exam_id, deck_id) VALUES (?, ?)",
                                (exam_id, did),
                            )
                    if folder_ids:
                        for fid in folder_ids:
                            cur.execute(
                                "INSERT INTO exam_folders (exam_id, folder_id) VALUES (?, ?)",
                                (exam_id, fid),
                            )

                imported_exam_ids.add(exam_id)
                imported_count += 1

            if imported_count > 0:
                for eid in imported_exam_ids:
                    self.distribute(eid, None, self.time.now_utc(), conn=conn)

            return imported_count

        count = self.adapter.transaction(_tx)
        if count > 0:
            from domain.events import ExamsImportedEvent
            from database import _notifier

            _notifier.notify(ExamsImportedEvent(count=count))

        return count
