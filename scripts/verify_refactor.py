
import sys
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Add app to path
sys.path.append(os.getcwd())

from app.main import app
from app.db.session import get_db
from app.db.base import Base
from app.core.auth import require_read_permission, require_write_permission

# Setup in-memory SQLite DB
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[require_read_permission] = lambda: "test-user"
app.dependency_overrides[require_write_permission] = lambda: "test-user"

# Create tables
Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_health():
    print("Testing /health...")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    print("MATCH")

def test_telemetry_flow():
    print("Testing Telemetry Flow...")
    
    # 1. Ingest Reading
    payload = {
        "device_id": "sensor-001",
        "reading_value": 25.5,
        "reading_type": "temperature",
        "unit": "Celsius",
        "battery_level": 98.0
    }
    response = client.post("/telemetry/ingest", json=payload)
    if response.status_code != 201:
        print("FAILED Ingest:", response.text)
    assert response.status_code == 201
    data = response.json()
    assert data["device_id"] == "sensor-001"
    assert data["reading_value"] == 25.5
    print("Ingest OK")

    # 2. List Readings
    response = client.get("/telemetry/")
    assert response.status_code == 200
    items = response.json()
    assert len(items) >= 1
    assert items[0]["device_id"] == "sensor-001"
    print("List OK")

    # 3. Get Devices
    response = client.get("/devices")
    assert response.status_code == 200
    assert "sensor-001" in response.json()
    print("Devices OK")

    # 4. Get Latest
    response = client.get("/telemetry/latest?device_id=sensor-001")
    assert response.status_code == 200
    assert response.json()["reading_value"] == 25.5
    print("Latest OK")

if __name__ == "__main__":
    try:
        test_health()
        test_telemetry_flow()
        print("\n[OK] VERIFICATION SUCCESSFUL: App refactored to IoT Engine.")
    except Exception as e:
        print(f"\n[FAIL] VERIFICATION FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
