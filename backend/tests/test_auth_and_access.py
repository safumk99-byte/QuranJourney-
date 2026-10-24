def login(client, login_id, password):
    return client.post("/auth/login", json={"login_id": login_id, "password": password})

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_teacher_can_create_student(client):
    token_response = login(client, "test_teacher", "Test-Teacher-Password-123!")
    assert token_response.status_code == 200
    token = token_response.json()["access_token"]
    response = client.post("/students", headers=auth(token), json={"student_code":"T-001", "name":"Test Student", "class_name":"Class 1"})
    assert response.status_code == 201
    assert response.json()["student_code"] == "T-001"

def test_invalid_password_is_rejected(client):
    response = login(client, "test_teacher", "incorrect-password")
    assert response.status_code == 401

def test_parent_only_sees_linked_students(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    first = client.post("/students", headers=headers, json={"student_code":"T-001", "name":"Linked Child"}).json()
    client.post("/students", headers=headers, json={"student_code":"T-002", "name":"Other Child"})
    created = client.post("/parents", headers=headers, json={"login_id":"parent_test", "password":"Parent-Test-Password-123!", "student_ids":[first["id"]]})
    assert created.status_code == 201
    parent_token_response = login(client, "parent_test", "Parent-Test-Password-123!")
    assert parent_token_response.status_code == 200
    visible = client.get("/students", headers=auth(parent_token_response.json()["access_token"]))
    assert visible.status_code == 200
    assert [student["name"] for student in visible.json()] == ["Linked Child"]

def test_parent_cannot_read_unlinked_student_records(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    first = client.post("/students", headers=headers, json={"student_code":"T-001", "name":"Linked Child"}).json()
    other = client.post("/students", headers=headers, json={"student_code":"T-002", "name":"Other Child"}).json()
    client.post("/parents", headers=headers, json={"login_id":"parent_test", "password":"Parent-Test-Password-123!", "student_ids":[first["id"]]})
    parent_token = login(client, "parent_test", "Parent-Test-Password-123!").json()["access_token"]
    denied = client.get(f"/students/{other['id']}/reading", headers=auth(parent_token))
    assert denied.status_code == 403

def test_teacher_can_import_local_backup_without_duplicate_rows(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    backup = {
        "students": [{
            "id": "legacy-student-1", "name": "Amina", "className": "Class 2",
            "totalPages": 604, "completedPages": 10, "currentJuz": 3,
            "journeyStartDate": "2026-01-01"
        }],
        "photos": {"Amina": "data:image/jpeg;base64,TEST"},
        "daily_marks": [{"id": "mark-1", "date": "2026-10-20", "name": "Amina", "s": 2, "ms": 3, "mu": 4, "total": 9}],
        "reading_entries": [{
            "id": "entry-1", "studentId": "legacy-student-1", "date": "2026-10-20",
            "newLesson": "Al-Baqarah 1-5", "pages": 2, "recentRevision": "Al-Fatiha",
            "generalRevision": "Juz 1", "attendance": "Present", "remarks": "Good"
        }, {
            "id": "entry-invalid-date", "studentId": "legacy-student-1", "date": "not-a-date",
            "newLesson": "Invalid test row", "pages": 100
        }],
        "reading_base_pages": {"legacy-student-1": 43}
    }
    first = client.post("/migration/localstorage", headers=headers, json=backup)
    assert first.status_code == 200, first.text
    assert first.json()["imported"]["students_created"] == 1
    assert first.json()["imported"]["reading_entries_created"] == 1
    assert first.json()["imported"]["daily_marks_created"] == 1
    second = client.post("/migration/localstorage", headers=headers, json=backup)
    assert second.status_code == 200, second.text
    assert second.json()["imported"]["students_created"] == 0
    assert second.json()["imported"]["reading_entries_created"] == 0
    assert second.json()["imported"]["daily_marks_created"] == 0
    students = client.get("/students", headers=headers).json()
    assert len(students) == 1
    assert students[0]["completed_pages"] == 45  # invalid-date row must not add 100 pages
    # Re-import must recalculate from the backup, not add the same pages twice.
    assert students[0]["completed_pages"] == 45
    assert students[0]["current_juz"] == 3
    assert students[0]["photo_data"] == "data:image/jpeg;base64,TEST"
    marks = client.get(f"/students/{students[0]['id']}/marks", headers=headers)
    assert marks.status_code == 200
    assert marks.json()[0]["s"] == 2
    assert marks.json()[0]["ms"] == 3
    assert marks.json()[0]["mu"] == 4
    assert marks.json()[0]["points"] == 9
