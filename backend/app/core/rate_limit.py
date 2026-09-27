"""app.core.rate_limit — Central rate limiter (in-memory, per-process)."""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["240/minute"])
