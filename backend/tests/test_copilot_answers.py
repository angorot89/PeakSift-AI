"""PeakSift's own answers: "what next?" from the next-action engine, terse model answers
completed only from the context, and a plain lead above idea cards."""

import uuid

from app.services.copilot.answers import asks_what_next, complete, ideas_lead, next_step_answer
from app.services.copilot.context import CopilotContext


def context(view):
    return CopilotContext("overview", uuid.uuid4(), view, {}, "Bridge Lab", [])


def test_what_next_questions_are_recognised():
    for text in (
        "What should I do next?",
        "what should I work on next",
        "What's next?",
        "Next step?",
        "Where should I start?",
        "Which project should I finish first?",
        "What do I do now?",
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
