import subprocess
import types
import uuid
from pathlib import Path

import pytest

from app.services.ffprobe import probe_audio
from app.services.storage import LocalMediaStorage
from app.services.transcription import chunking
from app.services.transcription.chunking import (
    ChunkingError,
    build_chunk_command,
    chunk_key,
    cleanup_chunks,
    plan_chunks,
    shift_segments,
    split_audio,
)
from app.services.transcription.contract import ProviderSegment
from tests.media_fixtures import FFMPEG, requires_ffmpeg

TID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def storage(tmp_path: Path) -> LocalMediaStorage:
    return LocalMediaStorage(tmp_path / "media")


@pytest.fixture
def source(storage: LocalMediaStorage) -> Path:
    path = storage.path_for(f"transcription/{TID}/normalized.mp3")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"fake mp3")
    return path


def files(storage: LocalMediaStorage) -> list[str]:
    return sorted(str(p.relative_to(storage.root)) for p in storage.root.rglob("*") if p.is_file())


# --- planning -----


def test_single_chunk_when_audio_is_shorter_than_chunk():
    assert plan_chunks(42.0, 600) == [chunking.ChunkPlan(0, 0.0, 42.0)]


def test_exact_multiple_gives_full_chunks():
    plans = plan_chunks(1800.0, 600)
    assert [(p.index, p.start_seconds, p.duration_seconds) for p in plans] == [
        (0, 0, 600),
        (1, 600, 600),
        (2, 1200, 600),
    ]


def test_final_partial_chunk():
    plans = plan_chunks(1450.0, 600)
    assert [(p.start_seconds, p.duration_seconds) for p in plans] == [
        (0, 600),
        (600, 600),
        (1200, 250),
    ]
    assert sum(p.duration_seconds for p in plans) == pytest.approx(1450.0)


def test_tiny_remainder_is_folded_into_previous_chunk():
    plans = plan_chunks(1200.4, 600)
    assert len(plans) == 2
    assert plans[-1].duration_seconds == pytest.approx(600.4)


def test_four_hour_stream_plan_is_contiguous():
    plans = plan_chunks(4 * 3600 + 17.0, 600)
    assert len(plans) == 25
    for previous, current in zip(plans, plans[1:], strict=False):
        assert current.start_seconds == pytest.approx(
            previous.start_seconds + previous.duration_seconds
        )
    assert plans[-1].duration_seconds == pytest.approx(17.0)


@pytest.mark.parametrize("total", [0, -5, None])
def test_invalid_duration_is_rejected(total):
    with pytest.raises(ChunkingError) as excinfo:
        plan_chunks(total, 600)
    assert excinfo.value.code == "invalid_duration"


def test_invalid_chunk_size_is_rejected():
    with pytest.raises(ChunkingError):
        plan_chunks(100, 0)


# --- keys and commands -----


def test_chunk_keys_are_internal_ordered_and_safe(storage: LocalMediaStorage):
    assert chunk_key(TID, 0) == f"transcription/{TID}/chunks/0000.mp3"
    assert chunk_key(TID, 1234) == f"transcription/{TID}/chunks/1234.mp3"
    assert storage.root in storage.path_for(chunk_key(TID, 7)).parents


def test_chunk_command_seeks_and_limits_duration(tmp_path: Path):
    command = build_chunk_command(
        "/opt/ffmpeg", tmp_path / "n.mp3", tmp_path / "c.part", 600, 250.5
    )

    assert command[0] == "/opt/ffmpeg"
    assert command[command.index("-ss") + 1] == "600.000"
    assert command.index("-ss") < command.index("-i")  # input seeking on the CBR file
    assert command[command.index("-t") + 1] == "250.500"
    assert command[command.index("-f") + 1] == "mp3"
    assert command[-1] == str(tmp_path / "c.part")


# --- splitting (mocked ffmpeg) -----


def fake_run_writing(payload: bytes = b"chunkdata"):
    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(payload)
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    return fake_run


