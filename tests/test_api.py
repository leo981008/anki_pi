from __future__ import annotations

import os
import atexit
import tempfile
import unittest
from unittest.mock import patch

_db_file = tempfile.NamedTemporaryFile(
    prefix="anki_pi_api_", suffix=".db", delete=False
)
_db_file.close()
os.environ["DATABASE_PATH"] = _db_file.name
os.environ["DISCORD_WEBHOOK_URL"] = ""


def _cleanup_test_database():
    try:
        if os.path.exists(_db_file.name):
            os.unlink(_db_file.name)
    except OSError:
        pass


atexit.register(_cleanup_test_database)

from app import app  # noqa: E402
import database as db  # noqa: E402


class EditDeckTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.client = app.test_client()
        self.deck = db.create_deck(self.id())
        self.other = db.create_deck(self.id() + " other")
        self.first, _ = db.add_card(
            self.id() + " first", "一", "recognize", [self.deck]
        )
        self.shared, _ = db.add_card(
            self.id() + " shared", "二", "spell", [self.deck, self.other]
        )
        self.outside, _ = db.add_card(
            self.id() + " outside", "三", "recognize", [self.other]
        )

    def tearDown(self):
        db.delete_deck(self.deck)
        db.delete_deck(self.other)

    def cards(self):
        return db._adapter.execute(
            "SELECT * FROM cards WHERE id IN (?, ?, ?) ORDER BY id",
            (self.first, self.shared, self.outside),
        )

    def test_bulk_change_preserves_progress_and_unrelated_cards(self):
        response = self.client.get(f"/decks/edit/{self.deck}")
        self.assertEqual(response.status_code, 200)
        self.assertIn('name="card_type"', response.get_data(as_text=True))
        original = self.cards()
        for mode in ("spell", "recognize"):
            response = self.client.post(
                f"/decks/edit/{self.deck}",
                data={"name": self.id(), "card_type": mode},
            )
            self.assertEqual(response.status_code, 302)
            expected = [dict(card) for card in original]
            for card in expected:
                if card["id"] in (self.first, self.shared):
                    card["card_type"] = mode
            self.assertEqual(self.cards(), expected)

    def test_keep_and_invalid_choice_do_not_change_cards(self):
        original = self.cards()
        for data, status in (
            ({"name": self.id()}, 302),
            ({"name": self.id(), "card_type": ""}, 302),
            ({"name": self.id(), "card_type": "invalid"}, 200),
        ):
            response = self.client.post(f"/decks/edit/{self.deck}", data=data)
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.cards(), original)


class ReviewApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        cls.client = app.test_client()

    def test_rejects_non_numeric_fields(self):
        response = self.client.post(
            "/study/api/review",
            json={"card_id": "bad", "rating": 3, "request_id": "request-1"},
        )
        self.assertEqual(response.status_code, 400)

    def test_passes_idempotency_key_to_review_service(self):
        with patch(
            "app.db.submit_card_review", return_value="2026-09-07T00:00:00+00:00"
        ) as submit:
            response = self.client.post(
                "/study/api/review",
                json={"card_id": 1, "rating": 3, "request_id": "request-1"},
            )
        self.assertEqual(response.status_code, 200)
        submit.assert_called_once_with(1, 3, "request-1")


if __name__ == "__main__":
    unittest.main()
