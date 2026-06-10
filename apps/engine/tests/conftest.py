# Session-wide network guard: any test that opens a real socket fails fast instead of stalling
# on an SSL/TCP timeout. All network-calling provider code has injectable `_fetcher` seams; tests
# MUST inject fixtures, never the live path.
#
# Override the guard for a single test via:
#   @pytest.mark.allow_network
# or for a whole module:
#   pytestmark = pytest.mark.allow_network
#
# The guard monkeypatches socket.socket.__init__ so ANY real AF_INET/AF_INET6 TCP/UDP connection
# raises immediately with a clear message rather than stalling for 20–30 s on an SSL handshake.
# FastAPI TestClient uses ASGI (in-process), not a real socket, so it is unaffected.
# SQLite and Unix-domain sockets (AF_UNIX) are also unaffected.

from __future__ import annotations

import socket
import pytest

_ORIGINAL_SOCKET_INIT = socket.socket.__init__


def _blocked_socket_init(  # noqa: ANN201
    self,
    family=socket.AF_INET,
    type=socket.SOCK_STREAM,  # noqa: A002
    proto=0,
    fileno=None,
):
    # Allow AF_UNIX (SQLite temp sockets, local IPC) and any existing-fd wraps.
    if fileno is not None:
        return _ORIGINAL_SOCKET_INIT(self, family, type, proto, fileno)
    if family == getattr(socket, "AF_UNIX", None):
        return _ORIGINAL_SOCKET_INIT(self, family, type, proto, fileno)
    # Block AF_INET and AF_INET6 — the two families that reach the internet.
    if family in (socket.AF_INET, socket.AF_INET6):
        raise OSError(
            "NETWORK BLOCKED: test tried to open a real TCP/UDP socket.\n"
            "Inject a fixture provider or _fetcher= kwarg instead of the live path.\n"
            "Add @pytest.mark.allow_network only if the test genuinely needs the network."
        )
    return _ORIGINAL_SOCKET_INIT(self, family, type, proto, fileno)


@pytest.fixture(autouse=True)
def _block_network(request, monkeypatch):
    """Block real TCP/UDP sockets for every test unless @pytest.mark.allow_network is set."""
    if request.node.get_closest_marker("allow_network"):
        yield
        return
    monkeypatch.setattr(socket.socket, "__init__", _blocked_socket_init)
    yield


@pytest.fixture(autouse=True, scope="session")
def _api_auth_gate_off_by_default():
    """The API's shared-secret gate (cosmu.api.app) reads the module-level settings, which on a dev box load
    .env.local — where API_SECRET_KEY is set. Tests that exercise routes without injecting their own settings
    would then 401 locally while passing in CI (no env file). Neutralize the IMPORT-TIME secret once for the
    session; auth tests inject their own Settings(api_secret_key=...) objects and are unaffected."""
    import cosmu.api._shared as shared

    shared.settings.api_secret_key = None
    yield
