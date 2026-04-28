"""Unit tests for the memento asset tool.

The tool exposes two LangChain @tool functions: store and recall. These
tests use a fake Vessel set on the ContextVar to drive employee context,
and patch MemoryV4Adapter to avoid real LLM calls.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from onemancompany.core.vessel import _current_vessel


@pytest.fixture
def fake_vessel():
    return SimpleNamespace(employee_id="E00006")


@pytest.fixture
def employee_root(tmp_path, monkeypatch):
    employees_dir = tmp_path / "employees"
    employees_dir.mkdir()
    (employees_dir / "E00006").mkdir()
    monkeypatch.setattr(
        "onemancompany.core.config.EMPLOYEES_DIR", employees_dir, raising=False
    )
    import company.assets.tools.memento.memento as memento_mod
    monkeypatch.setattr(memento_mod, "EMPLOYEES_DIR", employees_dir, raising=False)
    return employees_dir


@contextmanager
def _with_vessel(fake_vessel):
    token = _current_vessel.set(fake_vessel)
    try:
        yield
    finally:
        _current_vessel.reset(token)


def test_store_requires_employee_context(employee_root):
    from company.assets.tools.memento.memento import store

    result = store.invoke({"turns": [{"role": "user", "content": "hi"}]})

    assert result["status"] == "error"
    assert "employee context" in result["message"].lower()


def test_recall_requires_employee_context(employee_root):
    from company.assets.tools.memento.memento import recall

    result = recall.invoke({"query": "anything"})

    assert result["status"] == "error"
    assert "employee context" in result["message"].lower()
