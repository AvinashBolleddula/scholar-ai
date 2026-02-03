import pytest
from context_manager import count_messages, build_context

def test_count_messages():
    messages = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    assert count_messages(messages) == 2

def test_count_messages_empty():
    assert count_messages([]) == 0

def test_build_context_no_summary():
    result = build_context("", [], "hello")
    assert len(result) == 1
    assert result[0]["content"] == "hello"

def test_build_context_with_summary():
    result = build_context("Previous chat about AI", [], "new question")
    assert len(result) == 3  # summary + ack + new query
    assert "Previous chat about AI" in result[0]["content"]

def test_build_context_with_recent_messages():
    recent = [{"role": "user", "content": "old"}, {"role": "assistant", "content": "response"}]
    result = build_context("", recent, "new")
    assert len(result) == 3  # recent + new query