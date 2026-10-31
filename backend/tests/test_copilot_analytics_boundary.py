"""The Copilot never shows its data's field names, and answers exact analytics questions itself.

Regression for the real-model acceptance failure on the analytics page: with one Short published,
no figures reported yet and too few comparable Shorts for patterns, ``llama3.2:3b`` answered
"What has worked best for me?" by quoting the context's keys (``with_figures``,
``comparable_shorts``, ``minimum_needed``). Two layers now prevent it:

- PeakSift answers "what has worked?" and "how are my Shorts doing?" itself, from the analytics
  facts, in plain words (``answers.patterns_answer`` / ``answers.figures_answer``);
- every model answer passes an output boundary that removes any sentence naming an internal term
  (``safety.drop_internal_terms``), learnt from the data itself rather than a list of words.
"""

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.models import PublishedContent, PublishJob, User
from app.services.copilot import safety
from app.services.copilot.answers import figures_answer, own_answer, patterns_answer
from app.services.copilot.context import CopilotContext
from app.services.performance.insights import ensure_insights
from app.services.performance.provenance import PROVENANCE_VERSION
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit
from tests.test_copilot_acceptance import ask, use

# The answer the real model gave, verbatim (review stack, 2026-10-30).
LEAKED = (
    "You have 1 published Short, 'I was 4 seconds ahead… then the lava', with no views or "
    "engaged views reported. The 'Speedrun Fails — Episode 7' project has a 'with_figures' state "
    "of false, indicating no figures are available yet. The 'Morning Mindset — Guest Interview' "
    "project has a 'comparable_shorts' state of 0, indicating no comparable shorts are available "
    "for analysis. The 'Campus Welcome Vlog' project has a 'minimum_needed' state of 10, "
    "indicating that 10 more projects are needed to establish a pattern."
)
INTERNAL = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b|\bnull\b|[{}]")

# The failing seeded state: one Short published, nothing reported yet, too few to compare.
FAILING_ANALYTICS = {
    "published_shorts": 1,
    "with_figures": 0,
    "total_views": None,
    "simulated_data": True,
    "recent": [
        {
            "handle": "published_1",
            "title": "I was 4 seconds ahead… then the lava",
            "published": "2026-10-30",
            "views": None,
            "engaged_views": None,
            "average_percent_viewed": None,
        }
    ],
    "note": "observed figures only; never a prediction; null means not reported",
    "patterns": {
        "state": "insufficient",
        "comparable_shorts": 0,
        "minimum_needed": 10,
        "observed": [],
    },
    "summary": "1 published Short",
}


def analytics_context(analytics: dict, page: str = "analytics") -> CopilotContext:
    view = {"analytics": analytics, "next_steps": [{"project": "Speedrun Fails — Episode 7"}]}
    return CopilotContext(page, None, view, {"published_1": None}, "Your workspace", [])


def test_peaksift_answers_what_has_worked_in_the_failing_state():
    context = analytics_context(FAILING_ANALYTICS)
    kind, text = own_answer(context, "What has worked best for me?", False)
    assert kind == "analytics"
    assert text == (
        "You've published 1 Short from PeakSift. YouTube hasn't reported figures for it yet. "
        "There isn't enough performance history yet to make a reliable comparison. PeakSift needs "
        "at least 10 published Shorts with a complete first week of analytics (0 so far) before "
        "it can identify a pattern. These figures are simulated, not real YouTube data."
    )
    assert not INTERNAL.search(text)
    # The same question in other words, and in French, gets the same answer.
    for question in (
        "What's working for me?",
        "Any patterns in my Shorts?",
        "Qu'est-ce qui a le mieux marché ?",
    ):
        assert own_answer(context, question, False) == (kind, text)


def test_patterns_and_figures_answers_stay_observational():
    ready = {
        **FAILING_ANALYTICS,
        "with_figures": 1,
        "total_views": 1320,
        "simulated_data": False,
        "recent": [{**FAILING_ANALYTICS["recent"][0], "views": 1320, "engaged_views": 41,
                    "average_percent_viewed": 71.4}],
        "patterns": {"state": "ready", "comparable_shorts": 12, "minimum_needed": 10,
                     "observed": []},
    }  # fmt: skip
    text = patterns_answer(analytics_context(ready))
    assert "found no reliable pattern yet" in text and "1,320 views" in text
    found = {**ready, "patterns": {**ready["patterns"], "observed": [
        {"statement": "Shorts with an opening hook have tended to keep more viewers in your "
                      "recent uploads."}
    ]}}  # fmt: skip
    text = patterns_answer(analytics_context(found))
    assert text.startswith("Shorts with an opening hook have tended to keep more viewers")
    assert "associations, not causes, and never a prediction" in text
    figures = figures_answer(analytics_context(ready))
    assert figures == (
        "You've published 1 Short from PeakSift. “I was 4 seconds ahead… then the lava” "
        "(published Oct 30): 1,320 views, 41 engaged views, 71% viewed on average. These are "
        "observed figures, not predictions."
    )
    # Nothing reported: said plainly, never "1 view" read from the number of Shorts.
    nothing = figures_answer(analytics_context(FAILING_ANALYTICS))
    assert "YouTube hasn't reported its figures yet" in nothing and "1 view" not in nothing
    assert all(not INTERNAL.search(t) for t in (text, figures, nothing))


