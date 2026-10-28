"""Creator-facing words for a moment's place in its run's ranking.

Grounded in the run's own rank and its 0–100 editorial score — the model's judgement of the
moment, never a prediction of views. The frontend (``lib/workspace-rules.ts`` ``momentLabel``),
the moment filters (``view=top``) and the Copilot all use this threshold.
"""

STRONG_MOMENT_SCORE = 75


def moment_label(rank: int, overall_score: int) -> str:
    if rank == 1:
        return "Top pick"
    if overall_score >= STRONG_MOMENT_SCORE:
        return "Strong moment"
    return "Worth reviewing"
