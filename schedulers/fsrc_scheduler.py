# schedulers/fsrc_scheduler.py
from __future__ import annotations
from fsrs import Scheduler, Card, Rating, State
from domain.models import CardState, ScheduledReview
from datetime import datetime, timezone, timedelta


class FsrcSchedulerImpl:
    def __init__(self):
        self._parameters: tuple[float, ...] | None = None

    def review(
        self,
        card: CardState,
        rating: int,
        now: datetime,
        retention: float,
        exam_cutoff: datetime | None = None,
    ) -> ScheduledReview:
        if rating not in (1, 2, 3, 4):
            raise ValueError("rating must be 1..4")

        fsrs_card = Card()
        fsrs_card.state = State(card.state) if card.reps > 0 else State.Learning
        fsrs_card.step = card.step
        fsrs_card.stability = card.stability
        fsrs_card.difficulty = card.difficulty
        fsrs_card.last_review = card.last_review
        fsrs_card.due = card.due

        s = (
            Scheduler(parameters=self._parameters, desired_retention=retention)
            if self._parameters
            else Scheduler(desired_retention=retention)
        )
        new_card, review_log = s.review_card(fsrs_card, Rating(rating), now)

        adjusted_due = new_card.due
        if adjusted_due.tzinfo is None:
            adjusted_due = adjusted_due.replace(tzinfo=timezone.utc)
        else:
            adjusted_due = adjusted_due.astimezone(timezone.utc)

        if exam_cutoff and adjusted_due >= exam_cutoff:
            capped_due = exam_cutoff - timedelta(days=1)
            if capped_due >= now:
                adjusted_due = capped_due

        return ScheduledReview(
            next_review=adjusted_due,
            state=new_card.state.value,
            step=new_card.step,
            stability=new_card.stability,
            difficulty=new_card.difficulty,
            last_review=new_card.last_review,
        )

    def get_parameters(self) -> tuple[float, ...] | None:
        return self._parameters

    def set_parameters(self, weights: tuple[float, ...]) -> None:
        if len(weights) != 21:
            raise ValueError("FSRS parameters must be 21 floats")
        # Let the installed FSRS version enforce its parameter bounds now,
        # before a bad setting can make every review request fail.
        Scheduler(parameters=weights)
        self._parameters = weights
