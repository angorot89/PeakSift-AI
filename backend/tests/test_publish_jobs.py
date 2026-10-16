"""Publish jobs: a ready edit only, through a working connection, with metadata checked
against YouTube's rules (refused, never trimmed), private by default, never created twice."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import ConnectionStatus, Privacy, PublishJob, PublishStatus
from app.services.publishing.jobs import PublishRefused, request_publish
from app.services.publishing.metadata import (
    MetadataError,
    PublishMetadata,
    fingerprint,
    prefill,
    tags_length,
)
from tests.publishing_fixtures import connect, ready_edit


def meta(**overrides) -> PublishMetadata:
    return PublishMetadata.create(**{"title": "That was crazy", **overrides})


# --- metadata -----


def test_defaults_are_private_and_not_for_kids():
    metadata = meta()
    assert metadata.privacy == Privacy.PRIVATE and metadata.made_for_kids is False
    assert metadata.description == "" and metadata.tags == ()


def test_surrounding_whitespace_is_ignored_but_content_is_never_rewritten():
    metadata = meta(title="  Héllo — 🎬  wörld  ", description="\n Line one\nLine two \n")
    assert metadata.title == "Héllo — 🎬  wörld"  # inner spacing and characters kept
    assert metadata.description == "Line one\nLine two"


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"title": ""}, "title", "Add a title"),
        ({"title": "   "}, "title", "Add a title"),
        ({"title": "x" * 101}, "title", "101 characters; YouTube allows 100"),
        ({"title": "a <b> tag"}, "title", "< or >"),
        ({"title": "line\nbreak"}, "title", "control characters"),
        ({"description": "é" * 2501}, "description", "5002 bytes; YouTube allows 5000"),
        ({"description": "<script>"}, "description", "< or >"),
        ({"tags": ["ok", ""]}, "tags", "cannot be empty"),
        ({"tags": ["a,b"]}, "tags", "comma"),
        ({"tags": ["Same", "same"]}, "tags", "only once"),
        ({"tags": ["x" * 499, "y"]}, "tags", "total 501 characters"),
        ({"tags": [f"t{i}" for i in range(51)]}, "tags", "at most 50"),
        ({"privacy": "friends"}, "privacy", "private, unlisted or public"),
    ],
)
def test_metadata_breaking_youtube_rules_is_refused_not_trimmed(overrides, field, message):
    with pytest.raises(MetadataError) as excinfo:
        meta(**overrides)
    assert excinfo.value.field == field and message in excinfo.value.message


def test_limits_are_inclusive():
    assert len(meta(title="x" * 100).title) == 100
    assert len(meta(description="é" * 2500).description.encode()) == 5000
    assert tags_length(meta(tags=["x" * 498, "y"]).tags) == 500


def test_tags_are_counted_the_way_youtube_counts_them():
    assert tags_length(["one", "two words"]) == 3 + (9 + 2) + 1
    assert tags_length([]) == 0


def test_prefill_comes_from_the_candidate_without_ai():
    assert prefill("That Was Crazy!", "You won't believe\nwhat happened") == {
        "title": "That Was Crazy!",
        "description": "You won't believe\nwhat happened",
        "tags": [],
        "privacy": "private",
        "made_for_kids": False,
    }
    long = prefill("word " * 40, "<b>hook</b>")
    assert len(long["title"]) <= 100 and not long["title"].endswith(" ")
    assert long["description"] == "bhook/b"  # suggestions are made acceptable, then shown
    assert prefill(None, None)["title"] == "My short"
    PublishMetadata.create(**{k: v for k, v in long.items()})  # a prefill is always valid


def test_the_fingerprint_covers_connection_edit_metadata_and_privacy():
    connection, edit = uuid.uuid4(), uuid.uuid4()
    base = fingerprint(connection_id=connection, edit_id=edit, metadata=meta())
    assert base == fingerprint(connection_id=connection, edit_id=edit, metadata=meta())
    variants = [
        fingerprint(connection_id=uuid.uuid4(), edit_id=edit, metadata=meta()),
        fingerprint(connection_id=connection, edit_id=uuid.uuid4(), metadata=meta()),
        fingerprint(connection_id=connection, edit_id=edit, metadata=meta(title="Other")),
        fingerprint(connection_id=connection, edit_id=edit, metadata=meta(description="d")),
        fingerprint(connection_id=connection, edit_id=edit, metadata=meta(tags=["t"])),
        fingerprint(connection_id=connection, edit_id=edit, metadata=meta(privacy="public")),
        fingerprint(connection_id=connection, edit_id=edit, metadata=meta(made_for_kids=True)),
    ]
    assert len({base, *variants}) == 8


# --- creating jobs -----


def test_a_ready_edit_through_a_connection_becomes_a_queued_private_job(db_session: Session):
    user, edit = ready_edit(db_session)
    connection = connect(db_session, user)

    job, created = request_publish(
        db_session,
        user_id=user.id,
        edit=edit,
        connection=connection,
        metadata=meta(),
        task_id="task-1",
    )

    assert created and job.status == PublishStatus.QUEUED and job.progress_percent == 0
    assert job.privacy == "private" and job.title == "That was crazy"
    assert job.celery_task_id == "task-1" and job.connection_id == connection.id
    assert job.upload_session_ciphertext is None and job.provider_video_id is None


def test_the_same_request_returns_the_same_job(db_session: Session):
    user, edit = ready_edit(db_session)
    connection = connect(db_session, user)
    first, _ = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, metadata=meta(), task_id="t1"
    )
    again, created = request_publish(
        db_session, user_id=user.id, edit=edit, connection=connection, metadata=meta(), task_id="t2"
    )
    assert not created and again.id == first.id and again.celery_task_id == "t1"
    other, created = request_publish(
        db_session,
        user_id=user.id,
        edit=edit,
        connection=connection,
        metadata=meta(privacy="unlisted"),
        task_id="t3",
    )
    assert created and other.id != first.id


@pytest.mark.parametrize("status", ["queued", "rendering", "failed"])
def test_only_ready_edits_can_be_published(db_session: Session, status):
    user, edit = ready_edit(db_session, status=status)
    with pytest.raises(PublishRefused) as excinfo:
        request_publish(
            db_session,
            user_id=user.id,
            edit=edit,
            connection=connect(db_session, user),
            metadata=meta(),
            task_id="t",
        )
    assert excinfo.value.code == "edit_not_ready"


def test_publishing_needs_a_working_connection(db_session: Session):
    user, edit = ready_edit(db_session)
    with pytest.raises(PublishRefused) as excinfo:
        request_publish(
            db_session, user_id=user.id, edit=edit, connection=None, metadata=meta(), task_id="t"
        )
    assert excinfo.value.code == "not_connected"
    connection = connect(db_session, user)
    connection.status = ConnectionStatus.NEEDS_RECONNECT
    db_session.commit()
    with pytest.raises(PublishRefused) as excinfo:
        request_publish(
            db_session,
            user_id=user.id,
            edit=edit,
            connection=connection,
            metadata=meta(),
            task_id="t",
        )
    assert excinfo.value.code == "needs_reconnect"
    assert db_session.scalar(select(PublishJob)) is None


# --- database constraints -----


def job_row(db: Session, **overrides) -> PublishJob:
    user, edit = ready_edit(db)
    fields = dict(
        user_id=user.id,
        edit_id=edit.id,
        provider="youtube",
        title="t",
        description="",
        tags=[],
        privacy="private",
        made_for_kids=False,
        category_id="22",
        fingerprint="f" * 64,
        status="queued",
        progress_percent=0,
        attempt=1,
        bytes_uploaded=0,
    )
    fields.update(overrides)
    return PublishJob(**fields)


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider": "tiktok"},
        {"status": "done"},
        {"privacy": "friends"},
        {"title": ""},
        {"title": "x" * 101},
        {"description": "é" * 2501},
        {"tags": {"not": "a list"}},
        {"progress_percent": 101},
        {"attempt": 0},
        {"bytes_total": 10, "bytes_uploaded": 11},
        {"status": "published"},  # without a provider video id
        {"fingerprint": "short"},
    ],
)
def test_the_database_backs_every_rule(db_session: Session, overrides):
    db_session.add(job_row(db_session, **overrides))
    with pytest.raises((IntegrityError, DataError)):
        db_session.commit()
    db_session.rollback()


def test_a_youtube_video_belongs_to_one_job(db_session: Session):
    db_session.add(
        job_row(db_session, status="uploaded", provider_video_id="abc123", fingerprint="a" * 64)
    )
    db_session.commit()
    db_session.add(
        job_row(db_session, status="uploaded", provider_video_id="abc123", fingerprint="b" * 64)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_the_repr_reveals_no_metadata_or_session(db_session: Session):
    row = job_row(db_session, title="Secret title", upload_session_ciphertext=b"x" * 40)
    assert "Secret" not in repr(row) and "x" * 5 not in repr(row)
