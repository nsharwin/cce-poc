"""Tests for the production docker entrypoint helper."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parents[1] / "ops/docker/cce-entrypoint.py"


def _load_entrypoint_module():
    spec = importlib.util.spec_from_file_location("cce_entrypoint", ENTRYPOINT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_entrypoint_module()


def test_resolves_placeholders(tmp_path, mod):
    cfg = tmp_path / "jailer.json"
    cfg.write_text('{"home": "${HOME}"}\n', encoding="utf-8")
    env = {"CCE_JAILER_CONFIG": str(cfg), "HOME": "/var/lib/cce"}
    out = mod._resolve_jailer_config(env)
    assert out is not None
    assert "/var/lib/cce" in Path(out).read_text(encoding="utf-8")


def test_detects_unresolved_placeholders(tmp_path, mod):
    cfg = tmp_path / "jailer.json"
    cfg.write_text('{"x": "${NEVER_SET_VAR}"}\n', encoding="utf-8")
    env = {"CCE_JAILER_CONFIG": str(cfg)}
    with pytest.raises(RuntimeError, match="NEVER_SET_VAR"):
        mod._resolve_jailer_config(env)


def test_missing_file_returns_none(tmp_path, mod):
    env = {"CCE_JAILER_CONFIG": str(tmp_path / "nonexistent.json")}
    assert mod._resolve_jailer_config(env) is None


def test_resolves_unbraced_placeholders(tmp_path, mod):
    cfg = tmp_path / "jailer.json"
    cfg.write_text('{"home": "$HOME"}\n', encoding="utf-8")
    env = {"CCE_JAILER_CONFIG": str(cfg), "HOME": "/var/lib/cce"}
    out = mod._resolve_jailer_config(env)
    assert out is not None
    assert "/var/lib/cce" in Path(out).read_text(encoding="utf-8")


def test_detects_unresolved_unbraced_placeholders(tmp_path, mod):
    cfg = tmp_path / "jailer.json"
    cfg.write_text('{"x": "$NEVER_SET_VAR_42"}\n', encoding="utf-8")
    env = {"CCE_JAILER_CONFIG": str(cfg)}
    with pytest.raises(RuntimeError, match="NEVER_SET_VAR_42"):
        mod._resolve_jailer_config(env)


def test_correct_env_var_name_is_used(mod):
    """Regression guard: the entrypoint MUST read CCE_JAILER_CONFIG (not the
    historical typo CCE_JAOKER_CONFIG)."""
    src = ENTRYPOINT.read_text(encoding="utf-8")
    assert "CCE_JAILER_CONFIG" in src
    assert "CCE_JAOKER" not in src
    assert "CCE_JAIKER" not in src
    assert "_JAIKER_PATH" not in src