def test_split_writes_ordered_chunks_with_absolute_starts(monkeypatch, storage, source):
    monkeypatch.setattr(chunking.subprocess, "run", fake_run_writing())
    monkeypatch.setattr(
        chunking, "probe_audio", lambda *a, **k: types.SimpleNamespace(duration_seconds=None)
    )

    chunks = split_audio(source, storage, TID, total_seconds=1450, chunk_seconds=600)

    assert [(c.index, c.start_seconds, c.duration_seconds) for c in chunks] == [
        (0, 0, 600),
        (1, 600, 600),
        (2, 1200, 250),
    ]
    assert [c.storage_key for c in chunks] == [chunk_key(TID, i) for i in range(3)]
    assert files(storage) == [
        f"transcription/{TID}/chunks/0000.mp3",
        f"transcription/{TID}/chunks/0001.mp3",
        f"transcription/{TID}/chunks/0002.mp3",
        f"transcription/{TID}/normalized.mp3",
    ]


def test_split_uses_probed_duration_when_available(monkeypatch, storage, source):
    monkeypatch.setattr(chunking.subprocess, "run", fake_run_writing())
    monkeypatch.setattr(
        chunking, "probe_audio", lambda *a, **k: types.SimpleNamespace(duration_seconds=599.97)
    )

    chunks = split_audio(source, storage, TID, total_seconds=600, chunk_seconds=600)

    assert chunks[0].duration_seconds == 599.97


def test_split_failure_removes_every_chunk(monkeypatch, storage, source):
    calls = {"n": 0}

    def flaky_run(command, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            return types.SimpleNamespace(returncode=1, stdout=b"", stderr=b"/private/boom")
        Path(command[-1]).write_bytes(b"chunk")
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(chunking.subprocess, "run", flaky_run)
    monkeypatch.setattr(
        chunking, "probe_audio", lambda *a, **k: types.SimpleNamespace(duration_seconds=None)
    )

    with pytest.raises(ChunkingError) as excinfo:
        split_audio(source, storage, TID, total_seconds=1800, chunk_seconds=600)

    assert excinfo.value.code == "chunk_failed" and "/private" not in excinfo.value.message
    assert files(storage) == [f"transcription/{TID}/normalized.mp3"]


def test_split_timeout_cleans_up(monkeypatch, storage, source):
    def slow_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"half")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(chunking.subprocess, "run", slow_run)

    with pytest.raises(ChunkingError) as excinfo:
        split_audio(source, storage, TID, total_seconds=100, chunk_seconds=60, timeout_seconds=1)

    assert excinfo.value.code == "ffmpeg_timeout"
    assert files(storage) == [f"transcription/{TID}/normalized.mp3"]


def test_split_missing_source(storage):
    with pytest.raises(ChunkingError) as excinfo:
        split_audio(storage.root / "nope.mp3", storage, TID, total_seconds=10, chunk_seconds=5)
    assert excinfo.value.code == "source_missing"


def test_cleanup_removes_chunks_but_keeps_normalized_audio(monkeypatch, storage, source):
    monkeypatch.setattr(chunking.subprocess, "run", fake_run_writing())
    monkeypatch.setattr(
        chunking, "probe_audio", lambda *a, **k: types.SimpleNamespace(duration_seconds=None)
    )
    split_audio(source, storage, TID, total_seconds=1200, chunk_seconds=600)

    cleanup_chunks(storage, TID)
    cleanup_chunks(storage, TID)  # idempotent

    assert files(storage) == [f"transcription/{TID}/normalized.mp3"]


# --- absolute timestamps -----


def test_shift_segments_into_absolute_time():
    shifted = shift_segments(
        [ProviderSegment(12.4, 18.9, "hello", speaker=None), ProviderSegment(18.9, 25.0, "world")],
        600,
    )

    assert [(s.start, s.end, s.text) for s in shifted] == [
        (612.4, 618.9, "hello"),
        (618.9, 625.0, "world"),
    ]


def test_shift_zero_offset_is_identity_and_rounds_floats():
    shifted = shift_segments([ProviderSegment(0.1 + 0.2, 1.0, "x")], 0)
    assert shifted[0].start == 0.3


