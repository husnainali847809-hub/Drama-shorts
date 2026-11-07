import unittest

from sources.license_checker import license_is_allowed
from sources.movie_finder import (
    _plain_html,
    _release_year,
    has_film_metadata,
    looks_animated,
    looks_like_non_film_asset,
    looks_like_non_movie,
    looks_like_commons_promo,
    release_year_is_allowed,
)


class MovieSourceFilterTests(unittest.TestCase):
    def test_commercial_reuse_allowlist(self):
        self.assertTrue(license_is_allowed("https://creativecommons.org/licenses/by/4.0/"))
        self.assertTrue(license_is_allowed("https://creativecommons.org/publicdomain/zero/1.0/"))
        self.assertFalse(license_is_allowed("https://creativecommons.org/licenses/by-nc/4.0/"))
        self.assertFalse(license_is_allowed("https://creativecommons.org/licenses/by-sa/4.0/"))

    def test_animation_is_rejected(self):
        self.assertTrue(looks_animated({"description": "An animated short film"}))

    def test_non_film_asset_is_rejected(self):
        self.assertTrue(looks_like_non_film_asset({"title": "VHS Glitch - Volume 1"}))

    def test_tv_episode_is_rejected(self):
        self.assertTrue(looks_like_non_movie({"title": "Example Show S02E03"}))

    def test_commons_institutional_promo_is_rejected(self):
        self.assertTrue(looks_like_commons_promo({
            "title": "A short film about 20 years of work and existence of Wikimedia Serbia"
        }))

    def test_short_film_category_counts_as_film_metadata(self):
        self.assertTrue(has_film_metadata({"genre": "Short films"}))

    def test_old_film_year_is_allowed_but_unknown_year_is_not(self):
        self.assertTrue(release_year_is_allowed(1925))
        self.assertTrue(release_year_is_allowed(1890))
        self.assertFalse(release_year_is_allowed(1889))
        self.assertFalse(release_year_is_allowed(None))

    def test_release_year_can_be_read_from_title(self):
        self.assertEqual(_release_year({"title": "An Example Short Film (2015)"}), 2015)

    def test_commons_html_is_sanitized(self):
        self.assertEqual(_plain_html('<a href="https://example.org">Creator &amp; Co.</a>'), "Creator & Co.")


if __name__ == "__main__":
    unittest.main()
