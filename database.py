from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 1. 設定資料庫
DATABASE_URL = "sqlite:///./invoice_app.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. 建立資料模型 (Models)

class Invoice(Base):
    """
    發票模型
    (已將日期欄位正規化為 'invoice_date_iso')
    """
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, index=True)
    invoice_number = Column(String, index=True, nullable=False)
    
    # 原始金額
    total_amount = Column(String)
    currency = Column(String, nullable=True) 
    
    # --- (修改) 正規化的日期欄位 ---
    # 儲存所有日期的 ISO 格式 (YYYY-MM-DD)
    invoice_date_iso = Column(String, index=True, nullable=True) 
    # -----------------------------------
    
    # 轉換後的金額
    total_amount_twd = Column(Float, nullable=True) 
    exchange_rate_used = Column(Float, nullable=True)
    
    # 品項與公司
    company_name = Column(String, nullable=True)
    item_description = Column(String, nullable=True)

# 讓 main.py 可以呼叫此函式來建立所有資料表
def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

