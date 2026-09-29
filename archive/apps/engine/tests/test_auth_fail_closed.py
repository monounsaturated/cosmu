# Fail CLOSED: the API refuses to boot in production without API_SECRET_KEY, so a misconfigured deploy can
# never silently expose the money-moving control plane unauthenticated (the x-api-key middleware is a no-op
# when the key is unset). Scoped to the API lifespan — Modal cron / CLI build Settings without it.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cosmu.api._lifespan import _guard_production_auth


def test_guard_raises_in_production_without_key():
    with pytest.raises(RuntimeError):
        _guard_production_auth(SimpleNamespace(environment="production", api_secret_key=None))
    with pytest.raises(RuntimeError):
        _guard_production_auth(SimpleNamespace(environment="production", api_secret_key=""))


def test_guard_passes_when_key_present_or_not_production():
    # key present in production → OK
    _guard_production_auth(SimpleNamespace(environment="production", api_secret_key="HF8...key"))
    # non-production leaves auth optional (local dev / tests) → OK even with no key
    _guard_production_auth(SimpleNamespace(environment="local", api_secret_key=None))
    _guard_production_auth(SimpleNamespace(environment="test", api_secret_key=None))
