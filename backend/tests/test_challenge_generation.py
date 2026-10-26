import main

def login(client):
    response = client.post("/auth/login", json={
        "login_id": "test_teacher",
        "password": "Test-Teacher-Password-123!",
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

def test_generate_daily_challenge_from_saved_juz_range(client, monkeypatch):
    headers = login(client)
    student_response = client.post(
        "/students",
        headers=headers,
        json={"student_code": "CH-001", "name": "Challenge Student"},
    )
    assert student_response.status_code == 201
    student_id = student_response.json()["id"]

    range_response = client.post(
        f"/students/{student_id}/challenge/ranges",
        headers=headers,
        json={"start_juz": 2, "end_juz": 2, "status": "Learning"},
    )
    assert range_response.status_code == 201

    monkeypatch.setattr(main, "_juz_ayah_refs", lambda juz: [
        {"surah": 2, "surah_name": "Al-Baqarah", "ayah": n, "text": f"Arabic ayah text {n}"}
        for n in range(1, 21)
    ])

    generated = client.post(
        f"/students/{student_id}/challenge/generate/2026-10-26",
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    payload = generated.json()
    assert payload["date"] == "2026-10-26"
    assert len(payload["q"]) == 5
    assert len({q["text"] for q in payload["q"]}) == 5
    assert all(q["text"].startswith("Arabic ayah text ") for q in payload["q"])
    assert all(q["expected"].startswith("Surah 2:") for q in payload["q"])

    # The generated session is persisted and reused by the normal sessions API.
    sessions = client.get(
        f"/students/{student_id}/challenge/sessions",
        headers=headers,
    )
    assert sessions.status_code == 200
    saved = next(row for row in sessions.json() if row["date"] == "2026-10-26")
    assert saved["q"] == payload["q"]

def test_generate_daily_challenge_requires_a_saved_range(client):
    headers = login(client)
    student = client.post(
        "/students",
        headers=headers,
        json={"student_code": "CH-002", "name": "No Range Student"},
    ).json()
    response = client.post(
        f"/students/{student['id']}/challenge/generate/2026-10-26",
        headers=headers,
    )
    assert response.status_code == 400
    assert "Learning Range" in response.json()["detail"]

def test_parent_cannot_generate_daily_challenge(client):
    teacher_headers = login(client)
    student = client.post(
        "/students",
        headers=teacher_headers,
        json={"student_code": "CH-003", "name": "Linked Student"},
    ).json()
    parent = client.post(
        "/parents",
        headers=teacher_headers,
        json={"login_id": "challenge_parent", "password": "Parent-Test-Password-123!", "student_ids": [student["id"]]},
    )
    assert parent.status_code == 201
    token = client.post("/auth/login", json={
        "login_id": "challenge_parent",
        "password": "Parent-Test-Password-123!",
    }).json()["access_token"]
    response = client.post(
        f"/students/{student['id']}/challenge/generate/2026-10-26",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
