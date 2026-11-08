"""Unit tests for mastery score formula and review scheduling rules."""

from app.services.mastery import compute_mastery
from app.services.review import needs_review, review_interval_days


class TestComputeMastery:
    def test_zero_practices(self):
        assert compute_mastery(0, 0, 0) == 0.0

    def test_all_wrong(self):
        assert compute_mastery(0, 3, 0) == 0.0

    def test_one_correct_first_try(self):
        assert compute_mastery(1, 1, 1) == 0.8

    def test_partial(self):
        assert compute_mastery(2, 3, 2) == 0.6

    def test_perfect_streak_capped_at_five(self):
        assert compute_mastery(5, 5, 5) == 1.0
        assert compute_mastery(10, 10, 7) == 1.0

    def test_wrong_answer_resets_streak(self):
        assert compute_mastery(3, 5, 0) == 0.45


class TestReviewIntervals:
    def test_interval_table(self):
        assert review_interval_days(0) == 1
        assert review_interval_days(1) == 3
        assert review_interval_days(2) == 7
        assert review_interval_days(3) == 14
        assert review_interval_days(4) == 30

    def test_interval_capped(self):
        assert review_interval_days(99) == 30


class TestNeedsReview:
    def test_too_few_practices_always_needs_review(self):
        assert needs_review(0, 0.0) is True
        assert needs_review(2, 0.9) is True

    def test_enough_practices_and_high_mastery_skips(self):
        assert needs_review(3, 0.9) is False

    def test_low_mastery_keeps_review(self):
        assert needs_review(5, 0.4) is True

    def test_threshold_boundary(self):
        assert needs_review(3, 0.6) is False
        assert needs_review(3, 0.59) is True
