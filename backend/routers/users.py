from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User as UserModel
from schemas import UserCreate, UserUpdate, UserResponse, SignupRequest, LoginRequest
from utils.authentication import get_current_user, create_access_token
router = APIRouter()


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login a user"""
    user = db.query(UserModel).filter(UserModel.email == data.email, UserModel.password == data.password).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    access_token = create_access_token(data={"sub": user.name, "id": user.id, "email": user.email})
    return {
        "message": "Login Successful",
        "token": access_token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email}
    }

@router.post("/signup")
def signup(data: SignupRequest, db: Session = Depends(get_db)):
    """Signup a new user"""
    existing_user = db.query(UserModel).filter(UserModel.email == data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    new_user = UserModel(name=data.name, email=data.email, password=data.password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    access_token = create_access_token(data={"sub": new_user.name, "id": new_user.id, "email": new_user.email})
    return {
        "status": "success",
        "message": f"User {data.name} signed up successfully",
        "token": access_token,
        "token_type": "bearer",
        "user": {"id": new_user.id, "name": new_user.name, "email": new_user.email}
    }



@router.get("/protected")
def protected_route(current_user: dict = Depends(get_current_user)):
    """A protected route that requires authentication"""
    return {"message": f"Hello, user {current_user['id']}! This is a protected route."}