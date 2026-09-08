# repos/card_repo.py
from __future__ import annotations
import csv
import io
import logging
from datetime import datetime
from typing import List, Tuple, Any, Dict
from domain.protocols import DatabaseAdapter, CardScope, TimeProvider
from domain.models import CardRow, CardState, ScheduledReview

logger = logging.getLogger(__name__)


class CardRepoImpl:
    # CSV 匯入限制
    CSV_MAX_SIZE = 1024 * 1024  # 1MB
    CSV_MAX_ROWS = 10000  # 最大匯入筆數
    FIELD_MAX_LENGTH = 500  # 每個欄位最大長度

    def __init__(self, adapter: DatabaseAdapter, time_provider: TimeProvider):
        self.adapter = adapter
        self.time = time_provider

    def get_by_id(self, card_id: int) -> CardRow | None:
        rows = self.adapter.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
        if not rows:
            return None
        row = rows[0]
        deck_rows = self.adapter.execute(
            """
            SELECT d.name FROM decks d
            JOIN card_decks cd ON d.id = cd.deck_id
            WHERE cd.card_id = ?
        """,
            (card_id,),
        )
        row["deck_names"] = [d["name"] for d in deck_rows]
        deck_links = self.adapter.execute(
            "SELECT deck_id FROM card_decks WHERE card_id = ?", (card_id,)
        )
        row["deck_ids"] = [d["deck_id"] for d in deck_links]
        return CardRow(**row)

    def list(
        self, scope: CardScope, search: str = "", page: int = 1, limit: int = 50
    ) -> Tuple[List[CardRow], int]:
        offset = (page - 1) * limit

        params: list[Any] = []
        if scope.get("deck_id"):
            query = "SELECT c.* FROM cards c JOIN card_decks cd ON c.id = cd.card_id WHERE cd.deck_id = ?"
            params = [scope["deck_id"]]
            if search:
                query += " AND (c.front LIKE ? OR c.back LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
        elif scope.get("folder_id"):
            query = """
                SELECT c.* FROM cards c
                JOIN card_decks cd ON c.id = cd.card_id
                JOIN deck_folders df ON cd.deck_id = df.deck_id
                WHERE df.folder_id = ?
            """
            params = [scope["folder_id"]]
            if search:
                query += " AND (c.front LIKE ? OR c.back LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
        elif scope.get("exam_id"):
            query = """
                SELECT DISTINCT c.* FROM cards c
                JOIN card_decks cd ON c.id = cd.card_id
                WHERE cd.deck_id IN (
                    SELECT deck_id FROM exam_decks WHERE exam_id = ?
                    UNION
                    SELECT deck_id FROM deck_folders WHERE folder_id IN (
                        SELECT folder_id FROM exam_folders WHERE exam_id = ?
                    )
                )
            """
            params = [scope["exam_id"], scope["exam_id"]]
            if search:
                query += " AND (c.front LIKE ? OR c.back LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])
        else:
            query = "SELECT c.* FROM cards c"
            params = []
            if search:
                query += " WHERE c.front LIKE ? OR c.back LIKE ?"
                params.extend([f"%{search}%", f"%{search}%"])

        count_query = query.replace("SELECT c.*", "SELECT COUNT(*)", 1).replace(
            "SELECT DISTINCT c.*", "SELECT COUNT(DISTINCT c.id)", 1
        )
        total = (
            self.adapter.execute(count_query, tuple(params))[0]["COUNT(*)"]
            if "COUNT(*)" in count_query
            else self.adapter.execute(count_query, tuple(params))[0].get(
                "COUNT(DISTINCT c.id)", 0
            )
        )

        query += " ORDER BY c.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cards = self.adapter.execute(query, tuple(params))

        # 批次查詢所有卡片的 deck 資訊，避免 N+1 查詢問題
        card_ids = [c["id"] for c in cards]
        deck_names_map: Dict[int, List[str]] = {}
        deck_ids_map: Dict[int, List[int]] = {}

        if card_ids:
            placeholders = ",".join("?" for _ in card_ids)
            # 查詢 deck names
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

            # 查詢 deck ids
            deck_links = self.adapter.execute(
                f"""
                SELECT card_id, deck_id FROM card_decks
                WHERE card_id IN ({placeholders})
            """,
                tuple(card_ids),
            )
            for row in deck_links:
                deck_ids_map.setdefault(row["card_id"], []).append(row["deck_id"])

        card_list = []
        for c in cards:
            c_dict = dict(c)
            c_dict["deck_names"] = deck_names_map.get(c["id"], [])
            c_dict["deck_ids"] = deck_ids_map.get(c["id"], [])
            card_list.append(CardRow(**c_dict))

        return card_list, total

    def add(
        self, front: str, back: str, card_type: str, deck_ids: List[int]
    ) -> Tuple[int, bool]:
        front_stripped = front.strip()[: self.FIELD_MAX_LENGTH]
        back_stripped = back.strip()[: self.FIELD_MAX_LENGTH]

        def _tx(conn):
            cur = conn.cursor()

            existing = cur.execute(
                "SELECT * FROM cards WHERE front = ?", (front_stripped,)
            ).fetchone()
            now_str = self.time.format_iso(self.time.now_utc())

            if existing:
                merged_back = existing["back"] + "\n\n" + back_stripped
                new_type = (
                    "spell"
                    if (existing["card_type"] == "spell" or card_type == "spell")
                    else (existing["card_type"] or "recognize")
                )
                cur.execute(
                    "UPDATE cards SET back = ?, card_type = ? WHERE id = ?",
                    (merged_back, new_type, existing["id"]),
                )
                card_id = existing["id"]
                merged = True
            else:
                cur.execute(
                    """
                    INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        front_stripped,
                        back_stripped,
                        now_str,
                        0,
                        0,
                        None,
                        None,
                        None,
                        0,
                        0,
                        card_type,
                    ),
                )
                card_id = cur.lastrowid
                merged = False

            for did in deck_ids:
                if not cur.execute(
                    "SELECT 1 FROM card_decks WHERE card_id = ? AND deck_id = ?",
                    (card_id, did),
                ).fetchone():
                    cur.execute(
                        "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
                        (card_id, did),
                    )
            return card_id, merged

        return self.adapter.transaction(_tx)

    def update(
        self, card_id: int, front: str, back: str, card_type: str, deck_ids: List[int]
    ) -> None:
        def _tx(conn):
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE cards SET front = ?, back = ?, card_type = ? WHERE id = ?
            """,
                (
                    front.strip()[: self.FIELD_MAX_LENGTH],
                    back.strip(),
                    card_type,
                    card_id,
                ),
            )
            cur.execute("DELETE FROM card_decks WHERE card_id = ?", (card_id,))
            for did in deck_ids:
                cur.execute(
                    "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
                    (card_id, did),
                )

        self.adapter.transaction(_tx)

    def delete(self, card_id: int) -> None:
        def _tx(conn):
            conn.execute("DELETE FROM card_decks WHERE card_id = ?", (card_id,))
            conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))

        self.adapter.transaction(_tx)

    def import_csv(
        self, csv_text: str, deck_ids: List[int], card_type: str
    ) -> Tuple[int, int]:
        ct = card_type
        if ct not in ["recognize", "spell"]:
            ct = "recognize"

        # 驗證輸入大小
        if len(csv_text) > self.CSV_MAX_SIZE:
            raise ValueError(f"CSV 內容過大（最大 {self.CSV_MAX_SIZE // 1024}KB）")

        def _tx(conn):
            cur = conn.cursor()
            try:
                lines = csv_text.strip().split("\n")
                if len(lines) > self.CSV_MAX_ROWS:
                    raise ValueError(f"CSV 行數過多（最多 {self.CSV_MAX_ROWS} 行）")

                reader = csv.reader(io.StringIO(csv_text.strip()))
            except csv.Error as e:
                raise ValueError(f"CSV 格式解析失敗：{str(e)}")

            imported_count = 0
            merged_count = 0
            now_str = self.time.format_iso(self.time.now_utc())

            for row_num, row in enumerate(reader, 1):
                try:
                    if not row or len(row) < 2:
                        continue
                    front = row[0].strip()[: self.FIELD_MAX_LENGTH]
                    back = row[1].strip()
                    if not front or not back:
                        continue

                    existing = cur.execute(
                        "SELECT * FROM cards WHERE front = ?", (front,)
                    ).fetchone()
                    if existing:
                        merged_back = existing["back"] + "\n\n" + back
                        new_card_type = (
                            "spell"
                            if (existing["card_type"] == "spell" or ct == "spell")
                            else (existing["card_type"] or "recognize")
                        )
                        cur.execute(
                            "UPDATE cards SET back = ?, card_type = ? WHERE id = ?",
                            (
                                merged_back,
                                new_card_type,
                                existing["id"],
                            ),
                        )
                        card_id = existing["id"]
                        merged_count += 1
                    else:
                        cur.execute(
                            """
                            INSERT INTO cards (front, back, next_review, state, step, stability, difficulty, last_review, reps, lapses, card_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                            (front, back, now_str, 0, 0, None, None, None, 0, 0, ct),
                        )
                        card_id = cur.lastrowid
                        imported_count += 1

                    for did in deck_ids:
                        if not cur.execute(
                            "SELECT 1 FROM card_decks WHERE card_id = ? AND deck_id = ?",
                            (card_id, did),
                        ).fetchone():
                            cur.execute(
                                "INSERT INTO card_decks (card_id, deck_id) VALUES (?, ?)",
                                (card_id, did),
                            )
                except IndexError:
                    raise ValueError(f"CSV 第 {row_num} 行缺少必要的欄位！")

            if imported_count > 0 or merged_count > 0:
                from database import send_discord_message

                msg = f"📋 批次匯入成功！\n- 新增單字卡：{imported_count} 張\n- 合併重複卡：{merged_count} 張"
                send_discord_message(msg)

            return imported_count, merged_count

        return self.adapter.transaction(_tx)

    def get_card_state(self, card_id: int) -> CardState | None:
        rows = self.adapter.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
        if not rows:
            return None
        r = rows[0]
        return CardState(
            id=r["id"],
            state=r["state"] or 0,
            step=r["step"] or 0,
            stability=r["stability"],
            difficulty=r["difficulty"],
            last_review=self.time.parse_iso(r["last_review"])
            if r["last_review"]
            else None,
            due=self.time.parse_iso(r["next_review"]) if r["next_review"] else None,
            reps=r["reps"] or 0,
            lapses=r["lapses"] or 0,
        )

    def save_review(
        self, card_id: int, review: ScheduledReview, reps: int, lapses: int
    ) -> None:
        def _tx(conn):
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE cards
                SET state = ?, step = ?, stability = ?, difficulty = ?, last_review = ?, next_review = ?, reps = ?, lapses = ?
                WHERE id = ?
            """,
                (
                    review.state,
                    review.step,
                    review.stability,
                    review.difficulty,
                    self.time.format_iso(review.last_review),
                    self.time.format_iso(review.next_review),
                    reps,
                    lapses,
                    card_id,
                ),
            )

        self.adapter.transaction(_tx)

    def save_revlog(
        self,
        card_id: int,
        review_time: datetime,
        rating: int,
        state: int,
        duration: int,
    ) -> None:
        def _tx(conn):
            conn.execute(
                """
                INSERT INTO revlog (card_id, review_time, review_rating, review_state, review_duration)
                VALUES (?, ?, ?, ?, ?)
                """,
                (card_id, self.time.format_iso(review_time), rating, state, duration),
            )

        self.adapter.transaction(_tx)

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
    ) -> bool:
        """Atomically persist a card's schedule and its matching review log."""

        def _tx(conn):
            if request_id:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO review_requests
                        (request_id, card_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (request_id, card_id, self.time.format_iso(review_time)),
                )
                if cursor.rowcount == 0:
                    return False
            cursor = conn.execute(
                """
                UPDATE cards
                SET state = ?, step = ?, stability = ?, difficulty = ?,
                    last_review = ?, next_review = ?, reps = ?, lapses = ?
                WHERE id = ?
                """,
                (
                    review.state,
                    review.step,
                    review.stability,
                    review.difficulty,
                    self.time.format_iso(review.last_review),
                    self.time.format_iso(review.next_review),
                    reps,
                    lapses,
                    card_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Card not found: {card_id}")
            conn.execute(
                """
                INSERT INTO revlog
                    (card_id, review_time, review_rating, review_state, review_duration)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    card_id,
                    self.time.format_iso(review_time),
                    rating,
                    previous_state,
                    duration,
                ),
            )
            return True

        return self.adapter.transaction(_tx)
