from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from adapters.sqlite_adapter import SqliteAdapter
from domain.models import ScheduledReview
from domain.time_provider import FixedTimeProvider
from repos.card_repo import CardRepoImpl
from scripts.sqlite_backup import backup_database


class PersistenceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.adapter = SqliteAdapter(str(self.db_path))
        self.now = datetime(2026, 9, 7, 4, 0, tzinfo=timezone.utc)
        self.repo = CardRepoImpl(self.adapter, FixedTimeProvider(self.now))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_execute_commits_mutating_statements(self):
        self.adapter.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)", ("probe", "saved")
        )
        rows = self.adapter.execute(
            "SELECT value FROM settings WHERE key = ?", ("probe",)
        )
        self.assertEqual(rows, [{"value": "saved"}])

    def test_review_and_revlog_are_persisted_together(self):
        def seed(conn):
            cursor = conn.execute(
                """
                INSERT INTO cards (front, back, next_review, card_type)
                VALUES (?, ?, ?, ?)
                """,
                ("word", "meaning", self.now.isoformat(), "recognize"),
            )
            return cursor.lastrowid

        card_id = self.adapter.transaction(seed)
        review = ScheduledReview(
            next_review=self.now,
            state=1,
            step=1,
            stability=1.0,
            difficulty=5.0,
            last_review=self.now,
        )
        self.repo.save_review_with_log(
            card_id, review, 1, 0, self.now, 3, 0, request_id="same-request"
        )
        self.repo.save_review_with_log(
            card_id, review, 2, 0, self.now, 3, 1, request_id="same-request"
        )

        card = self.adapter.execute("SELECT reps FROM cards WHERE id = ?", (card_id,))
        logs = self.adapter.execute(
            "SELECT review_rating FROM revlog WHERE card_id = ?", (card_id,)
        )
        self.assertEqual(card[0]["reps"], 1)
        self.assertEqual(logs, [{"review_rating": 3}])

    def test_backup_contains_committed_wal_data(self):
        self.adapter.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)", ("live", "value")
        )
        backup_path = Path(self.temp_dir.name) / "backup.db"
        backup_database(self.db_path, backup_path)
        backup = SqliteAdapter(str(backup_path), auto_init=False)
        self.assertEqual(
            backup.execute("SELECT value FROM settings WHERE key = ?", ("live",)),
            [{"value": "value"}],
        )

    def test_day_cutoff_uses_0400_at_utc_plus_8(self):
        before_rollover = datetime(2026, 9, 6, 19, 59, tzinfo=timezone.utc)
        at_rollover = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)
        provider = FixedTimeProvider(before_rollover)
        self.assertEqual(provider.day_cutoff_utc(), at_rollover)
        provider.set_now(at_rollover)
        self.assertEqual(
            provider.day_cutoff_utc(),
            datetime(2026, 9, 7, 20, 0, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
