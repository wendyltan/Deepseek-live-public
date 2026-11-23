"""Minimal authenticated loopback reader for existing DSH Bridge task facts.

No discovery, proxies, redirects, key persistence, background poller or model
requests. Only a trusted Mac process should own the Bridge's bearer token.
"""
from __future__ import annotations

import http.client
import json

from app.companion_events import CompanionEventError
from app.companion_trusted_adapter import StaleCompanionFacts, TrustedCompanionAdapter

_PATH = "/dsh-live-bridge/companion-facts"
_MAX_BYTES = 4096


class LoopbackFactsClient:
    def __init__(self, *, port: int, bearer: str, timeout: float = 1.5):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid loopback port")
        if not isinstance(bearer, str) or not 32 <= len(bearer) <= 256:
            raise ValueError("invalid Bridge credential")
        if type(timeout) not in (float, int) or not 0 < timeout <= 10:
            raise ValueError("invalid loopback timeout")
        self._port = port
        self._bearer = bearer
        self._timeout = float(timeout)

    def fetch(self, *, task_id: str, session_id: str) -> dict:
        if not all(isinstance(value, str) and 8 <= len(value) <= 128
                   for value in (task_id, session_id)):
            raise CompanionEventError("invalid task owner")
        payload = json.dumps({"protocolVersion": 1, "task_id": task_id,
                              "session_id": session_id}, separators=(",", ":"))
        connection = http.client.HTTPConnection("127.0.0.1", self._port,
                                                timeout=self._timeout)
        try:
            connection.request("POST", _PATH, body=payload.encode("utf-8"),
                               headers={"Authorization": f"Bearer {self._bearer}",
                                        "Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(_MAX_BYTES + 1)
            if response.status != 200 or len(raw) > _MAX_BYTES:
                raise CompanionEventError("DSH companion facts unavailable")
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("ok") is not True:
                raise CompanionEventError("invalid DSH companion facts reply")
            return data
        except (OSError, TimeoutError, ValueError, UnicodeError,
                http.client.HTTPException) as exc:
            raise CompanionEventError("DSH companion facts unavailable") from exc
        finally:
            connection.close()


class TrustedFactsPoller:
    """One synchronous read per explicit call; no anonymous background work."""

    def __init__(self, adapter: TrustedCompanionAdapter,
                 client: LoopbackFactsClient, *, task_id: str):
        self.adapter = adapter
        self.client = client
        self.task_id = task_id

    def poll(self) -> list[dict]:
        self.adapter._require_active()
        try:
            data = self.client.fetch(task_id=self.task_id,
                                     session_id=self.adapter.session_id)
        except CompanionEventError:
            # A failed authenticated poll must not leave a looping speaking
            # animation or stale work state on a disconnected Mac gateway.
            self.adapter.disconnected()
            raise
        try:
            return self.adapter.apply_facts(data)
        except StaleCompanionFacts:
            # Ignore late/duplicated polls; newer state is still authoritative.
            raise
        except CompanionEventError:
            self.adapter.disconnected()
            raise
