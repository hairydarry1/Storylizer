"""M1: the manual adapter writes a prompt file and reads the pasted reply file."""

from __future__ import annotations

import threading
import time

import pytest

from pipeline.adapters.manual import ManualAdapter, ManualPending


def test_manual_writes_prompt_file_and_returns_the_reply(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 5, "poll_interval": 0.01})

    def user_pastes_answer():
        # Wait for the adapter to publish the exchange paths, then answer.
        for _ in range(500):
            if adapter.last_paths is not None:
                prompt_path, reply_path = adapter.last_paths
                if prompt_path.exists():
                    reply_path.write_text("The pasted reply.\n", encoding="utf-8")
                    return
            time.sleep(0.01)
        raise AssertionError("adapter never wrote a prompt file")

    thread = threading.Thread(target=user_pastes_answer)
    thread.start()
    try:
        answer = adapter.complete("Write chapter one.")
    finally:
        thread.join(timeout=5)

    assert answer == "The pasted reply."
    prompt_path, reply_path = adapter.last_paths
    assert prompt_path.name.endswith(".prompt.md")
    assert reply_path.name.endswith(".reply.md")
    assert "Write chapter one." in prompt_path.read_text(encoding="utf-8")


def test_manual_writes_the_system_prompt_into_the_prompt_file(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 0})

    with pytest.raises(ManualPending):
        adapter.complete("Draft a scene.", system="You are a novelist.")

    prompt_path, _ = adapter.last_paths
    text = prompt_path.read_text(encoding="utf-8")
    assert "You are a novelist." in text
    assert "Draft a scene." in text


def test_manual_timeout_raises_and_leaves_the_prompt_on_disk(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 0})

    with pytest.raises(ManualPending) as excinfo:
        adapter.complete("Scene card please.")

    pending = excinfo.value
    assert pending.prompt_path.exists()
    assert "Scene card please." in pending.prompt_path.read_text(encoding="utf-8")
    assert str(pending.reply_path) in str(pending)
    assert str(pending.prompt_path) in str(pending)


def test_manual_numbers_each_exchange(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 0})

    names = []
    for _ in range(2):
        with pytest.raises(ManualPending) as excinfo:
            adapter.complete("prompt")
        names.append(excinfo.value.prompt_path.name)

    assert names == ["0001.prompt.md", "0002.prompt.md"]
    assert sorted(p.name for p in tmp_path.glob("*.prompt.md")) == names


def test_manual_uses_a_custom_prefix(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 0, "prefix": "14-chapter_writer-"})

    with pytest.raises(ManualPending) as excinfo:
        adapter.complete("prompt")

    assert excinfo.value.prompt_path.name == "14-chapter_writer-0001.prompt.md"


def test_manual_accepts_an_existing_reply_without_waiting(tmp_path):
    adapter = ManualAdapter({"directory": str(tmp_path), "timeout": 30, "poll_interval": 1})
    adapter.directory.mkdir(parents=True, exist_ok=True)
    (tmp_path / "0001.reply.md").write_text("Already answered.\n", encoding="utf-8")

    assert adapter.complete("prompt") == "Already answered."
