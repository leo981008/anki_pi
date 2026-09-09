# repos/folder_deck_repo.py
from __future__ import annotations
import sqlite3
from domain.protocols import DatabaseAdapter, TimeProvider
from domain.models import FolderWithDecks, DeckRow


class FolderDeckRepoImpl:
    def __init__(self, adapter: DatabaseAdapter, time_provider: TimeProvider):
        self.adapter = adapter
        self.time = time_provider

    def list_folders_with_decks(self) -> tuple[list[FolderWithDecks], list[DeckRow]]:
        now = self.time.now_utc()
        now_str = self.time.format_iso(now)
        day_cutoff_str = self.time.format_iso(self.time.day_cutoff_utc())

        folders = self.adapter.execute("SELECT * FROM folders")
        folder_list = []

        stats_query = """
            SELECT cd.deck_id,
                   SUM(CASE WHEN c.reps = 0 OR c.reps IS NULL THEN 1 ELSE 0 END) as new_count,
                   SUM(CASE
                       WHEN c.reps > 0 AND (
                           (c.state IN (1, 3) AND c.next_review <= ?)
                           OR ((c.state NOT IN (1, 3) OR c.state IS NULL)
                               AND c.next_review <= ?)
                       ) THEN 1
                       ELSE 0
                   END) as due_count
            FROM card_decks cd
            JOIN cards c ON cd.card_id = c.id
            GROUP BY cd.deck_id
        """
        stats_rows = self.adapter.execute(stats_query, (now_str, day_cutoff_str))
        deck_stats = {
            row["deck_id"]: {
                "new_count": row["new_count"],
                "due_count": row["due_count"],
            }
            for row in stats_rows
        }

        deck_folders_rows = self.adapter.execute("""
            SELECT df.folder_id, d.* FROM decks d
            JOIN deck_folders df ON d.id = df.deck_id
        """)

        folder_decks_map: dict[int, list[DeckRow]] = {}
        for row in deck_folders_rows:
            fid = row["folder_id"]
            d_dict = dict(row)
            del d_dict["folder_id"]
            stats = deck_stats.get(d_dict["id"], {"new_count": 0, "due_count": 0})
            d_dict.update(stats)
            folder_decks_map.setdefault(fid, []).append(DeckRow(**d_dict))

        for f in folders:
            f_dict = dict(f)
            f_dict["decks"] = folder_decks_map.get(f["id"], [])
            folder_list.append(FolderWithDecks(**f_dict))

        unassigned_decks = self.adapter.execute("""
            SELECT d.* FROM decks d
            LEFT JOIN deck_folders df ON d.id = df.deck_id
            WHERE df.folder_id IS NULL
        """)

        unassigned_list = []
        for d in unassigned_decks:
            d_dict = dict(d)
            stats = deck_stats.get(d["id"], {"new_count": 0, "due_count": 0})
            d_dict.update(stats)
            unassigned_list.append(DeckRow(**d_dict))

        return folder_list, unassigned_list

    def create_folder(self, name: str) -> int:
        def _tx(conn):
            cur = conn.cursor()
            try:
                cur.execute("INSERT INTO folders (name) VALUES (?)", (name.strip(),))
                return cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(f"資料夾「{name.strip()}」已存在！")

        return self.adapter.transaction(_tx)

    def delete_folder(self, folder_id: int) -> None:
        def _tx(conn):
            conn.execute("DELETE FROM deck_folders WHERE folder_id = ?", (folder_id,))
            conn.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

        self.adapter.transaction(_tx)

    def create_deck(self, name: str, folder_ids: list[int] | None = None) -> int:
        def _tx(conn):
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO decks (name) VALUES (?, ?)"
                    if False
                    else "INSERT INTO decks (name) VALUES (?)",
                    (name.strip(),),
                )
                deck_id = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(f"牌組「{name.strip()}」已存在！")
            if folder_ids:
                for fid in folder_ids:
                    cur.execute(
                        "INSERT INTO deck_folders (deck_id, folder_id) VALUES (?, ?)",
                        (deck_id, fid),
                    )
            return deck_id

        return self.adapter.transaction(_tx)

    def update_deck(
        self,
        deck_id: int,
        name: str,
        folder_ids: list[int] | None = None,
        card_type: str | None = None,
    ) -> None:
        if card_type not in (None, "recognize", "spell"):
            raise ValueError("無效的卡片類型！")

        def _tx(conn):
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE decks SET name = ? WHERE id = ?", (name.strip(), deck_id)
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"牌組名稱「{name.strip()}」已被其他牌組使用！")
            cur.execute("DELETE FROM deck_folders WHERE deck_id = ?", (deck_id,))
            if folder_ids:
                for fid in folder_ids:
                    cur.execute(
                        "INSERT INTO deck_folders (deck_id, folder_id) VALUES (?, ?)",
                        (deck_id, fid),
                    )
            if card_type is not None:
                cur.execute(
                    "UPDATE cards SET card_type = ? WHERE id IN "
                    "(SELECT card_id FROM card_decks WHERE deck_id = ?)",
                    (card_type, deck_id),
                )

        self.adapter.transaction(_tx)

    def delete_deck(self, deck_id: int) -> None:
        def _tx(conn):
            conn.execute("DELETE FROM deck_folders WHERE deck_id = ?", (deck_id,))
            conn.execute("DELETE FROM card_decks WHERE deck_id = ?", (deck_id,))
            conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
            conn.execute(
                "DELETE FROM cards WHERE id NOT IN (SELECT DISTINCT card_id FROM card_decks)"
            )

        self.adapter.transaction(_tx)

    def get_deck_folders(self, deck_id: int) -> list[int]:
        rows = self.adapter.execute(
            "SELECT folder_id FROM deck_folders WHERE deck_id = ?", (deck_id,)
        )
        return [r["folder_id"] for r in rows]

    def list_all_decks(self) -> list[DeckRow]:
        rows = self.adapter.execute("SELECT * FROM decks")
        return [DeckRow(**dict(r)) for r in rows]

    def list_all_folders(self) -> list[FolderWithDecks]:
        folders, _ = self.list_folders_with_decks()
        return folders
