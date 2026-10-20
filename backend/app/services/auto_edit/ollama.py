"""The local Auto Edit planner: an Ollama-compatible model chooses creator-level options.

The endpoint (``OLLAMA_BASE_URL``) and model (``AUTO_EDIT_OLLAMA_MODEL``, default the first
``OLLAMA_CLIP_MODELS`` entry) are operator configuration; a request never carries either. The
model sees only ``AutoEditContext.planner_view()`` — facts and symbolic handles, never ids —
and must answer the ``AutoEditProposal`` JSON schema (Ollama ``format``), at temperature 0.

The model is asked to act as an editor, not a marketer: choose what improves *this* clip, keep
speech clear, add nothing that is not useful, never invent assets or facts.

Bounded: one request, plus **one** corrective request when the reply is not valid JSON of the
right shape — and only while the overall time budget (``AUTO_EDIT_TIMEOUT_SECONDS``) allows.
Anything else (unreachable, timed out, still malformed) raises a ``PlannerError`` so the
deterministic planner can stand in. Semantic problems (an unknown handle, a preset outside the
recipe) are not re-prompted: the plan validator handles them. No model is pulled or loaded here.
"""

import json
import logging
import time
from typing import Any

import httpx

from app.core.config import Settings
from app.services.auto_edit.contract import (
    AutoEditContext,
    PlannerError,
    PlannerOutputError,
    PlannerResult,
    PlannerTimeoutError,
    PlannerUnavailableError,
    parse_proposal,
    proposal_json_schema,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # the first answer and one corrective attempt
MIN_RETRY_SECONDS = 5.0  # not worth a corrective attempt with less time left

SYSTEM_PROMPT = """You are an experienced short-form video editor. You plan the edit of ONE \
vertical short (a person talking) using only the options listed in the input. Ask yourself: \
which choices make THIS clip clearer and more watchable? Do not add effects everywhere.

Rules:
- Keep speech clear and easy to follow. The speaker's voice always comes first.
- Use only the options in "recipe" and "available". Never use an option marked unavailable.
- layout: prefer smart_reframe when it is available (it follows the speaker's face); \
otherwise blur_background (keeps the whole frame) or center_crop.
- captions: word-synced captions read best; pick a preset and position from the recipe.
- hook: optional. A short opening line (max 60 characters) built from the speaker's own words \
or the candidate hook. Never invent facts, numbers, names or claims that were not said. Do \
not repeat the clip's first sentence word for word. Turn it off if nothing fits.
- visuals: only a listed broll suggestion together with one of ITS matching_assets. Never \
invent handles. Add a visual only when it clearly helps the line it covers; none is fine.
- audio: use_music only if a music handle is available, kept low under the voice. \
transition_sounds only if the recipe allows them and transition sounds are available.
- explanations: one short sentence per section for the creator (what you chose and why). \
No internal reasoning.
Return only the JSON object."""

CORRECTION = (
    "Your previous answer was not a valid JSON object matching the required schema. "
    "Answer again with ONLY the JSON object, using exactly the allowed values and handles."
)


def constraints(context: AutoEditContext) -> list[str]:
    """What this clip allows, stated plainly (small models follow sentences better than they
    infer availability from data). Every rule is still enforced by the server."""
    caps = context.capabilities
    recipe = context.recipe
    rules: list[str] = []
    allowed = recipe.get("smart_reframe_confidence") or []
    if not caps.smart_reframe or caps.reframe_confidence not in allowed:
        rules.append("Smart Reframe is NOT available: use blur_background or center_crop.")
    else:
        rules.append("Smart Reframe is available: prefer it.")
    rules.append(
        f"captions.preset must be one of {recipe.get('caption_presets')}; captions.position "
        f"one of {recipe.get('caption_positions')}; hook.style one of "
        f"{recipe.get('hook_styles')}."
    )
    pairs = [
        f"{option.handle} with {', '.join(option.matches)}"
        for option in context.broll
        if option.matches
    ]
    if not pairs:
        rules.append("No B-roll suggestion has a matching asset: visuals must be [].")
    else:
        rules.append(
            f"Visuals may only use these pairs: {'; '.join(pairs)}. Never invent other handles."
        )
    if context.music is None or not recipe.get("music_levels"):
        rules.append("No music track was chosen: use_music must be false.")
    sounds = [s for s in context.sound_effects if s.transition]
    if not sounds or not recipe.get("sound_effects_allowed"):
        rules.append("Transition sounds are not available: transition_sounds must be false.")
    rules.append(
        "hook.text: at most 60 characters, from the speaker's words or the candidate hook."
    )
    return rules


def user_prompt(context: AutoEditContext) -> str:
    return (
        "Plan the edit for this clip.\nConstraints for this clip:\n- "
        + "\n- ".join(constraints(context))
        + "\nInput:\n"
        + json.dumps(context.planner_view(), ensure_ascii=False, separators=(",", ":"))
    )


class OllamaAutoEditPlanner:
    name = "ollama"

    def __init__(self, settings: Settings, model: str, *, client: httpx.Client | None = None):
        self.model = model
        self._num_ctx = settings.ollama_num_ctx
        self._budget = settings.auto_edit_timeout_seconds
        self._connect = settings.ollama_connect_timeout_seconds
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._injected = client  # tests inject a client; otherwise one per plan, always closed

    def plan(self, context: AutoEditContext) -> PlannerResult:
        client = self._injected or httpx.Client(base_url=self._base_url)
        try:
            return self._plan(context, client)
        finally:
            if self._injected is None:
                client.close()

    def _plan(self, context: AutoEditContext, client: httpx.Client) -> PlannerResult:
        deadline = time.monotonic() + self._budget
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(context)},
        ]
        last: PlannerOutputError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if attempt > 1 and remaining < MIN_RETRY_SECONDS:
                break
            content = self._chat(client, messages, timeout=max(remaining, 1.0))
            try:
                data = json.loads(content)
            except (TypeError, ValueError):
                last = PlannerOutputError("The model did not return valid JSON")
            else:
                try:
                    proposal = parse_proposal(data, provider="The local model")
                except PlannerOutputError as error:
                    last = error
                else:
                    return PlannerResult(proposal, self.name, self.model, attempts=attempt)
            logger.info("Auto Edit planner answer %d was malformed; correcting once", attempt)
            messages += [
                {"role": "assistant", "content": str(content)[:4000]},
                {"role": "user", "content": CORRECTION},
            ]
        raise last or PlannerTimeoutError("The local model ran out of planning time")

    def _chat(self, client: httpx.Client, messages: list[dict[str, str]], *, timeout: float) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": proposal_json_schema(),
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        limits = httpx.Timeout(timeout, connect=min(self._connect, timeout))
        try:
            response = client.post("/api/chat", json=payload, timeout=limits)
        except httpx.ConnectError as error:
            raise PlannerUnavailableError("The local inference server is not reachable") from error
        except httpx.TimeoutException as error:
            raise PlannerTimeoutError(
                "The local inference server did not answer in time"
            ) from error
        except httpx.HTTPError as error:
            raise PlannerUnavailableError("Could not talk to the local inference server") from error
        if response.status_code == 404:
            raise PlannerUnavailableError(
                "The configured local model is not installed", code="model_not_installed"
            )
        if response.status_code >= 500:
            raise PlannerUnavailableError(
                f"The local inference server failed (HTTP {response.status_code})",
                code="planner_server_error",
            )
        if response.status_code >= 400:
            raise PlannerError(
                "planner_request_rejected",
                f"The local inference server rejected the request (HTTP {response.status_code})",
            )
        try:
            body = response.json()
            content = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise PlannerOutputError(
                "The local inference server returned an unexpected response"
            ) from error
        if body.get("done_reason") == "length":
            return ""  # cut off: treated as malformed (one corrective attempt)
        return content
