"""Auth endpoints: register, login (OAuth2 password flow), refresh, me."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from orbit.api.deps import CurrentUser, SessionDep
from orbit.api.schemas.auth import RefreshRequest, RegisterRequest, TokenPair, UserOut
from orbit.core.config import get_settings
from orbit.core.rate_limit import limiter
from orbit.core.security import TokenError, create_token, decode_token
from orbit.services import auth_service
from orbit.services.auth_service import EmailAlreadyRegistered, InvalidCredentials

router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_LIMIT = get_settings().auth_rate_limit


def _issue_tokens(user_id: str) -> TokenPair:
    return TokenPair(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(_AUTH_LIMIT)
async def register(body: RegisterRequest, session: SessionDep, request: Request) -> UserOut:
    try:
        user = await auth_service.register_user(session, body.email, body.full_name, body.password)
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenPair)
@limiter.limit(_AUTH_LIMIT)
async def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> TokenPair:
    try:
        user = await auth_service.authenticate(session, form.username, form.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return _issue_tokens(user.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: SessionDep) -> TokenPair:
    try:
        user_id = decode_token(body.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc
    return _issue_tokens(user_id)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
