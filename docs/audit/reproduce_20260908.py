"""Isolated audit probes. FAIL means an expected user invariant is violated.

Run from the repository root: python docs/audit/reproduce_20260908.py
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
_temp = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = str(Path(_temp.name) / "audit.db")
os.environ["DISCORD_WEBHOOK_URL"] = ""
os.environ["SECRET_KEY"] = "isolated-audit-only"
import database as db  # noqa: E402
from app import app  # noqa: E402
from domain.time_provider import FixedTimeProvider  # noqa: E402
from schedulers.fsrc_scheduler import FsrcSchedulerImpl  # noqa: E402


class Audit(unittest.TestCase):
    def setUp(self):
        db.delete_all_app_data()
        db._adapter.execute("DELETE FROM settings")
        self.now = datetime(2026, 9, 8, 4, tzinfo=timezone.utc)
        self.time = FixedTimeProvider(self.now)
        db._time_provider = self.time
        for component in (db._card_repo, db._folder_deck_repo, db._exam_scheduler):
            component.time = self.time
        db._fsrc_scheduler = FsrcSchedulerImpl()
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()
        self.deck = db.create_deck("A")

    def card(self, name="word", decks=None, back="meaning"):
        return db.add_card(name, back, "recognize", decks or [self.deck])[0]

    def test_later_exam_must_not_postpone_cards_past_earlier_exam(self):
        for i in range(12):
            self.card(str(i))
        early = self.now + timedelta(days=3)
        with patch(
            "schedulers.exam_scheduler.random.shuffle", lambda values: None
        ), patch("schedulers.exam_scheduler.random.randint", return_value=0):
            db.create_exam("early", early.isoformat(), [self.deck])
            db.create_exam(
                "late", (self.now + timedelta(days=30)).isoformat(), [self.deck]
            )
        rows = db._adapter.execute("SELECT next_review FROM cards")
        late = sum(self.time.parse_iso(r["next_review"]) >= early for r in rows)
        self.assertEqual(late, 0, f"{late}/12 new cards moved past the early exam")

    def test_shared_card_summary_matches_actual_queues(self):
        other = db.create_deck("B")
        self.card(decks=[self.deck, other])
        db.create_exam("exam", (self.now + timedelta(days=10)).isoformat(), [self.deck])
        summary = db.get_today_summary_stats()
        actual = sum(
            len(db.get_today_cards(flag).new_cards)
            + len(db.get_today_cards(flag).due_cards)
            for flag in (True, False)
        )
        self.assertEqual(summary["today_total"], actual)

    def test_daily_limit_applies_across_decks(self):
        other = db.create_deck("B")
        self.card("a")
        self.card("b", [other])
        db.set_setting("daily_new_limit", "1")
        self.assertLessEqual(len(db.get_today_cards(False).new_cards), 1)

    def test_daily_limit_selection_is_stable_while_polling(self):
        self.card("a")
        self.card("b")
        db.set_setting("daily_new_limit", "1")
        first = [c["id"] for c in db.get_study_cards(deck_id=self.deck).new_cards]
        second = [c["id"] for c in db.get_study_cards(deck_id=self.deck).new_cards]
        self.assertEqual(first, second)

    def test_daily_limit_is_global_for_individual_decks(self):
        other = db.create_deck("B")
        self.card("a")
        self.card("b", [other])
        db.set_setting("daily_new_limit", "1")
        total = len(db.get_study_cards(deck_id=self.deck).new_cards)
        total += len(db.get_study_cards(deck_id=other).new_cards)
        self.assertLessEqual(total, 1)

    def test_form_date_is_midnight_in_taipei(self):
        response = self.client.post(
            "/exams/add",
            data={"name": "date", "date": "2026-09-10", "decks": str(self.deck)},
        )
        self.assertEqual(response.status_code, 302)
        stored = db._adapter.execute("SELECT date FROM exams")[0]["date"]
        expected = datetime(2026, 9, 9, 16, tzinfo=timezone.utc)
        self.assertEqual(self.time.parse_iso(stored), expected)

    def test_merge_does_not_silently_discard_new_meaning(self):
        cid = self.card(back="x" * 500)
        db.add_card("word", "new meaning", "recognize", [self.deck])
        self.assertIn("new meaning", db.get_card_by_id(cid)["back"])

    def test_invalid_weights_rejected_before_breaking_reviews(self):
        cid = self.card()
        self.client.post(
            "/settings/update-weights", data={"fsrs_weights": ",".join(["-1"] * 21)}
        )
        try:
            response = self.client.post(
                "/study/api/review",
                json={"card_id": cid, "rating": 3, "request_id": "probe"},
            )
        except (ValueError, AssertionError) as exc:
            self.fail(f"Saved weights break subsequent reviews: {exc}")
        self.assertEqual(response.status_code, 200)

    def test_oversize_csv_returns_feedback_instead_of_500(self):
        try:
            response = self.client.post(
                "/cards/import",
                data={
                    "csv_text": "a,b\n" * 10001,
                    "decks": str(self.deck),
                    "card_type": "recognize",
                },
            )
        except TypeError as exc:
            self.fail(str(exc))
        self.assertLess(response.status_code, 500)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        _temp.cleanup()
