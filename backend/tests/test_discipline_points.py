from datetime import date

def login(client, login_id, password):
    return client.post('/auth/login', json={'login_id': login_id, 'password': password})


def auth(token):
    return {'Authorization': f'Bearer {token}'}


def test_teacher_can_add_discipline_points_and_reverse_a_record(client):
    token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    headers = auth(token)
    student = client.post(
        "/students",
        headers=headers,
        json={"student_code": "DISC-001", "name": "Discipline Test Student", "class_name": "Class 1"},
    ).json()

    created = client.post(
        "/discipline",
        headers=headers,
        json={
            "student_id": student["id"],
            "reason": "Disrespectful speech",
            "points_deducted": 2,
            "incident_date": date.today().isoformat(),
            "notes": "Test record",
        },
    )
    assert created.status_code == 201
    record_id = created.json()["id"]

    summary = client.get("/discipline/summary", headers=headers)
    assert summary.status_code == 200
    entry = next(row for row in summary.json() if row["student_id"] == student["id"])
    assert entry["discipline_points_deducted"] == 2
    assert entry["final_points"] == entry["academic_points"] - 2

    reversed_response = client.post(
        f"/discipline/{record_id}/reverse",
        headers=headers,
        json={"reason": "Entered against the wrong student"},
    )
    assert reversed_response.status_code == 200

    summary_after = client.get("/discipline/summary", headers=headers)
    entry_after = next(row for row in summary_after.json() if row["student_id"] == student["id"])
    assert entry_after["discipline_points_deducted"] == 0
    history = client.get(f"/discipline/{student['id']}", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["is_reversed"] is True


def test_parent_cannot_manage_discipline_points(client):
    teacher_token = login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"]
    teacher_headers = auth(teacher_token)
    student = client.post(
        "/students",
        headers=teacher_headers,
        json={"student_code": "DISC-002", "name": "Parent Access Test"},
    ).json()
    client.post(
        "/parents",
        headers=teacher_headers,
        json={"login_id": "discipline_parent", "password": "Parent-Test-Password-123!", "student_ids": [student["id"]]},
    )
    parent_token = login(client, "discipline_parent", "Parent-Test-Password-123!").json()["access_token"]
    denied = client.post(
        "/discipline",
        headers=auth(parent_token),
        json={
            "student_id": student["id"],
            "reason": "Disrespectful speech",
            "points_deducted": 2,
            "incident_date": date.today().isoformat(),
        },
    )
    assert denied.status_code == 403
