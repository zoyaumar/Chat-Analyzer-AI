import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text


#load_dotenv()  
#DATABASE_URL = os.getenv("DATABASE_URL")
DATABASE_URL = "postgresql://postgres%2Eknwxpnefclphfaflkmgj:Zozoumar123@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
if not DATABASE_URL:
    raise ValueError("❌ DATABASE_URL is not set")


engine = create_engine(DATABASE_URL, connect_args={"sslmode": "require"})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

with engine.connect() as conn:
    print(conn.execute(text("SELECT 1")).scalar())

    

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    try:
        with engine.connect() as conn:
            result = conn.execute("SELECT 1").scalar()
            print("✅ Database connected:", result)
    except Exception as e:
        print("❌ DB connection failed:", e)

