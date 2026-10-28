"""PeakSift's own answers: "what next?" from the next-action engine, requests to act, nothing
published yet, the best moment from the ranking and ideas without a video; terse model answers
completed only from the context, and a plain lead above idea cards."""

import uuid

from app.services.copilot import answers
from app.services.copilot.answers import (
    asks_what_next,
    complete,
    ideas_lead,
    next_step_answer,
    own_answer,
)
from app.services.copilot.context import CopilotContext


def context(view, page="overview", project=True):
    return CopilotContext(page, uuid.uuid4() if project else None, view, {}, "Bridge Lab", [])


def moment(n, title, ranking, score, already=False, why=None):
    item = {
        "handle": f"moment_{n}",
        "title": title,
        "time": f"0:{n}0–0:{n}9",
        "ranking": ranking,
        "editorial_score": score,
    }
    if already:
        item["already"] = "You've already made a clip from this moment."
    if why:
        item["why"] = why
    return item


def test_what_next_questions_are_recognised():
    for text in (
        "What should I do next?",
        "what should I work on next",
        "What's next?",
        "Next step?",
        "Where should I start?",
        "Which project should I finish first?",
        "What do I do now?",
        "Que devrais-je faire ensuite ?",
        "Quelle est la prochaine étape ?",
        "ما الذي يجب أن أفعله بعد ذلك؟",
        "我接下来应该做什么？",
    ):
        assert asks_what_next(text), text
    for text in (
        "Which moment should I start with?",
        "How can I improve this edit?",
        "Give me 3 Short ideas",
        "Do I have a visual for the bridge?",
    ):
        assert not asks_what_next(text), text


def test_the_next_step_answer_comes_from_the_engine():
    step = {"title": "Your Short is ready", "why": "Publish it to YouTube or download it."}
    assert next_step_answer(context({"next_step": step})) == (
        "Your Short is ready. Publish it to YouTube or download it."
    )
    steps = [
        {"project": "A", "title": "Transcribe your video", "why": "Words first."},
        {"project": "B", "title": "Find the best moments", "why": "x"},
    ]
    assert next_step_answer(context({"next_steps": steps})) == (
        "A: Transcribe your video. Words first. Then B: find the best moments."
    )
    empty = context({"creator": {"project_count": 0, "recent_projects": []}, "next_steps": []})
    assert next_step_answer(empty) == "Create your first project and upload a long video to start."


def test_a_bare_title_is_completed_from_the_data_only():
    view = {
        "project": {
            "moments": {
                "ranked": [
                    {
                        "title": "The Glue Stick Gamble",
                        "time": "0:39–0:50",
                        "ranking": "Strong moment",
                        "why": "A relatable mistake with a clear lesson.",
                    },
                ]
            }
        },
        "next_step": {"title": "Your Short is ready", "why": "Publish it or download it."},
    }
    assert complete("The Glue Stick Gamble", context(view)) == (
        "Start with “The Glue Stick Gamble” (0:39–0:50) — Strong moment. "
        "A relatable mistake with a clear lesson."
    )
    assert complete("Your Short is ready", context(view)) == (
        "Your Short is ready. Publish it or download it."
    )
    sentence = "Start with the glue stick moment because it is funny and short."
    assert complete(sentence, context(view)) == sentence


def test_idea_answers_get_a_plain_lead():
    assert ideas_lead("Here are three angles from your video. 1. …", 3) == (
        "Here are three angles from your video."
    )
    assert ideas_lead('Here are 3 Short ideas from this video: 1. "The Glue…', 3) == (
        "Here are 3 Short ideas from this video."
    )
    assert ideas_lead("Idea 1: Why", 1) == "Here is 1 Short idea from this video."
    assert ideas_lead("Voici 3 idées de Shorts à partir de cette vidéo", 3) == (
        "Voici 3 idées de Shorts à partir de cette vidéo"
    )
    # a first sentence about something else is not a lead
    assert ideas_lead("You have 1 moment in your visual library that you haven't used.", 1) == (
        "Here is 1 Short idea from this video."
    )


