from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID

from backend.database import get_session
from backend.models.user import User
from backend.services.auth import hash_password, verify_password, create_access_token, require_user

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]

    class Config:
        from_attributes = True


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest):
    with get_session() as session:
        if session.query(User).filter_by(email=body.email).first():
            raise HTTPException(status_code=400, detail="Email already registered")

        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        user = User(
            email=body.email,
            hashed_password=hash_password(body.password),
            full_name=body.full_name,
        )
        session.add(user)
        session.flush()
        token = create_access_token(str(user.id))

    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    with get_session() as session:
        user = session.query(User).filter_by(email=body.email).first()
        if not user or not verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Account disabled")
        token = create_access_token(str(user.id))

    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(require_user)):
    return user
