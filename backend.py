"""
TrustPay Africa - COMPLETE BACKEND
Single file: FastAPI + SQLAlchemy + SQLite + JWT
Run: python backend.py
"""

import uuid
import enum
from datetime import datetime, timedelta
from typing import Optional

# ── FastAPI
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── SQLAlchemy
from sqlalchemy import (
    create_engine, Column, Integer, String, Float,
    Boolean, DateTime, ForeignKey, Text, Enum as SAEnum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql import func

# ── Auth
from jose import JWTError, jwt
from passlib.context import CryptContext

# ── Pydantic
from pydantic import BaseModel, EmailStr, Field, validator

import uvicorn

# ═══════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════

DATABASE_URL = "sqlite:///./trustpay_africa.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ═══════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════

class EscrowStatus(str, enum.Enum):
    pending   = "pending"
    funded    = "funded"
    active    = "active"
    completed = "completed"
    disputed  = "disputed"
    cancelled = "cancelled"

class TxnType(str, enum.Enum):
    deposit    = "deposit"
    withdrawal = "withdrawal"
    escrow_in  = "escrow_in"
    escrow_out = "escrow_out"
    refund     = "refund"

class DisputeStatus(str, enum.Enum):
    open     = "open"
    resolved = "resolved"
    closed   = "closed"

# ═══════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════

class User(Base):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    full_name       = Column(String(100), nullable=False)
    email           = Column(String(150), unique=True, index=True, nullable=False)
    phone           = Column(String(20),  unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active       = Column(Boolean, default=True)
    is_admin        = Column(Boolean, default=False)
    is_verified     = Column(Boolean, default=False)
    is_suspended    = Column(Boolean, default=False)
    trust_score     = Column(Float, default=50.0)
    completed_deals = Column(Integer, default=0)
    avatar_url      = Column(String(255), nullable=True)
    language        = Column(String(10), default="en")
    dark_mode       = Column(Boolean, default=False)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    wallet            = relationship("Wallet", back_populates="owner", uselist=False)
    sent_messages     = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    notifications     = relationship("Notification", back_populates="user")
    reviews_given     = relationship("Review", foreign_keys="Review.reviewer_id", back_populates="reviewer")
    reviews_received  = relationship("Review", foreign_keys="Review.reviewed_id", back_populates="reviewed")
    marketplace_items = relationship("MarketplaceItem", back_populates="seller")
    admin_logs        = relationship("AdminLog", back_populates="admin")


class Wallet(Base):
    __tablename__ = "wallets"
    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    balance        = Column(Float, default=0.0)
    escrow_balance = Column(Float, default=0.0)
    currency       = Column(String(10), default="NGN")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    owner        = relationship("User", back_populates="wallet")
    transactions = relationship("Transaction", back_populates="wallet")


class Transaction(Base):
    __tablename__ = "transactions"
    id             = Column(Integer, primary_key=True, index=True)
    wallet_id      = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    type           = Column(SAEnum(TxnType), nullable=False)
    amount         = Column(Float, nullable=False)
    balance_before = Column(Float, nullable=False)
    balance_after  = Column(Float, nullable=False)
    reference      = Column(String(100), unique=True, nullable=False)
    description    = Column(String(255), nullable=True)
    escrow_deal_id = Column(Integer, ForeignKey("escrow_deals.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    wallet      = relationship("Wallet", back_populates="transactions")
    escrow_deal = relationship("EscrowDeal", back_populates="transactions")


class EscrowDeal(Base):
    __tablename__ = "escrow_deals"
    id                = Column(Integer, primary_key=True, index=True)
    buyer_id          = Column(Integer, ForeignKey("users.id"), nullable=False)
    seller_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_name      = Column(String(200), nullable=False)
    description       = Column(Text, nullable=True)
    amount            = Column(Float, nullable=False)
    status            = Column(SAEnum(EscrowStatus), default=EscrowStatus.pending)
    delivery_timeline = Column(String(100), nullable=True)
    buyer_confirmed   = Column(Boolean, default=False)
    seller_confirmed  = Column(Boolean, default=False)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    funded_at         = Column(DateTime(timezone=True), nullable=True)
    completed_at      = Column(DateTime(timezone=True), nullable=True)
    cancelled_at      = Column(DateTime(timezone=True), nullable=True)

    buyer        = relationship("User", foreign_keys=[buyer_id])
    seller       = relationship("User", foreign_keys=[seller_id])
    transactions = relationship("Transaction", back_populates="escrow_deal")
    messages     = relationship("Message", back_populates="escrow_deal")
    disputes     = relationship("Dispute", back_populates="escrow_deal")


class Message(Base):
    __tablename__ = "messages"
    id             = Column(Integer, primary_key=True, index=True)
    escrow_deal_id = Column(Integer, ForeignKey("escrow_deals.id"), nullable=False)
    sender_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    content        = Column(Text, nullable=False)
    is_read        = Column(Boolean, default=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    escrow_deal = relationship("EscrowDeal", back_populates="messages")
    sender      = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver    = relationship("User", foreign_keys=[receiver_id])


class Notification(Base):
    __tablename__ = "notifications"
    id         = Column(Integer, primary_key=True, index=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    title      = Column(String(200), nullable=False)
    body       = Column(Text, nullable=False)
    type       = Column(String(50), default="general")
    is_read    = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="notifications")


class Review(Base):
    __tablename__ = "reviews"
    id             = Column(Integer, primary_key=True, index=True)
    reviewer_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    reviewed_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    escrow_deal_id = Column(Integer, ForeignKey("escrow_deals.id"), nullable=True)
    rating         = Column(Integer, nullable=False)
    comment        = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    reviewer = relationship("User", foreign_keys=[reviewer_id], back_populates="reviews_given")
    reviewed = relationship("User", foreign_keys=[reviewed_id], back_populates="reviews_received")


class Dispute(Base):
    __tablename__ = "disputes"
    id             = Column(Integer, primary_key=True, index=True)
    escrow_deal_id = Column(Integer, ForeignKey("escrow_deals.id"), nullable=False)
    raised_by_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    reason         = Column(Text, nullable=False)
    status         = Column(SAEnum(DisputeStatus), default=DisputeStatus.open)
    admin_notes    = Column(Text, nullable=True)
    resolved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at    = Column(DateTime(timezone=True), nullable=True)

    escrow_deal = relationship("EscrowDeal", back_populates="disputes")
    raised_by   = relationship("User", foreign_keys=[raised_by_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_id])


class MarketplaceItem(Base):
    __tablename__ = "marketplace_items"
    id          = Column(Integer, primary_key=True, index=True)
    seller_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    price       = Column(Float, nullable=False)
    category    = Column(String(100), nullable=True)
    image_url   = Column(String(255), nullable=True)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    seller = relationship("User", back_populates="marketplace_items")


class AdminLog(Base):
    __tablename__ = "admin_logs"
    id          = Column(Integer, primary_key=True, index=True)
    admin_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    action      = Column(String(200), nullable=False)
    target_id   = Column(Integer, nullable=True)
    target_type = Column(String(50), nullable=True)
    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    admin = relationship("User", back_populates="admin_logs")


# Create all tables
Base.metadata.create_all(bind=engine)

# ═══════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════

SECRET_KEY = "trustpay_africa_super_secret_key_change_in_production_2024"
ALGORITHM  = "HS256"
TOKEN_EXP  = 60 * 24  # 24 hours

pwd_context   = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


def hash_pw(pw: str) -> str:
    return pwd_context.hash(pw)

def verify_pw(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def make_token(user_id: int) -> str:
    exp = datetime.utcnow() + timedelta(minutes=TOKEN_EXP)
    return jwt.encode({"sub": user_id, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)

def gen_ref(prefix="TXN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"

def notify(db, user_id: int, title: str, body: str, ntype: str = "general"):
    db.add(Notification(user_id=user_id, title=title, body=body, type=ntype))

def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db)
) -> User:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        uid = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_suspended:
        raise HTTPException(status_code=403, detail="Account suspended")
    return user

def get_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# ═══════════════════════════════════════════════════════
# SCHEMAS
# ═══════════════════════════════════════════════════════

class RegisterIn(BaseModel):
    full_name:        str
    email:            str
    phone:            str
    password:         str
    confirm_password: str

class LoginIn(BaseModel):
    email:    str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user_id:      int
    full_name:    str
    is_admin:     bool

class UserOut(BaseModel):
    id: int; full_name: str; email: str; phone: str
    is_active: bool; is_admin: bool; is_verified: bool
    is_suspended: bool; trust_score: float
    completed_deals: int; avatar_url: Optional[str]
    language: str; dark_mode: bool
    created_at: datetime
    class Config: from_attributes = True

class UserUpdate(BaseModel):
    full_name:  Optional[str] = None
    phone:      Optional[str] = None
    avatar_url: Optional[str] = None
    language:   Optional[str] = None
    dark_mode:  Optional[bool] = None

class WalletOut(BaseModel):
    id: int; user_id: int; balance: float
    escrow_balance: float; currency: str; created_at: datetime
    class Config: from_attributes = True

class DepositIn(BaseModel):
    amount: float = Field(..., gt=0)

class WithdrawIn(BaseModel):
    amount: float = Field(..., gt=0)

class TxnOut(BaseModel):
    id: int; type: TxnType; amount: float
    balance_before: float; balance_after: float
    reference: str; description: Optional[str]; created_at: datetime
    class Config: from_attributes = True

class EscrowIn(BaseModel):
    seller_email:      str
    product_name:      str
    description:       Optional[str] = None
    amount:            float = Field(..., gt=0)
    delivery_timeline: Optional[str] = None

class EscrowOut(BaseModel):
    id: int; buyer_id: int; seller_id: int
    product_name: str; description: Optional[str]
    amount: float; status: EscrowStatus
    delivery_timeline: Optional[str]
    buyer_confirmed: bool; seller_confirmed: bool
    created_at: datetime
    funded_at:    Optional[datetime] = None
    completed_at: Optional[datetime] = None
    class Config: from_attributes = True

class MsgIn(BaseModel):
    escrow_deal_id: int
    receiver_id:    int
    content:        str

class MsgOut(BaseModel):
    id: int; escrow_deal_id: int; sender_id: int
    receiver_id: int; content: str; is_read: bool; created_at: datetime
    class Config: from_attributes = True

class NotifOut(BaseModel):
    id: int; title: str; body: str; type: str; is_read: bool; created_at: datetime
    class Config: from_attributes = True

class MarketIn(BaseModel):
    title:       str
    description: Optional[str] = None
    price:       float = Field(..., gt=0)
    category:    Optional[str] = None

class MarketOut(BaseModel):
    id: int; seller_id: int; title: str
    description: Optional[str]; price: float
    category: Optional[str]; image_url: Optional[str]
    is_active: bool; created_at: datetime
    class Config: from_attributes = True

class ReviewIn(BaseModel):
    reviewed_id:    int
    escrow_deal_id: Optional[int] = None
    rating:         int = Field(..., ge=1, le=5)
    comment:        Optional[str] = None

class ReviewOut(BaseModel):
    id: int; reviewer_id: int; reviewed_id: int
    rating: int; comment: Optional[str]; created_at: datetime
    class Config: from_attributes = True

class DisputeIn(BaseModel):
    escrow_deal_id: int
    reason:         str

class DisputeOut(BaseModel):
    id: int; escrow_deal_id: int; raised_by_id: int
    reason: str; status: DisputeStatus
    admin_notes: Optional[str]; created_at: datetime
    class Config: from_attributes = True

class ResolveIn(BaseModel):
    admin_notes: str
    release_to:  str  # "buyer" or "seller"

class AdminLogOut(BaseModel):
    id: int; admin_id: int; action: str
    target_id: Optional[int]; target_type: Optional[str]
    notes: Optional[str]; created_at: datetime
    class Config: from_attributes = True

# ═══════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════

app = FastAPI(title="TrustPay Africa API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

# ═══════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"message": "TrustPay Africa API", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/auth/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if data.password != data.confirm_password:
        raise HTTPException(400, "Passwords do not match")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Email already registered")
    if db.query(User).filter(User.phone == data.phone).first():
        raise HTTPException(400, "Phone already registered")

    user = User(full_name=data.full_name, email=data.email,
                phone=data.phone, hashed_password=hash_pw(data.password))
    db.add(user)
    db.flush()
    db.add(Wallet(user_id=user.id))
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=make_token(user.id),
                    user_id=user.id, full_name=user.full_name, is_admin=user.is_admin)

@app.post("/api/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first() or \
           db.query(User).filter(User.phone == data.email).first()
    if not user or not verify_pw(data.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    if user.is_suspended:
        raise HTTPException(403, "Account suspended")
    return TokenOut(access_token=make_token(user.id),
                    user_id=user.id, full_name=user.full_name, is_admin=user.is_admin)

@app.get("/api/auth/me", response_model=UserOut)
def me(u: User = Depends(get_current_user)):
    return u

@app.post("/api/auth/logout")
def logout(u: User = Depends(get_current_user)):
    return {"message": "Logged out"}

# ═══════════════════════════════════════════════════════
# WALLET ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/wallet/", response_model=WalletOut)
def get_wallet(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
    if not w: raise HTTPException(404, "Wallet not found")
    return w

@app.post("/api/wallet/deposit", response_model=WalletOut)
def deposit(data: DepositIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
    bal = w.balance
    w.balance += data.amount
    db.add(Transaction(wallet_id=w.id, type=TxnType.deposit, amount=data.amount,
        balance_before=bal, balance_after=w.balance, reference=gen_ref(),
        description=f"Deposit of N{data.amount:,.2f}"))
    db.commit(); db.refresh(w); return w

@app.post("/api/wallet/withdraw", response_model=WalletOut)
def withdraw(data: WithdrawIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
    if w.balance < data.amount: raise HTTPException(400, "Insufficient balance")
    bal = w.balance
    w.balance -= data.amount
    db.add(Transaction(wallet_id=w.id, type=TxnType.withdrawal, amount=data.amount,
        balance_before=bal, balance_after=w.balance, reference=gen_ref(),
        description=f"Withdrawal of N{data.amount:,.2f}"))
    db.commit(); db.refresh(w); return w

@app.get("/api/wallet/transactions", response_model=list[TxnOut])
def transactions(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
    if not w: raise HTTPException(404, "Wallet not found")
    return db.query(Transaction).filter(Transaction.wallet_id == w.id)\
             .order_by(Transaction.created_at.desc()).limit(100).all()

# ═══════════════════════════════════════════════════════
# ESCROW ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/escrow/", response_model=list[EscrowOut])
def list_escrows(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(EscrowDeal).filter(
        (EscrowDeal.buyer_id == u.id) | (EscrowDeal.seller_id == u.id)
    ).order_by(EscrowDeal.created_at.desc()).all()

@app.post("/api/escrow/create", response_model=EscrowOut, status_code=201)
def create_escrow(data: EscrowIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    seller = db.query(User).filter(User.email == data.seller_email).first()
    if not seller: raise HTTPException(404, "Seller not found")
    if seller.id == u.id: raise HTTPException(400, "Cannot escrow with yourself")
    deal = EscrowDeal(buyer_id=u.id, seller_id=seller.id,
                      product_name=data.product_name, description=data.description,
                      amount=data.amount, delivery_timeline=data.delivery_timeline)
    db.add(deal); db.flush()
    notify(db, seller.id, "New Escrow Request",
           f"{u.full_name} wants to escrow '{data.product_name}' for N{data.amount:,.2f}", "escrow")
    db.commit(); db.refresh(deal); return deal

@app.get("/api/escrow/{deal_id}", response_model=EscrowOut)
def get_escrow(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if u.id not in (deal.buyer_id, deal.seller_id) and not u.is_admin:
        raise HTTPException(403, "Access denied")
    return deal

@app.post("/api/escrow/{deal_id}/fund", response_model=EscrowOut)
def fund_escrow(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if deal.buyer_id != u.id: raise HTTPException(403, "Only buyer can fund")
    if deal.status != EscrowStatus.pending: raise HTTPException(400, f"Already {deal.status}")
    w = db.query(Wallet).filter(Wallet.user_id == u.id).first()
    if w.balance < deal.amount: raise HTTPException(400, "Insufficient balance")
    bal = w.balance
    w.balance        -= deal.amount
    w.escrow_balance += deal.amount
    db.add(Transaction(wallet_id=w.id, type=TxnType.escrow_in, amount=deal.amount,
        balance_before=bal, balance_after=w.balance, reference=gen_ref("ESC"),
        description=f"Escrow funded: {deal.product_name}", escrow_deal_id=deal.id))
    deal.status    = EscrowStatus.funded
    deal.funded_at = datetime.utcnow()
    notify(db, deal.seller_id, "Escrow Funded",
           f"N{deal.amount:,.2f} locked for '{deal.product_name}'. Deliver now!", "payment")
    db.commit(); db.refresh(deal); return deal

@app.post("/api/escrow/{deal_id}/activate", response_model=EscrowOut)
def activate_escrow(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if deal.seller_id != u.id: raise HTTPException(403, "Only seller can activate")
    if deal.status != EscrowStatus.funded: raise HTTPException(400, "Must be funded first")
    deal.status = EscrowStatus.active
    notify(db, deal.buyer_id, "Escrow Active",
           f"Seller accepted '{deal.product_name}'. Awaiting delivery.", "escrow")
    db.commit(); db.refresh(deal); return deal

@app.post("/api/escrow/{deal_id}/release", response_model=EscrowOut)
def release_escrow(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if deal.buyer_id != u.id: raise HTTPException(403, "Only buyer can release")
    if deal.status not in (EscrowStatus.funded, EscrowStatus.active):
        raise HTTPException(400, f"Cannot release in '{deal.status}' status")
    bw = db.query(Wallet).filter(Wallet.user_id == deal.buyer_id).first()
    sw = db.query(Wallet).filter(Wallet.user_id == deal.seller_id).first()
    bw.escrow_balance -= deal.amount
    bal = sw.balance
    sw.balance += deal.amount
    db.add(Transaction(wallet_id=sw.id, type=TxnType.escrow_out, amount=deal.amount,
        balance_before=bal, balance_after=sw.balance, reference=gen_ref("REL"),
        description=f"Payment released: {deal.product_name}", escrow_deal_id=deal.id))
    deal.status       = EscrowStatus.completed
    deal.buyer_confirmed = True
    deal.completed_at = datetime.utcnow()
    buyer  = db.query(User).filter(User.id == deal.buyer_id).first()
    seller = db.query(User).filter(User.id == deal.seller_id).first()
    buyer.completed_deals  += 1
    seller.completed_deals += 1
    seller.trust_score = min(100.0, seller.trust_score + 2.0)
    buyer.trust_score  = min(100.0, buyer.trust_score  + 1.0)
    notify(db, deal.seller_id, "Payment Released!",
           f"N{deal.amount:,.2f} added to your wallet for '{deal.product_name}'.", "payment")
    db.commit(); db.refresh(deal); return deal

@app.post("/api/escrow/{deal_id}/cancel", response_model=EscrowOut)
def cancel_escrow(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if u.id not in (deal.buyer_id, deal.seller_id): raise HTTPException(403, "Access denied")
    if deal.status in (EscrowStatus.completed, EscrowStatus.cancelled):
        raise HTTPException(400, f"Cannot cancel '{deal.status}' deal")
    if deal.status in (EscrowStatus.funded, EscrowStatus.active):
        bw = db.query(Wallet).filter(Wallet.user_id == deal.buyer_id).first()
        bal = bw.balance
        bw.escrow_balance -= deal.amount
        bw.balance += deal.amount
        db.add(Transaction(wallet_id=bw.id, type=TxnType.refund, amount=deal.amount,
            balance_before=bal, balance_after=bw.balance, reference=gen_ref("REF"),
            description=f"Refund: cancelled escrow for {deal.product_name}", escrow_deal_id=deal.id))
        notify(db, deal.buyer_id, "Escrow Cancelled - Refunded",
               f"N{deal.amount:,.2f} refunded to your wallet.", "payment")
    deal.status       = EscrowStatus.cancelled
    deal.cancelled_at = datetime.utcnow()
    db.commit(); db.refresh(deal); return deal

@app.post("/api/escrow/{deal_id}/dispute", response_model=DisputeOut, status_code=201)
def open_dispute(deal_id: int, data: DisputeIn,
                 u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Not found")
    if u.id not in (deal.buyer_id, deal.seller_id): raise HTTPException(403, "Access denied")
    if deal.status not in (EscrowStatus.funded, EscrowStatus.active):
        raise HTTPException(400, "Can only dispute funded/active escrows")
    deal.status = EscrowStatus.disputed
    dispute = Dispute(escrow_deal_id=deal.id, raised_by_id=u.id, reason=data.reason)
    db.add(dispute)
    other = deal.seller_id if u.id == deal.buyer_id else deal.buyer_id
    notify(db, other, "Dispute Opened",
           f"A dispute was raised on '{deal.product_name}'. Admin will review.", "security")
    db.commit(); db.refresh(dispute); return dispute

# ═══════════════════════════════════════════════════════
# CHAT ROUTES
# ═══════════════════════════════════════════════════════

@app.post("/api/chat/send", response_model=MsgOut, status_code=201)
def send_msg(data: MsgIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == data.escrow_deal_id).first()
    if not deal: raise HTTPException(404, "Deal not found")
    if u.id not in (deal.buyer_id, deal.seller_id): raise HTTPException(403, "Access denied")
    if data.receiver_id not in (deal.buyer_id, deal.seller_id):
        raise HTTPException(400, "Receiver not in this deal")
    if data.receiver_id == u.id: raise HTTPException(400, "Cannot message yourself")
    msg = Message(escrow_deal_id=data.escrow_deal_id, sender_id=u.id,
                  receiver_id=data.receiver_id, content=data.content)
    db.add(msg); db.commit(); db.refresh(msg); return msg

@app.get("/api/chat/{deal_id}", response_model=list[MsgOut])
def get_chat(deal_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == deal_id).first()
    if not deal: raise HTTPException(404, "Deal not found")
    if u.id not in (deal.buyer_id, deal.seller_id) and not u.is_admin:
        raise HTTPException(403, "Access denied")
    msgs = db.query(Message).filter(Message.escrow_deal_id == deal_id)\
              .order_by(Message.created_at.asc()).all()
    for m in msgs:
        if m.receiver_id == u.id: m.is_read = True
    db.commit(); return msgs

# ═══════════════════════════════════════════════════════
# NOTIFICATIONS ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/notifications/", response_model=list[NotifOut])
def get_notifs(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Notification).filter(Notification.user_id == u.id)\
             .order_by(Notification.created_at.desc()).limit(100).all()

@app.get("/api/notifications/unread-count")
def unread_count(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.user_id == u.id,
                                       Notification.is_read == False).count()
    return {"unread_count": n}

@app.post("/api/notifications/mark-all-read")
def mark_all(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.user_id == u.id,
                                   Notification.is_read == False)\
      .update({"is_read": True})
    db.commit(); return {"message": "All read"}

@app.post("/api/notifications/{nid}/read")
def mark_one(nid: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.id == nid,
                                       Notification.user_id == u.id).first()
    if n: n.is_read = True; db.commit()
    return {"message": "Read"}

# ═══════════════════════════════════════════════════════
# PROFILE ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/profile/", response_model=UserOut)
def my_profile(u: User = Depends(get_current_user)):
    return u

@app.put("/api/profile/", response_model=UserOut)
def update_profile(data: UserUpdate, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.full_name  is not None: u.full_name  = data.full_name
    if data.phone      is not None: u.phone      = data.phone
    if data.avatar_url is not None: u.avatar_url = data.avatar_url
    if data.language   is not None: u.language   = data.language
    if data.dark_mode  is not None: u.dark_mode  = data.dark_mode
    db.commit(); db.refresh(u); return u

@app.get("/api/profile/{user_id}", response_model=UserOut)
def public_profile(user_id: int, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u: raise HTTPException(404, "User not found")
    return u

@app.post("/api/profile/review", response_model=ReviewOut, status_code=201)
def leave_review(data: ReviewIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if data.reviewed_id == u.id: raise HTTPException(400, "Cannot review yourself")
    reviewed = db.query(User).filter(User.id == data.reviewed_id).first()
    if not reviewed: raise HTTPException(404, "User not found")
    rev = Review(reviewer_id=u.id, reviewed_id=data.reviewed_id,
                 escrow_deal_id=data.escrow_deal_id, rating=data.rating, comment=data.comment)
    db.add(rev)
    all_revs = db.query(Review).filter(Review.reviewed_id == data.reviewed_id).all()
    avg = sum(r.rating for r in all_revs) / len(all_revs)
    reviewed.trust_score = round((avg / 5) * 100, 1)
    db.commit(); db.refresh(rev); return rev

@app.get("/api/profile/{user_id}/reviews", response_model=list[ReviewOut])
def user_reviews(user_id: int, db: Session = Depends(get_db)):
    return db.query(Review).filter(Review.reviewed_id == user_id).all()

# ═══════════════════════════════════════════════════════
# MARKETPLACE ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/marketplace/")
def list_market(search: Optional[str] = None, category: Optional[str] = None,
                db: Session = Depends(get_db)):
    q = db.query(MarketplaceItem).filter(MarketplaceItem.is_active == True)
    if search:   q = q.filter(MarketplaceItem.title.ilike(f"%{search}%"))
    if category and category != "All":
        q = q.filter(MarketplaceItem.category.ilike(f"%{category}%"))
    items = q.order_by(MarketplaceItem.created_at.desc()).limit(100).all()
    result = []
    for item in items:
        d = {c.name: getattr(item, c.name) for c in item.__table__.columns}
        d["seller_name"]        = item.seller.full_name
        d["seller_trust_score"] = item.seller.trust_score
        d["created_at"]         = str(d["created_at"])
        result.append(d)
    return result

@app.post("/api/marketplace/", response_model=MarketOut, status_code=201)
def create_item(data: MarketIn, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = MarketplaceItem(seller_id=u.id, title=data.title,
                           description=data.description, price=data.price, category=data.category)
    db.add(item); db.commit(); db.refresh(item); return item

@app.get("/api/marketplace/my-listings", response_model=list[MarketOut])
def my_listings(u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(MarketplaceItem).filter(MarketplaceItem.seller_id == u.id).all()

@app.delete("/api/marketplace/{item_id}")
def delete_item(item_id: int, u: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(MarketplaceItem).filter(MarketplaceItem.id == item_id).first()
    if not item: raise HTTPException(404, "Not found")
    if item.seller_id != u.id and not u.is_admin: raise HTTPException(403, "Permission denied")
    item.is_active = False; db.commit()
    return {"message": "Listing removed"}

@app.get("/api/marketplace/categories")
def categories():
    return {"categories": ["Electronics","Fashion","Food & Groceries","Real Estate",
                            "Vehicles","Services","Books","Health & Beauty",
                            "Agriculture","Education","Other"]}

# ═══════════════════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════════════════

@app.get("/api/admin/stats")
def admin_stats(admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    return {
        "users": {
            "total":     db.query(User).count(),
            "active":    db.query(User).filter(User.is_active == True).count(),
            "suspended": db.query(User).filter(User.is_suspended == True).count(),
        },
        "escrows": {
            "total":    db.query(EscrowDeal).count(),
            "active":   db.query(EscrowDeal).filter(EscrowDeal.status.in_(
                            [EscrowStatus.funded, EscrowStatus.active])).count(),
            "disputed": db.query(EscrowDeal).filter(EscrowDeal.status == EscrowStatus.disputed).count(),
        },
        "disputes": {
            "open": db.query(Dispute).filter(Dispute.status == DisputeStatus.open).count()
        },
        "transactions": {"total": db.query(Transaction).count()}
    }

@app.get("/api/admin/users", response_model=list[UserOut])
def admin_users(admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.desc()).all()

@app.post("/api/admin/users/{uid}/suspend")
def suspend(uid: int, admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "Not found")
    if u.is_admin: raise HTTPException(403, "Cannot suspend admin")
    u.is_suspended = True
    db.add(AdminLog(admin_id=admin.id, action="suspend_user", target_id=uid, target_type="user"))
    db.commit(); return {"message": f"{u.email} suspended"}

@app.post("/api/admin/users/{uid}/unsuspend")
def unsuspend(uid: int, admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "Not found")
    u.is_suspended = False
    db.add(AdminLog(admin_id=admin.id, action="unsuspend_user", target_id=uid, target_type="user"))
    db.commit(); return {"message": f"{u.email} unsuspended"}

@app.post("/api/admin/users/{uid}/make-admin")
def make_admin(uid: int, admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == uid).first()
    if not u: raise HTTPException(404, "Not found")
    u.is_admin = True
    db.add(AdminLog(admin_id=admin.id, action="make_admin", target_id=uid, target_type="user"))
    db.commit(); return {"message": f"{u.email} is now admin"}

@app.get("/api/admin/escrows", response_model=list[EscrowOut])
def admin_escrows(admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    return db.query(EscrowDeal).order_by(EscrowDeal.created_at.desc()).all()

@app.get("/api/admin/disputes", response_model=list[DisputeOut])
def admin_disputes(admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    return db.query(Dispute).order_by(Dispute.created_at.desc()).all()

@app.post("/api/admin/disputes/{did}/resolve")
def resolve_dispute(did: int, data: ResolveIn,
                    admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    dispute = db.query(Dispute).filter(Dispute.id == did).first()
    if not dispute: raise HTTPException(404, "Not found")
    if dispute.status != DisputeStatus.open: raise HTTPException(400, "Already resolved")
    deal = db.query(EscrowDeal).filter(EscrowDeal.id == dispute.escrow_deal_id).first()
    bw = db.query(Wallet).filter(Wallet.user_id == deal.buyer_id).first()
    sw = db.query(Wallet).filter(Wallet.user_id == deal.seller_id).first()
    if data.release_to == "seller":
        bal = sw.balance
        bw.escrow_balance -= deal.amount
        sw.balance += deal.amount
        db.add(Transaction(wallet_id=sw.id, type=TxnType.escrow_out, amount=deal.amount,
            balance_before=bal, balance_after=sw.balance, reference=gen_ref("ADM"),
            description="Admin resolved: released to seller", escrow_deal_id=deal.id))
        notify(db, deal.seller_id, "Dispute Resolved",
               f"N{deal.amount:,.2f} released to your wallet.", "payment")
    elif data.release_to == "buyer":
        bal = bw.balance
        bw.escrow_balance -= deal.amount
        bw.balance += deal.amount
        db.add(Transaction(wallet_id=bw.id, type=TxnType.refund, amount=deal.amount,
            balance_before=bal, balance_after=bw.balance, reference=gen_ref("ADM"),
            description="Admin resolved: refunded to buyer", escrow_deal_id=deal.id))
        notify(db, deal.buyer_id, "Dispute Resolved",
               f"N{deal.amount:,.2f} refunded to your wallet.", "payment")
    else:
        raise HTTPException(400, "release_to must be 'buyer' or 'seller'")
    deal.status       = EscrowStatus.completed
    deal.completed_at = datetime.utcnow()
    dispute.status       = DisputeStatus.resolved
    dispute.admin_notes  = data.admin_notes
    dispute.resolved_by_id = admin.id
    dispute.resolved_at  = datetime.utcnow()
    db.add(AdminLog(admin_id=admin.id, action="resolve_dispute", target_id=did,
                    target_type="dispute", notes=data.admin_notes))
    db.commit()
    return {"message": f"Resolved. Released to {data.release_to}."}

@app.get("/api/admin/logs", response_model=list[AdminLogOut])
def admin_logs(admin: User = Depends(get_admin), db: Session = Depends(get_db)):
    return db.query(AdminLog).order_by(AdminLog.created_at.desc()).limit(200).all()

# ═══════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 50)
    print("  TrustPay Africa Backend v1.0")
    print("  http://127.0.0.1:8000")
    print("  Docs: http://127.0.0.1:8000/docs")
    print("=" * 50)
    uvicorn.run("backend:app", host="0.0.0.0", port=8000, reload=False)