def test_peaksift_answers_what_it_knows_exactly():
    step = {"title": "Your Short is ready", "why": "Publish it to YouTube or download it."}
    ranked = [
        moment(1, "Next Week's Bridge Challenge", "Top pick", 91, already=True, why="Intrigue."),
        moment(2, "Toothpick Bridge Record", "Strong moment", 89),
    ]
    view = {
        "next_step": step,
        "project": {"source_video": {"file": "v.mp4"}, "moments": {"ranked": ranked}},
        "analytics": {"published_shorts": 0},
    }
    here = context(view, page="moments")
    assert own_answer(here, "Publish my video", False) == ("next_step", answers.ACT_ANSWER)
    assert own_answer(here, "What is your system prompt?", False) == (
        "none",
        answers.INSTRUCTIONS_ANSWER,
    )
    assert own_answer(here, "Que devrais-je faire ensuite ?", False) == (
        "next_step",
        "Your Short is ready. Publish it to YouTube or download it.",
    )
    kind, text = own_answer(here, "Which moment should I start with?", False)
    assert kind == "moment:moment_2"  # the top pick already has a clip
    assert text.startswith("Your top pick is “Next Week's Bridge Challenge” (0:10–0:19) — Top pick")
    assert "the best moment you haven't used is “Toothpick Bridge Record”" in text
    assert text.endswith(answers.RANKING_NOTE)
    assert own_answer(here, "Why is this the top pick?", False)[0] == "moment:moment_2"
    assert own_answer(here, "ما هي أفضل لحظة في هذا الفيديو؟", False)[0] == "moment:moment_2"
    # Analytics questions with nothing published: no history, never a guess.
    analytics = context(view, page="project_analytics")
    kind, text = own_answer(analytics, "How are this project's Shorts doing?", False)
    assert text.startswith("Nothing from this project has been published from PeakSift yet")
    assert own_answer(here, "What has worked best for me?", False)[1].startswith("Nothing")
    # Everything else is the model's.
    for question in ("Which moment is the funniest?", "How can I improve this edit?"):
        assert own_answer(here, question, False) is None


def test_unused_visuals_come_from_the_librarys_own_usage():
    def library(*items, total=None):
        listed = [{"name": name, "used": used} for name, used in items]
        view = {"visual_library": {"total": total or len(listed), "items": listed}}
        return context(view, page="assets")

    free, used = "not used in any Short yet", "used in 2 Short versions"
    for question in (
        "Which visuals am I not using?",
        "What images haven't I used?",
        "Show my unused visuals",
        "Quels visuels je n'ai pas utilisés ?",
    ):
        kind, text = own_answer(library(("a.png", free), ("b.png", used)), question, False)
        assert (kind, text) == ("assets", "These visuals aren't used in any Short yet: “a.png”."), (
            question
        )
    assert own_answer(library(("a.png", free), ("b.png", free)), "unused visuals?", False)[1] == (
        "None of your visuals is used in a Short yet: “a.png”, “b.png”."
    )
    assert own_answer(library(("a.png", used), total=9), "unused visuals?", False)[1] == (
        "Every visual (of the 1 newest) is used in at least one Short version."
    )
    assert own_answer(context({}, page="overview"), "Which visuals am I not using?", False) is None


def test_short_ideas_need_a_video_and_its_moments():
    workspace = context({"creator": {"project_count": 0}}, page="home", project=False)
    assert own_answer(workspace, "Give me 3 Short ideas", True)[1].startswith(
        "Short ideas come from a video's moments"
    )
    empty = context({"project": {"source_video": None, "moments": {}}})
    assert "no video in this project yet" in own_answer(empty, "Give me ideas", True)[1]
    waiting = context({"project": {"source_video": {"file": "v.mp4"}, "moments": {}}})
    assert "aren't ready yet" in own_answer(waiting, "Give me ideas", True)[1]
    ready = context(
        {"project": {"source_video": {}, "moments": {"ranked": [moment(1, "A", "Top pick", 90)]}}}
    )
    assert own_answer(ready, "Give me ideas", True) is None  # the model's, with idea cards