def test_the_boundary_removes_the_leaked_sentences_and_keeps_the_rest():
    context = analytics_context(FAILING_ANALYTICS)
    words = safety.vocabulary(context.view, context.targets)
    shown = safety.drop_internal_terms(LEAKED, words)
    assert shown == (
        "You have 1 published Short, 'I was 4 seconds ahead… then the lava', with no views or "
        "engaged views reported."
    )
    assert not INTERNAL.search(shown)


def test_the_boundary_learns_internal_terms_from_the_data():
    view = {
        "analytics": FAILING_ANALYTICS,
        "visual_library": {"items": [{"name": "bridge_photo.jpg", "used": "used in 1 version"}]},
    }
    words = safety.vocabulary(view, {"published_1", "moment_2"})
    assert safety.drop_internal_terms("Your engaged_views are low.", words) == ""  # any key
    assert safety.drop_internal_terms("See published_1 for details.", words) == ""  # a handle
    assert safety.drop_internal_terms("It has a retention_bucket of 3.", words) == ""  # unknown id
    assert safety.drop_internal_terms('The data says {"views": 3}.', words) == ""  # JSON
    assert safety.drop_internal_terms("Its average percent viewed is null.", words) == ""
    assert safety.drop_internal_terms("Its 'state' is insufficient.", words) == ""  # a quoted key
    kept = "Your visual “bridge_photo.jpg” shows the bridge. Views are observed, not predicted."
    assert safety.drop_internal_terms(kept, words) == kept  # the creator's own file name stays


def _publish(db_session, email: str) -> None:
    """One Short published from PeakSift, with nothing reported yet (the failing state)."""
    data = ready_clip(db_session, email)
    user = db_session.scalars(select(User).where(User.email == email)).one()
    edit = make_edit(db_session, data["clip"], status="ready",
                     storage_key=f"edits/{uuid.uuid4()}.mp4", file_size=10,
                     duration_seconds=15.0)  # fmt: skip
    db_session.add(PublishJob(
        user_id=user.id, edit_id=edit.id, provider="youtube",
        title="I was 4 seconds ahead… then the lava",
        privacy="private", category_id="22", fingerprint="9" * 64, status="published",
        provider_video_id="fakevid0001", completed_at=datetime.now(UTC),
    ))  # fmt: skip
    db_session.add(PublishedContent(
        user_id=user.id, project_id=data["clip"].video.project_id, provider="youtube",
        remote_video_id="fakevid0001", title="I was 4 seconds ahead… then the lava",
        published_at=datetime.now(UTC), provenance={}, provenance_version=PROVENANCE_VERSION,
    ))  # fmt: skip
    db_session.commit()
    source = "fake" if get_settings().performance_provider == "fake" else "youtube"
    insights = ensure_insights(db_session, user.id, source)
    db_session.commit()
    assert insights.status == "insufficient" and insights.sample_size == 0


def test_the_failing_seeded_state_through_the_api(client, db_session, monkeypatch):
    sign_up(client, "lava@example.com")
    _publish(db_session, "lava@example.com")
    # A model reply that leaks, for a question the model does answer.
    fake = use(monkeypatch, {"message": LEAKED})

    worked = ask(client, "What has worked best for me?", page="analytics")["content"]
    assert "There isn't enough performance history yet to make a reliable comparison." in worked
    assert "PeakSift needs at least 10 published Shorts" in worked
    doing = ask(client, "How are my Shorts doing?", page="analytics")["content"]
    assert "YouTube hasn't reported its figures yet" in doing
    assert not fake.calls  # both answered by PeakSift, from the data

    other = ask(client, "Is it worth posting on weekends?", page="analytics")["content"]
    assert fake.calls  # this one went to the model…
    assert other == (  # …and only its plain sentence is shown
        "You have 1 published Short, 'I was 4 seconds ahead… then the lava', with no views or "
        "engaged views reported."
    )
    for text in (worked, doing, other):
        assert not INTERNAL.search(text)
