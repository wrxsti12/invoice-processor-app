from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv() # 從 .env 載入

# 從環境變數讀取 DATABASE_URL，預設使用本地 SQLite
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./invoice_app.db")

# 檢查是否為 PostgreSQL (Render 環境)
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    engine = create_engine(DATABASE_URL)
else:
    # 本地開發使用 SQLite
    engine = create_engine(
        DATABASE_URL, connect_args={"check_same_thread": False}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Invoice(Base):
    """
    發票模型 (包含所有欄位)
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, index=True)
    invoice_number = Column(String, index=True, nullable=False)
    total_amount = Column(String)
    currency = Column(String, nullable=True)
    invoice_date_iso = Column(String, index=True, nullable=True) # 正規化日期
    total_amount_twd = Column(Float, nullable=True)
    exchange_rate_used = Column(Float, nullable=True)
    company_name = Column(String, nullable=True)
    item_description = Column(String, nullable=True)

def create_db_and_tables():
    Base.metadata.create_all(bind=engine)