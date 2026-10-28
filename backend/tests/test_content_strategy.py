"""Content strategy (V1.6): notes from the creator's own data only, cautious about small
samples, aware of repeated work; Short ideas only from real moments or transcript times."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.models import (
    ClipCandidate,
    CreatorInsight,
    InsightSet,
    PublishedContent,
    User,
)
from app.services.copilot import service
from app.services.copilot.context import build_context
from app.services.copilot.ideas import asks_for_ideas, check_ideas
from app.services.copilot.provider import CopilotProviderError, FakeCopilotProvider
from app.services.performance.provenance import PROVENANCE_VERSION
from app.services.strategy import project_strategy
from tests.test_clip_edit_api import ready_clip, sign_up
from tests.test_clip_edit_model import make_edit


def me(db, email):
    return db.scalar(select(User).where(User.email == email))


def moment(db, run, video_id, rank, title, category, score=80, start=40.0):
    candidate = ClipCandidate(
        run=run,
        video_id=video_id,
        start_time=start,
        end_time=start + 15,
        duration_seconds=15.0,
        title=title,
        hook="h",
        rationale=f"Why {title}",
        category=category,
        transcript_excerpt="x",
        overall_score=score,
        hook_score=score,
        entertainment_score=score,
        clarity_score=score,
        payoff_score=score,
        completeness_score=score,
        rank=rank,
    )
    db.add(candidate)
    db.flush()
    return candidate


def publish(db, user, project_id, category, edit_id=None, days=1):
    content = PublishedContent(
        user_id=user.id,
        project_id=project_id,
        provider="youtube",
        remote_video_id=uuid.uuid4().hex[:11],
        title=f"A {category} Short",
        published_at=datetime.now(UTC) - timedelta(days=days),
        edit_id=edit_id,
        provenance={"candidate": {"category": category}},
        provenance_version=PROVENANCE_VERSION,
    )
    db.add(content)
    db.flush()
    return content


def setup(client, db, email):
    sign_up(client, email)
    data = ready_clip(db, email)
    clip = data["clip"]
    run = clip.candidate.run
    moment(db, run, clip.video_id, 2, "The glue-stick incident", "humor", start=60.0)
    moment(db, run, clip.video_id, 3, "How load spreads", "explanation", score=60, start=90.0)
    db.commit()
    return me(db, email), clip


def test_a_fresh_project_gets_honest_notes(client, db_session):
    user, clip = setup(client, db_session, "fresh@example.com")
    strategy = project_strategy(db_session, clip.video.project, "youtube")
    assert strategy.notes[0] == (
        "You have 2 moments in this video you haven't used yet (explanation, funny)."
    )
    assert "haven't published from PeakSift yet" in strategy.notes[1]
    assert [m.note for m in strategy.moments] == [
        "You've already made a clip from this moment.",
        None,
        None,
    ]


def test_history_is_used_cautiously_and_never_as_a_prediction(client, db_session):
    user, clip = setup(client, db_session, "history@example.com")
    project_id = clip.video.project_id
    for n in range(3):
        publish(db_session, user, project_id, "insight", days=n + 1)
    db_session.add(
        InsightSet(
            user_id=user.id,
            source="youtube",
            engine_version="v1",
            input_fingerprint="f" * 64,
            status="insufficient",
            sample_size=3,
            computed_at=datetime.now(UTC),
        )
    )
    db_session.commit()
    notes = project_strategy(db_session, clip.video.project, "youtube").notes
    assert "You've published 3 insight Shorts recently." in notes[1]
    assert "“The glue-stick incident”" in notes[1]
    assert notes[2] == (
        "Your current sample isn't large enough to recommend a length, style or kind of "
        "moment yet (3 of 10 comparable Shorts)."
    )


def test_observed_patterns_are_relayed_with_their_own_wording(client, db_session):
    user, clip = setup(client, db_session, "pattern@example.com")
    insight_set = InsightSet(
        user_id=user.id,
        source="youtube",
        engine_version="v1",
        input_fingerprint="a" * 64,
        status="ready",
        sample_size=12,
        computed_at=datetime.now(UTC),
    )
    db_session.add(insight_set)
    db_session.flush()
    db_session.add(
        CreatorInsight(
            set_id=insight_set.id,
            key="length:under_20s",
            rank=1,
            feature="length",
            value="under_20s",
            metric="engaged_views",
            window="day_7",
            direction="higher",
            group_size=6,
            comparison_size=6,
            group_median=900,
            comparison_median=400,
            ratio=2.25,
            consistency=0.8,
            confidence="limited",
            statement="In your recent uploads, Shorts under 20 seconds have tended to get more "
            "engaged views in their first week.",
            evidence={"group": [], "comparison": []},
        )
    )
    publish(db_session, user, clip.video.project_id, "story")
    db_session.commit()
    notes = project_strategy(db_session, clip.video.project, "youtube").notes
    assert notes[-1].startswith("In your recent uploads, Shorts under 20 seconds have tended to")
    assert notes[-1].endswith("This is an observed pattern, not a prediction.")
    assert not [n for n in notes if "viral" in n.lower() or "will get" in n.lower()]


def test_repeated_work_is_marked_in_the_copilot_view(client, db_session):
    user, clip = setup(client, db_session, "repeat@example.com")
    edit = make_edit(
        db_session,
        clip,
        status="ready",
        storage_key=f"edits/{uuid.uuid4()}.mp4",
        file_size=10,
        duration_seconds=20.0,
    )
    publish(db_session, user, clip.video.project_id, "story", edit_id=edit.id)
    db_session.commit()
    context = build_context(
        db_session, user, get_settings(), page="moments", project_id=clip.video.project_id
    )
    ranked = context.view["project"]["moments"]["ranked"]
    assert ranked[0]["already"] == "Similar to a Short you've already published."
    assert "already" not in ranked[1]
    assert context.view["strategy"]["notes"][0].startswith("You have 2 moments")


def test_ideas_come_only_from_real_moments_or_transcript_times(client, db_session):
    user, clip = setup(client, db_session, "ideas@example.com")
    context = build_context(
        db_session, user, get_settings(), page="moments", project_id=clip.video.project_id
    )
    cards = check_ideas(
        [
            {
                "title": "The glue disaster",
                "moment": "moment_2",
                "angle": "Story",
                "why": "A funny failure.",
                "style": "punchy",
            },
            {"title": "Opening line", "from": "0:10", "to": "0:10", "why": "Too short"},  # empty
            {"title": "Hello", "from": "0:10", "to": "0:14", "why": "x"},  # 0:14 is not a line time
            {"title": "Invented", "moment": "moment_9", "why": "Not real"},
            {"title": "Made up", "from": "9:00", "to": "9:30", "why": "Not in the transcript"},
            {
                "title": "Odd style",
                "moment": "moment_3",
                "angle": "Prophecy",
                "why": "y",
                "style": "viral",
            },
            {"title": "Twice", "moment": "moment_2", "why": "duplicate time"},
        ],
        context,
    )
    assert [c.card["title"] for c in cards] == ["The glue disaster", "Odd style"]
    first, second = cards
    assert first.card["time"] == "1:00–1:15" and first.card["angle"] == "Story"
    assert first.card["style"] == "punchy" and first.action.type == "create_short"
    assert second.card["angle"] is None and second.card["style"] is None
    assert asks_for_ideas("Give me 3 Short ideas") and asks_for_ideas("Des idées ?")
    assert asks_for_ideas("أعطني أفكار") and not asks_for_ideas("What next?")


def test_idea_cards_reach_the_creator_with_create_short(client, db_session):
    user, clip = setup(client, db_session, "cards@example.com")
    fake = FakeCopilotProvider(
        [
            {
                "message": "Here are two ideas.",
                "actions": [],
                "references": [],
                "ideas": [
                    {
                        "title": "The glue disaster",
                        "moment": "moment_2",
                        "angle": "Story",
                        "why": "A funny failure.",
                        "style": "punchy",
                    }
                ],
            }
        ]
    )
    answer = service.ask(
        db_session,
        user,
        get_settings(),
        text="Give me ideas",
        page="overview",
        project_id=clip.video.project_id,
        provider=fake,
    ).answer
    body = client.get("/copilot/thread", params={"project_id": str(clip.video.project_id)}).json()
    [card] = body["messages"][-1]["cards"]
    assert card["title"] == "The glue disaster" and card["note"] is None
    action = body["messages"][-1]["actions"][card["action"]]
    assert action["label"] == "Create Short"
    resolved = client.post(f"/copilot/messages/{answer.id}/actions/{card['action']}").json()
    assert resolved["kind"] == "create_short"  # this moment has no clip yet


def test_without_the_assistant_peaksift_still_offers_ideas(client, db_session):
    user, clip = setup(client, db_session, "offline-ideas@example.com")
    answer = service.ask(
        db_session,
        user,
        get_settings(),
        text="Give me 3 Short ideas from this video",
        page="overview",
        project_id=clip.video.project_id,
        provider=FakeCopilotProvider([CopilotProviderError("unavailable", "down")]),
    ).answer
    assert answer.status == "unavailable"
    assert answer.content.endswith(service.IDEAS_FALLBACK)
    titles = [card["title"] for card in answer.cards]
    assert titles == ["The glue-stick incident", "How load spreads", "That Was Crazy!"]
    assert answer.cards[0]["angle"] == "Reaction" and answer.cards[0]["style"] == "punchy"
    assert answer.cards[2]["note"] == "You've already made a clip from this moment."


def test_an_idea_naming_a_moment_exactly_is_anchored_to_it(client, db_session):
    user, clip = setup(client, db_session, "anchor@example.com")
    fake = FakeCopilotProvider(
        [
            {
                "message": "Idea 1",
                "actions": [],
                "references": [],
                "ideas": [
                    {"title": "the Glue-Stick incident!", "why": "Funny.", "angle": "Story"},
                    {"title": "A glue story", "why": "Not a moment title."},
                ],
            }
        ]
    )
    answer = service.ask(
        db_session,
        user,
        get_settings(),
        text="Give me ideas",
        page="moments",
        project_id=clip.video.project_id,
        provider=fake,
    ).answer
    assert [c["time"] for c in answer.cards] == ["1:00–1:15"]
    assert answer.content == "Here is 1 Short idea from this video."
