"""Unit tests for model_roles — role slots ≠ quality bands."""

from __future__ import annotations

import model_roles as mr


def test_defaults_are_cheap_flash_lite(monkeypatch):
    for k in (
        "PLANNER_MODEL",
        "MID_TIER_MODEL",
        "SQUAD_MODEL",
        "FAST_MODEL",
        "ASK_MODEL",
        "BATTALION_MODEL",
        "HEAVY_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)
    assert mr.planner_model() == mr.DEFAULT_CHEAP_MODEL
    assert mr.squad_model() == mr.DEFAULT_CHEAP_MODEL
    assert mr.ask_model() == mr.DEFAULT_CHEAP_MODEL
    assert mr.battalion_model() == mr.ask_model()


def test_ask_env_beats_battalion_alias(monkeypatch):
    monkeypatch.setenv("ASK_MODEL", "pref/ask")
    monkeypatch.setenv("BATTALION_MODEL", "legacy/battalion")
    assert mr.ask_model() == "pref/ask"
    assert mr.battalion_model() == "pref/ask"


def test_preferred_env_beats_legacy(monkeypatch):
    monkeypatch.setenv("PLANNER_MODEL", "pref/planner")
    monkeypatch.setenv("MID_TIER_MODEL", "legacy/mid")
    assert mr.planner_model() == "pref/planner"


def test_legacy_env_still_works(monkeypatch):
    monkeypatch.delenv("PLANNER_MODEL", raising=False)
    monkeypatch.setenv("MID_TIER_MODEL", "legacy/mid")
    assert mr.planner_model() == "legacy/mid"
