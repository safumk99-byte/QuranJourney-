import main

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

def test_parent_cannot_import_localstorage_backup(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    student = client.post("/students", headers=auth(teacher_token), json={"student_code":"T-IMPORT-001", "name":"Import Guard Child"}).json()
    created = client.post("/parents", headers=auth(teacher_token), json={"login_id":"parent_import_guard", "password":"Parent-Import-Password-123!", "student_ids":[student["id"]]})
    assert created.status_code == 201
    parent_token = login(client, "parent_import_guard", "Parent-Import-Password-123!").json()["access_token"]
    denied = client.post("/migration/localstorage", headers=auth(parent_token), json={"students":[{"id":"attacker-student","name":"Injected Child"}]})
    assert denied.status_code == 403
    visible = client.get("/students", headers=auth(teacher_token))
    assert all(row["name"] != "Injected Child" for row in visible.json())


def test_import_caps_completed_pages_at_total_pages(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    backup = {
        "students": [{"id":"legacy-cap-1", "name":"Page Cap", "totalPages":10, "completedPages":0}],
        "reading_entries": [{"id":"cap-entry-1", "studentId":"legacy-cap-1", "date":"2026-10-20", "pages":20}],
        "reading_base_pages": {"legacy-cap-1":9}
    }
    response = client.post("/migration/localstorage", headers=headers, json=backup)
    assert response.status_code == 200, response.text
    students = client.get("/students", headers=headers).json()
    imported_student = next(row for row in students if row["name"] == "Page Cap")
    assert imported_student["completed_pages"] == 10

def test_reimport_without_photo_does_not_erase_existing_photo(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    first = client.post("/migration/localstorage", headers=headers, json={"students":[{"id":"legacy-photo-keep","name":"Photo Keep","totalPages":604}], "photos":{"Photo Keep":"data:image/jpeg;base64,KEEP"}})
    assert first.status_code == 200, first.text
    second = client.post("/migration/localstorage", headers=headers, json={"students":[{"id":"legacy-photo-keep","name":"Photo Keep","totalPages":604}]})
    assert second.status_code == 200, second.text
    students = client.get("/students", headers=headers).json()
    row = next(student for student in students if student["name"] == "Photo Keep")
    assert row["photo_data"] == "data:image/jpeg;base64,KEEP"

def test_import_skips_negative_or_out_of_range_marks(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    backup = {
        "students": [{"id": "legacy-mark-validation", "name": "Mark Validation"}],
        "daily_marks": [
            {"id": "valid-mark", "date": "2026-10-20", "name": "Mark Validation", "s": 2, "ms": 3, "mu": 4, "total": 9},
            {"id": "negative-mark", "date": "2026-10-20", "name": "Mark Validation", "s": -1, "ms": 0, "mu": 0, "total": -1},
            {"id": "oversized-mark", "date": "2026-10-20", "name": "Mark Validation", "s": 1001, "ms": 0, "mu": 0, "total": 1001},
        ],
    }
    response = client.post("/migration/localstorage", headers=headers, json=backup)
    assert response.status_code == 200, response.text
    assert response.json()["imported"]["daily_marks_created"] == 1
    assert response.json()["imported"]["skipped"] == 2
    students = client.get("/students", headers=headers).json()
    student = next(row for row in students if row["name"] == "Mark Validation")
    marks = client.get(f"/students/{student['id']}/marks", headers=headers).json()
    assert len(marks) == 1
    assert (marks[0]["s"], marks[0]["ms"], marks[0]["mu"], marks[0]["points"]) == (2, 3, 4, 9)

def test_import_commit_failure_rolls_back_all_new_records(client, monkeypatch):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    backup = {
        "students": [{"id": "legacy-rollback-1", "name": "Rollback Child"}],
        "daily_marks": [{"id": "rollback-mark-1", "date": "2026-10-20", "name": "Rollback Child", "s": 1, "ms": 2, "mu": 3, "total": 6}],
    }

    def fail_commit(self):
        raise RuntimeError("simulated database commit failure")

    monkeypatch.setattr(main.Session, "commit", fail_commit)
    import pytest
    with pytest.raises(RuntimeError, match="simulated database commit failure"):
        client.post("/migration/localstorage", headers=headers, json=backup)

    # The endpoint's commit handler must roll back the student and mark together.
    with main.SessionLocal() as db:
        assert db.scalar(main.select(main.Student).where(main.Student.legacy_id == "legacy-rollback-1")) is None
        assert db.scalar(main.select(main.DailyMark).where(main.DailyMark.legacy_id == "mark:rollback-mark-1")) is None

def test_parent_cannot_write_reading_attendance_or_marks(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    student = client.post("/students", headers=headers, json={"student_code": "T-PARENT-WRITE", "name": "Read Only Child"}).json()
    parent_response = client.post("/parents", headers=headers, json={"login_id": "parent_read_only", "password": "Parent-Read-Only-123!", "student_ids": [student["id"]]})
    assert parent_response.status_code == 201
    parent_token = login(client, "parent_read_only", "Parent-Read-Only-123!").json()["access_token"]
    parent_headers = auth(parent_token)

    reading = client.post(f"/students/{student['id']}/reading", headers=parent_headers, json={"entry_date": "2026-10-24", "new_lesson": "Test"})
    attendance = client.post(f"/students/{student['id']}/attendance", headers=parent_headers, json={"attendance_date": "2026-10-24", "status": "present"})
    marks = client.post(f"/students/{student['id']}/marks", headers=parent_headers, json={"mark_date": "2026-10-24", "points": 5})
    assert reading.status_code == 403
    assert attendance.status_code == 403
    assert marks.status_code == 403


def test_parent_cannot_read_any_record_type_for_unlinked_student(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    linked = client.post("/students", headers=headers, json={"student_code": "T-LINKED", "name": "Linked Record Child"}).json()
    unlinked = client.post("/students", headers=headers, json={"student_code": "T-UNLINKED", "name": "Unlinked Record Child"}).json()
    created = client.post("/parents", headers=headers, json={"login_id": "parent_link_scope", "password": "Parent-Link-Scope-123!", "student_ids": [linked["id"]]})
    assert created.status_code == 201
    parent_token = login(client, "parent_link_scope", "Parent-Link-Scope-123!").json()["access_token"]
    parent_headers = auth(parent_token)

    assert client.get(f"/students/{unlinked['id']}/reading", headers=parent_headers).status_code == 403
    assert client.get(f"/students/{unlinked['id']}/attendance", headers=parent_headers).status_code == 403
    assert client.get(f"/students/{unlinked['id']}/marks", headers=parent_headers).status_code == 403
    assert client.get(f"/students/{linked['id']}/reading", headers=parent_headers).status_code == 200
    assert client.get(f"/students/{linked['id']}/attendance", headers=parent_headers).status_code == 200
    assert client.get(f"/students/{linked['id']}/marks", headers=parent_headers).status_code == 200

def test_frontend_api_contract_teacher_to_parent_read_flow(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    teacher_headers = auth(teacher_token)

    created_student = client.post("/students", headers=teacher_headers, json={
        "student_code": "QJ-CONTRACT-001", "name": "Contract Test Child", "class_name": "Hifz A"
    })
    assert created_student.status_code == 201, created_student.text
    student_id = created_student.json()["id"]

    assert client.post(f"/students/{student_id}/reading", headers=teacher_headers, json={
        "entry_date": "2026-10-24T00:00:00", "new_lesson": "Al-Baqarah 1-5",
        "pages": "2", "recent_revision": "Al-Fatiha", "general_revision": "Juz 1",
        "remarks": "Good progress"
    }).status_code == 201
    assert client.post(f"/students/{student_id}/attendance", headers=teacher_headers, json={
        "attendance_date": "2026-10-24T00:00:00", "status": "present", "remarks": "On time"
    }).status_code == 201
    assert client.post(f"/students/{student_id}/marks", headers=teacher_headers, json={
        "mark_date": "2026-10-24T00:00:00", "points": 9, "remarks": "Excellent"
    }).status_code == 201

    parent_created = client.post("/parents", headers=teacher_headers, json={
        "login_id": "parent_contract", "password": "Parent-Contract-123!", "student_ids": [student_id]
    })
    assert parent_created.status_code == 201, parent_created.text
    parent_login = login(client, "parent_contract", "Parent-Contract-123!")
    assert parent_login.status_code == 200
    parent_headers = auth(parent_login.json()["access_token"])

    # These are the response fields consumed by parent.js.
    children = client.get("/students", headers=parent_headers)
    assert children.status_code == 200
    assert children.json() == [{
        "id": student_id, "student_code": "QJ-CONTRACT-001", "name": "Contract Test Child",
        "class_name": "Hifz A", "total_pages": 604, "completed_pages": 2,
        "current_juz": 1, "journey_start_date": None, "photo_data": None
    }]

    reading = client.get(f"/students/{student_id}/reading", headers=parent_headers).json()
    attendance = client.get(f"/students/{student_id}/attendance", headers=parent_headers).json()
    marks = client.get(f"/students/{student_id}/marks", headers=parent_headers).json()
    assert reading[0]["new_lesson"] == "Al-Baqarah 1-5"
    assert reading[0]["pages"] == "2"
    assert attendance[0]["status"] == "present"
    assert (marks[0]["s"], marks[0]["ms"], marks[0]["mu"], marks[0]["points"]) == (0, 0, 0, 9)
    assert marks[0]["remarks"] == "Excellent"

def test_attendance_rejects_invalid_status_and_marks_enforce_point_bounds(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    student = client.post("/students", headers=headers, json={
        "student_code": "QJ-VALIDATION-002", "name": "Validation Child"
    }).json()
    invalid_attendance = client.post(
        f"/students/{student['id']}/attendance",
        headers=headers,
        json={"attendance_date": "2026-10-24", "status": "maybe"}
    )
    assert invalid_attendance.status_code == 422

    for points in (-1, 1001):
        invalid_mark = client.post(
            f"/students/{student['id']}/marks",
            headers=headers,
            json={"mark_date": "2026-10-24", "points": points}
        )
        assert invalid_mark.status_code == 422

    valid_attendance = client.post(
        f"/students/{student['id']}/attendance",
        headers=headers,
        json={"attendance_date": "2026-10-24", "status": "present"}
    )
    assert valid_attendance.status_code == 201
    valid_mark = client.post(
        f"/students/{student['id']}/marks",
        headers=headers,
        json={"mark_date": "2026-10-24", "points": 1000}
    )
    assert valid_mark.status_code == 201

def test_inactive_account_cannot_login_or_reuse_existing_token(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    with main.SessionLocal() as db:
        teacher = db.scalar(main.select(main.User).where(main.User.login_id == "test_teacher"))
        teacher.is_active = False
        db.commit()

    denied_login = login(client, "test_teacher", "Test-Teacher-Password-123!")
    assert denied_login.status_code == 401
    denied_existing_token = client.get("/auth/me", headers=auth(teacher_token))
    assert denied_existing_token.status_code == 401


def test_invalid_or_expired_bearer_token_is_rejected(client):
    import jwt
    from datetime import datetime, timedelta, timezone

    invalid = client.get("/auth/me", headers=auth("not-a-valid-jwt"))
    assert invalid.status_code == 401

    expired = jwt.encode(
        {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        main.JWT_SECRET,
        algorithm="HS256",
    )
    expired_response = client.get("/auth/me", headers=auth(expired))
    assert expired_response.status_code == 401

def test_parent_cannot_create_students_or_parent_accounts(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    teacher_headers = auth(teacher_token)
    student = client.post("/students", headers=teacher_headers, json={
        "student_code": "QJ-ROLE-001", "name": "Role Boundary Child"
    }).json()
    parent_created = client.post("/parents", headers=teacher_headers, json={
        "login_id": "parent_role_boundary", "password": "Parent-Role-Boundary-123!", "student_ids": [student["id"]]
    })
    assert parent_created.status_code == 201
    parent_token = login(client, "parent_role_boundary", "Parent-Role-Boundary-123!").json()["access_token"]
    parent_headers = auth(parent_token)

    create_student = client.post("/students", headers=parent_headers, json={
        "student_code": "QJ-PARENT-INJECT", "name": "Should Not Be Created"
    })
    create_parent = client.post("/parents", headers=parent_headers, json={
        "login_id": "parent_injected", "password": "Injected-Parent-123!", "student_ids": [student["id"]]
    })
    assert create_student.status_code == 403
    assert create_parent.status_code == 403

    teacher_students = client.get("/students", headers=teacher_headers)
    assert teacher_students.status_code == 200
    assert all(row["name"] != "Should Not Be Created" for row in teacher_students.json())


def test_protected_endpoints_reject_missing_authentication(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/students").status_code == 401
    assert client.post("/students", json={"student_code": "QJ-NO-AUTH", "name": "Unauthorized"}).status_code == 401
    assert client.post("/migration/localstorage", json={"students": []}).status_code == 401

def test_reading_rejects_bad_date_and_long_pages_value(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    student = client.post("/students", headers=headers, json={"student_code": "READ-VAL", "name": "Reading Validation"}).json()
    bad_date = client.post(f"/students/{student['id']}/reading", headers=headers, json={"entry_date": "not-a-date"})
    long_value = client.post(f"/students/{student['id']}/reading", headers=headers, json={"entry_date": "2026-10-24T00:00:00", "pages": "x" * 201})
    assert bad_date.status_code == 422
    assert long_value.status_code == 422
    assert client.get(f"/students/{student['id']}/reading", headers=headers).json() == []


def test_attendance_rejects_bad_date_without_saving(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    student = client.post("/students", headers=headers, json={"student_code": "ATT-DATE", "name": "Attendance Date"}).json()
    response = client.post(f"/students/{student['id']}/attendance", headers=headers, json={"attendance_date": "not-a-date", "status": "present"})
    assert response.status_code == 422
    assert client.get(f"/students/{student['id']}/attendance", headers=headers).json() == []

def test_student_creation_rejects_blank_or_overlong_fields(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    blank_name = client.post("/students", headers=headers, json={"student_code": "BAD-NAME", "name": "   "})
    long_code = client.post("/students", headers=headers, json={"student_code": "C" * 81, "name": "Valid Name"})
    long_name = client.post("/students", headers=headers, json={"student_code": "BAD-LONG-NAME", "name": "N" * 161})
    assert blank_name.status_code == 422
    assert long_code.status_code == 422
    assert long_name.status_code == 422


def test_parent_creation_rejects_short_password_and_empty_student_list(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    short_password = client.post("/parents", headers=headers, json={
        "login_id": "parent_short_pw", "password": "short", "student_ids": [1]
    })
    no_students = client.post("/parents", headers=headers, json={
        "login_id": "parent_no_kids", "password": "Valid-Password-123!", "student_ids": []
    })
    assert short_password.status_code == 422
    assert no_students.status_code == 422



def test_teacher_can_update_student_and_parent_cannot(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    teacher_headers = auth(teacher_token)
    created = client.post("/students", headers=teacher_headers, json={
        "student_code": "QJ-UPDATE-001", "name": "Before Update", "class_name": "Hifz A"
    })
    assert created.status_code == 201
    student_id = created.json()["id"]

    updated = client.patch(f"/students/{student_id}", headers=teacher_headers, json={
        "name": "After Update", "class_name": "Hifz B", "total_pages": 604,
        "completed_pages": 25, "current_juz": 2, "journey_start_date": "2026-10-01"
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "After Update"
    assert updated.json()["class_name"] == "Hifz B"
    assert updated.json()["completed_pages"] == 25
    assert updated.json()["current_juz"] == 2

    parent_created = client.post("/parents", headers=teacher_headers, json={
        "login_id": "parent_update_guard", "password": "Parent-Update-Guard-123!", "student_ids": [student_id]
    })
    assert parent_created.status_code == 201
    parent_token = login(client, "parent_update_guard", "Parent-Update-Guard-123!").json()["access_token"]
    denied = client.patch(f"/students/{student_id}", headers=auth(parent_token), json={"name": "Unauthorized"})
    assert denied.status_code == 403


def test_teacher_student_delete_is_soft_and_parent_no_longer_sees_student(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    teacher_headers = auth(teacher_token)
    created = client.post("/students", headers=teacher_headers, json={
        "student_code": "QJ-DELETE-001", "name": "Soft Delete Child"
    })
    assert created.status_code == 201
    student_id = created.json()["id"]
    parent_created = client.post("/parents", headers=teacher_headers, json={
        "login_id": "parent_delete_guard", "password": "Parent-Delete-Guard-123!", "student_ids": [student_id]
    })
    assert parent_created.status_code == 201
    parent_token = login(client, "parent_delete_guard", "Parent-Delete-Guard-123!").json()["access_token"]

    deleted = client.delete(f"/students/{student_id}", headers=teacher_headers)
    assert deleted.status_code == 204
    assert all(row["id"] != student_id for row in client.get("/students", headers=teacher_headers).json())
    assert client.get("/students", headers=auth(parent_token)).json() == []
    # Existing records are not cascade-deleted by the soft-delete operation.
    with main.SessionLocal() as db:
        row = db.get(main.Student, student_id)
        assert row is not None and row.is_active is False


def test_student_update_rejects_completed_pages_above_total(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    created = client.post("/students", headers=headers, json={
        "student_code": "QJ-UPDATE-VALIDATION", "name": "Progress Validation"
    })
    student_id = created.json()["id"]
    response = client.patch(f"/students/{student_id}", headers=headers, json={
        "total_pages": 10, "completed_pages": 11
    })
    assert response.status_code == 422


def test_teacher_can_create_update_and_delete_reading_entry(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    student = client.post("/students", headers=headers, json={
        "student_code": "QJ-READING-CRUD", "name": "Reading CRUD Child"
    }).json()
    student_id = student["id"]

    created = client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-10-20T00:00:00", "new_lesson": "Al-Baqarah 1-5", "pages": "2"
    })
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    updated = client.patch(f"/students/{student_id}/reading/{entry_id}", headers=headers, json={
        "new_lesson": "Al-Baqarah 1-7", "pages": "3", "remarks": "Updated"
    })
    assert updated.status_code == 200, updated.text
    rows = client.get(f"/students/{student_id}/reading", headers=headers).json()
    assert len(rows) == 1
    assert rows[0]["new_lesson"] == "Al-Baqarah 1-7"
    assert rows[0]["pages"] == "3"
    assert rows[0]["remarks"] == "Updated"

    deleted = client.delete(f"/students/{student_id}/reading/{entry_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/students/{student_id}/reading", headers=headers).json() == []


def test_reading_entry_mutations_are_teacher_only_and_student_scoped(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    first = client.post("/students", headers=headers, json={
        "student_code": "QJ-READING-SCOPE-A", "name": "Reading Scope A"
    }).json()
    second = client.post("/students", headers=headers, json={
        "student_code": "QJ-READING-SCOPE-B", "name": "Reading Scope B"
    }).json()
    entry = client.post(f"/students/{first['id']}/reading", headers=headers, json={
        "entry_date": "2026-10-20T00:00:00", "new_lesson": "Protected"
    }).json()

    wrong_student = client.patch(f"/students/{second['id']}/reading/{entry['id']}", headers=headers, json={
        "new_lesson": "Should not change"
    })
    wrong_delete = client.delete(f"/students/{second['id']}/reading/{entry['id']}", headers=headers)
    assert wrong_student.status_code == 404
    assert wrong_delete.status_code == 404
    rows = client.get(f"/students/{first['id']}/reading", headers=headers).json()
    assert rows[0]["new_lesson"] == "Protected"

    parent_created = client.post("/parents", headers=headers, json={
        "login_id": "parent_reading_mutation", "password": "Parent-Reading-Mutation-123!",
        "student_ids": [first["id"]]
    })
    assert parent_created.status_code == 201
    parent_token = login(client, "parent_reading_mutation", "Parent-Reading-Mutation-123!").json()["access_token"]
    parent_headers = auth(parent_token)
    assert client.patch(f"/students/{first['id']}/reading/{entry['id']}", headers=parent_headers, json={
        "new_lesson": "Unauthorized"
    }).status_code == 403
    assert client.delete(f"/students/{first['id']}/reading/{entry['id']}", headers=parent_headers).status_code == 403


def test_reading_entry_pages_update_student_progress_without_double_counting(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    student = client.post("/students", headers=headers, json={
        "student_code": "QJ-PAGE-PROGRESS", "name": "Page Progress Child",
        "total_pages": 10, "completed_pages": 2
    }).json()
    student_id = student["id"]

    created = client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-10-24T00:00:00", "new_lesson": "Lesson", "pages": "3"
    })
    assert created.status_code == 201, created.text
    assert client.get("/students", headers=headers).json()[0]["completed_pages"] == 5

    entry_id = created.json()["id"]
    updated = client.patch(f"/students/{student_id}/reading/{entry_id}", headers=headers, json={"pages": "4"})
    assert updated.status_code == 200, updated.text
    assert client.get("/students", headers=headers).json()[0]["completed_pages"] == 6

    deleted = client.delete(f"/students/{student_id}/reading/{entry_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/students", headers=headers).json()[0]["completed_pages"] == 2


def test_reading_entry_progress_never_exceeds_total_pages(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    student = client.post("/students", headers=headers, json={
        "student_code": "QJ-PAGE-CAP", "name": "Page Cap Child",
        "total_pages": 5, "completed_pages": 4
    }).json()
    student_id = student["id"]
    response = client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-10-24T00:00:00", "pages": "20"
    })
    assert response.status_code == 201, response.text
    visible = next(s for s in client.get("/students", headers=headers).json() if s["id"] == student_id)
    assert visible["completed_pages"] == 5

def test_daily_marks_validate_breakdown_and_can_be_deleted(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(teacher_token)
    student = client.post("/students", headers=headers, json={
        "student_code": "QJ-MARK-DELETE-001", "name": "Daily Mark Child"
    }).json()
    student_id = student["id"]

    invalid = client.post(
        f"/students/{student_id}/marks",
        headers=headers,
        json={"mark_date": "2026-10-24", "points": 8, "s": 2, "ms": 3, "mu": 4}
    )
    assert invalid.status_code == 422

    created = client.post(
        f"/students/{student_id}/marks",
        headers=headers,
        json={"mark_date": "2026-10-24", "points": 9, "s": 2, "ms": 3, "mu": 4}
    )
    assert created.status_code == 201, created.text
    mark_id = created.json()["id"]
    assert (created.json()["s"], created.json()["ms"], created.json()["mu"], created.json()["points"]) == (2, 3, 4, 9)

    deleted = client.delete(f"/students/{student_id}/marks/{mark_id}", headers=headers)
    assert deleted.status_code == 204
    remaining = client.get(f"/students/{student_id}/marks", headers=headers)
    assert remaining.status_code == 200
    assert all(row["id"] != mark_id for row in remaining.json())

