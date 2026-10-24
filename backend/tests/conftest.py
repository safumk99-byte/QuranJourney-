import os

# Keep tests isolated from the production Neon database.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_quran_journey.db"
os.environ["JWT_SECRET"] = "test-only-secret-key-with-more-than-32-characters"
os.environ["INITIAL_TEACHER_ID"] = "test_teacher"
os.environ["INITIAL_TEACHER_PASSWORD"] = "Test-Teacher-Password-123!"
os.environ["CORS_ORIGINS"] = "http://testserver"

import pytest
from fastapi.testclient import TestClient
import main
from sqlalchemy import delete

@pytest.fixture
def client():
    main.Base.metadata.drop_all(bind=main.engine)
    main.Base.metadata.create_all(bind=main.engine)
    with main.SessionLocal() as db:
        db.add(main.User(login_id="test_teacher", password_hash=main.password_hash.hash("Test-Teacher-Password-123!"), role="teacher"))
        db.commit()
    with TestClient(main.app) as test_client:
        yield test_client
    main.Base.metadata.drop_all(bind=main.engine)
