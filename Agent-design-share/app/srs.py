"""Review scheduling: SM-2 (Wozniak) and the fixed 1/3/7-day comparison policy.

UI ratings map to SM-2 quality: again=1, hard=3, good=4, easy=5.
`retire` removes a card from the active queue under either policy.
"""

from datetime import datetime, timedelta, timezone

QUALITY = {"again": 1, "hard": 3, "good": 4, "easy": 5}
FIXED_DAYS = {"again": 1, "hard": 1, "good": 3, "easy": 7}
FIXED_RETIRE_STREAK = 3  # fixed policy: 3 consecutive "easy" -> familiar, leaves the queue
RETIRED = "9999-12-31T00:00:00+00:00"


def schedule(card: dict, rating: str, now: datetime | None = None) -> dict:
    """Return the updated scheduling fields for `card` after `rating`."""
    now = now or datetime.now(timezone.utc)
    if rating == "retire":
        return {"status": "retired", "due_at": RETIRED}
    if rating not in QUALITY:
        raise ValueError(f"unknown rating {rating}")

    if card.get("policy") == "fixed":
        streak = card["streak"] + 1 if rating == "easy" else 0
        if streak >= FIXED_RETIRE_STREAK:
            return {"status": "retired", "due_at": RETIRED, "streak": streak}
        days = FIXED_DAYS[rating]
        return {"interval": days, "streak": streak, "due_at": (now + timedelta(days=days)).isoformat(timespec="microseconds")}

    q, ef, reps, interval = QUALITY[rating], card["ef"], card["reps"], card["interval"]
    if q < 3:  # SM-2 step 6: restart repetitions, E-Factor unchanged
        reps, interval = 0, 1
    else:
        interval = 1 if reps == 0 else 6 if reps == 1 else round(interval * ef)
        reps += 1
        ef = max(1.3, ef + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    return {"ef": round(ef, 3), "reps": reps, "interval": interval,
            "due_at": (now + timedelta(days=interval)).isoformat(timespec="microseconds")}
