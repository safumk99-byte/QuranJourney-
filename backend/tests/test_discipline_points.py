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


def test_all_point_boards_reset_each_month_without_deleting_history(client, monkeypatch):
    from datetime import date
    import main

    monkeypatch.setattr(main, "current_month_bounds", lambda reference=None: (date(2026, 10, 1), date(2026, 10, 31)))
    headers = auth(login(client, "test_teacher", "Test-Teacher-Password-123!").json()["access_token"])
    student = client.post("/students", headers=headers, json={
        "student_code": "MONTH-001", "name": "Monthly Points Student", "class_name": "Class 1"
    }).json()
    sid = student["id"]

    # Reading points: September is retained but must not count in October's leaderboard.
    for day, pages, recent, general in [
        ("2026-09-30T12:00:00", "5", "2", "1"),
        ("2026-10-01T12:00:00", "2", "1", "1"),
    ]:
        response = client.post(f"/students/{sid}/reading", headers=headers, json={
            "entry_date": day, "pages": pages, "recent_pages": recent, "general_pages": general
        })
        assert response.status_code == 201, response.text

    # Discipline deductions are also monthly; older deductions remain in the audit history.
    for day in ("2026-09-30", "2026-10-02"):
        response = client.post("/discipline", headers=headers, json={
            "student_id": sid, "reason": "Monthly test deduction", "points_deducted": 2,
            "incident_date": day, "notes": "Monthly reset test"
        })
        assert response.status_code == 201, response.text

    # Challenge marks should start afresh in October without deleting September sessions.
    for day, review in (("2026-09-30", 20), ("2026-10-03", 10)):
        response = client.put(f"/students/{sid}/challenge/sessions/{day}", headers=headers, json={
            "date": day, "confirmed": True, "score": 0,
            "questions": [{"text": f"Q{i}", "submitted": True, "review": review} for i in range(5)]
        })
        assert response.status_code == 200, response.text

    points = client.get("/points/leaderboard", headers=headers)
    assert points.status_code == 200
    current = next(row for row in points.json() if row["student_id"] == sid)
    assert current["month"] == "2026-10"
    assert current["new_lesson_points"] == 20
    assert current["recent_revision_points"] == 1
    assert current["general_revision_points"] == 1
    assert current["total_points"] == 22

    discipline = client.get("/discipline/summary", headers=headers)
    assert discipline.status_code == 200
    current_discipline = next(row for row in discipline.json() if row["student_id"] == sid)
    assert current_discipline["academic_points"] == 22
    assert current_discipline["discipline_points_deducted"] == 2
    assert current_discipline["final_points"] == 20

    challenge = client.get("/challenge/leaderboard", headers=headers)
    assert challenge.status_code == 200
    current_challenge = next(row for row in challenge.json() if row["student_id"] == sid)
    assert current_challenge["month"] == "2026-10"
    assert current_challenge["total_marks"] == 50
    assert current_challenge["challenges_completed"] == 1

    # Both months' source records still exist; monthly reset is a reporting boundary, not data deletion.
    history = client.get(f"/students/{sid}/reading", headers=headers)
    assert history.status_code == 200
    assert len(history.json()) == 2
    challenge_history = client.get(f"/students/{sid}/challenge/sessions", headers=headers)
    assert challenge_history.status_code == 200
    assert {row["date"] for row in challenge_history.json()} == {"2026-09-30", "2026-10-03"}