def test_shift_rejects_negative_offset():
    with pytest.raises(ChunkingError):
        shift_segments([ProviderSegment(0, 1, "x")], -1)


def test_shift_across_three_hours():
    shifted = shift_segments([ProviderSegment(5.5, 9.25, "late")], 3 * 3600 + 600)
    assert (shifted[0].start, shifted[0].end) == (11405.5, 11409.25)


# --- real ffmpeg -----


@requires_ffmpeg
def test_real_split_of_generated_audio(storage: LocalMediaStorage, tmp_path: Path):
    source = storage.path_for(f"transcription/{TID}/normalized.mp3")
    source.parent.mkdir(parents=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=7",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            "-codec:a",
            "libmp3lame",
            str(source),
        ],
        check=True,
    )
    total = probe_audio(source).duration_seconds

    chunks = split_audio(source, storage, TID, total_seconds=total, chunk_seconds=3)

    assert [c.index for c in chunks] == [0, 1, 2]
    assert [c.start_seconds for c in chunks] == [0, 3, 6]
    for chunk, expected in zip(chunks, [3.0, 3.0, total - 6], strict=True):
        info = probe_audio(storage.path_for(chunk.storage_key))
        assert info.duration_seconds == pytest.approx(expected, abs=0.15)
        assert info.sample_rate == 16000 and info.channels == 1
        assert chunk.duration_seconds == pytest.approx(expected, abs=0.15)
    assert sum(c.duration_seconds for c in chunks) == pytest.approx(total, abs=0.3)

    cleanup_chunks(storage, TID)
    assert files(storage) == [f"transcription/{TID}/normalized.mp3"]


@requires_ffmpeg
def test_real_short_source_is_a_single_chunk(storage: LocalMediaStorage):
    source = storage.path_for(f"transcription/{TID}/normalized.mp3")
    source.parent.mkdir(parents=True)
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            "-codec:a",
            "libmp3lame",
            str(source),
        ],
        check=True,
    )

    chunks = split_audio(source, storage, TID, total_seconds=2.0, chunk_seconds=600)

    assert len(chunks) == 1 and chunks[0].start_seconds == 0
    assert chunks[0].duration_seconds == pytest.approx(2.0, abs=0.15)


# --- per-attempt workspaces ----------------------------------------------------------------


def test_attempt_workspaces_are_distinct_and_safe():
    from app.services.transcription.chunking import attempt_workspace

    tid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    first = attempt_workspace(tid, "0f8e6c2a-1111-4222-8333-944455556666")
    second = attempt_workspace(tid, "aa11bb22-1111-4222-8333-944455556666")
    assert first != second and first.startswith(f"{tid}/")
    assert attempt_workspace(tid, None) == f"{tid}/inline"
    assert attempt_workspace(tid, "../../etc") == f"{tid}/etc"  # only alphanumerics survive
    with pytest.raises(ValueError):
        attempt_workspace("not-a-uuid", "x")


def test_cleaning_one_workspace_never_touches_another(storage: LocalMediaStorage):
    from app.services.transcription.chunking import (
        attempt_workspace,
        chunk_key,
        cleanup_other_workspaces,
    )

    tid = uuid.uuid4()
    old, new = attempt_workspace(tid, "taskone"), attempt_workspace(tid, "tasktwo")
    for workspace in (old, new):
        path = storage.path_for(chunk_key(workspace, 0))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    cleanup_chunks(storage, old)  # the stale worker cleans up after itself
    assert not storage.path_for(chunk_key(old, 0)).exists()
    assert storage.path_for(chunk_key(new, 0)).exists()

    legacy = storage.path_for(f"transcription/{tid}/normalized.mp3")  # pre-V0.6 flat layout
    legacy.write_bytes(b"old")
    cleanup_other_workspaces(storage, tid, keep=new)  # the current attempt clears the rest
    assert storage.path_for(chunk_key(new, 0)).exists()
    assert not storage.path_for(f"transcription/{old}").exists() and not legacy.exists()
