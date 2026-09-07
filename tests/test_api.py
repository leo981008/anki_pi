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
