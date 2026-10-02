"""
Shared rate limiter instance.
Import this from any router to apply rate limits.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address


def _login_key(request):
    """Synchronous login rate-limit key compatible with SlowAPI."""
    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)
