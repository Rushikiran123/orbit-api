"""Password hashing and JWT token creation/verification.

Kept framework-agnostic (no FastAPI imports) so it can be unit-tested in
isolation and reused off the request path.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from orbit.core.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


def create_token(subject: str, token_type: TokenType) -> str:
    """Create a signed JWT for ``subject`` (the user id)."""
    settings = get_settings()
    now = datetime.now(UTC)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expires = now + timedelta(days=settings.refresh_token_expire_days)
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or the wrong type."""


def decode_token(token: str, expected_type: TokenType) -> str:
    """Return the subject (user id) of a valid token of the expected type."""
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # expired, bad signature, malformed
        raise TokenError(str(exc)) from exc
    if claims.get("type") != expected_type:
        raise TokenError(f"expected {expected_type} token, got {claims.get('type')!r}")
    subject = claims.get("sub")
    if not subject:
        raise TokenError("token missing subject")
    return str(subject)
