
import sys
import os

# Add current directory to python path to find 'app'
sys.path.append(os.getcwd())

from app.db.base import Base
from app.db.session import engine
# Import models to ensure they are registered
from app.models import iot

def init_db():
    print("Creating database tables...")
    try:
        Base.metadata.create_all(bind=engine)
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")

if __name__ == "__main__":
    init_db()
