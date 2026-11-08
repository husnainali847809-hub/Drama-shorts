import os
import unittest
from unittest.mock import patch

from mixed_content.main import choose_category, SCHEDULES, LABELS


class MixedContentScheduleTests(unittest.TestCase):
    def test_each_existing_pakistan_schedule_has_one_category(self):
        self.assertEqual(len(SCHEDULES), 5)
        self.assertEqual(set(SCHEDULES.values()), set(LABELS))

    def test_movie_explainer_slot(self):
        with patch.dict(os.environ, {"MIXED_SLOT_CRON": "0 3 * * *"}):
            self.assertEqual(choose_category(), "movie_explainer")

    def test_anime_inspired_slot(self):
        with patch.dict(os.environ, {"MIXED_SLOT_CRON": "0 6 * * *"}):
            self.assertEqual(choose_category(), "anime_style")

    def test_documentary_slot(self):
        with patch.dict(os.environ, {"MIXED_SLOT_CRON": "0 9 * * *"}):
            self.assertEqual(choose_category(), "documentary")

    def test_real_story_slot(self):
        with patch.dict(os.environ, {"MIXED_SLOT_CRON": "0 12 * * *"}):
            self.assertEqual(choose_category(), "real_story")

    def test_original_story_slot(self):
        with patch.dict(os.environ, {"MIXED_SLOT_CRON": "0 15 * * *"}):
            self.assertEqual(choose_category(), "original_story")


if __name__ == "__main__":
    unittest.main()
