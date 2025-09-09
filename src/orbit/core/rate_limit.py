"""Shared slowapi limiter. Imported by the app factory and by routers that
apply stricter per-endpoint limits (e.g. auth)."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from orbit.core.config import get_settings

limiter = Limiter(key_func=get_remote_address, default_limits=[get_settings().rate_limit])
