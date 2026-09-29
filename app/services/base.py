"""Shared service plumbing."""

from __future__ import annotations

from app.db import Gateway, get_gateway


class BaseService:
    """Binds a service to a gateway, resolved lazily per call.

    Resolving at call time (rather than import time) lets the app start without
    Supabase credentials and lets tests swap in an in-memory gateway.
    """

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._gateway = gateway

    @property
    def gateway(self) -> Gateway:
        return self._gateway if self._gateway is not None else get_gateway()
