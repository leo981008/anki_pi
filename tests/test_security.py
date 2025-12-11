import unittest
import json
import os
import sys

# Add parent directory to path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

class SecurityTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for testing APIs easily
        self.client = self.app.test_client()

    def test_tts_length_limit(self):
        """Test that /api/tts rejects input longer than 500 characters."""
        long_text = "a" * 501
        response = self.client.get(f'/api/tts?text={long_text}')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Text too long", response.data)

        # Verify normal input works (or at least doesn't return 400 for length)
        # Note: edge_tts might fail in test env if no internet/ffmpeg, but we check length validation first
        short_text = "Hello"
        response = self.client.get(f'/api/tts?text={short_text}')
        # We expect either 200 or 500 (if TTS fails), but NOT 400 "Text too long"
        self.assertNotEqual(response.status_code, 400)

    def test_make_sentence_length_limit(self):
        """Test that /api/make_sentence rejects input longer than 100 characters."""
        long_word = "a" * 101
        response = self.client.post('/api/make_sentence',
                                    data=json.dumps({'word': long_word}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Word too long", response.data)

        # Verify normal input passes the length check
        short_word = "Hello"
        # It might return 200 or 500 (if Ollama down), but not 400 due to length
        response = self.client.post('/api/make_sentence',
                                    data=json.dumps({'word': short_word}),
                                    content_type='application/json')
        if response.status_code == 400:
             # Only if it's "No word provided" or similar, but we provided it.
             # If it fails due to length, that's a bug in our test expectation.
             self.assertNotIn(b"Word too long", response.data)

if __name__ == '__main__':
    unittest.main()
