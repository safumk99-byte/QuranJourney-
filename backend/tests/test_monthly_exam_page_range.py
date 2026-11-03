def login(client):
    response = client.post("/auth/login", json={
        "login_id": "test_teacher",
        "password": "Test-Teacher-Password-123!",
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_student(client, headers):
    response = client.post("/students", headers=headers, json={
        "student_code": "MONTHLY-PAGE-001",
        "name": "Monthly Page Range Student",
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def fake_surah_refs(surah_no):
    counts = __import__("main").SURAH_AYAH_COUNTS
    return [
        {"surah": surah_no, "surah_name": f"Surah {surah_no}", "ayah": ayah,
         "text": f"Arabic ayah {surah_no}:{ayah}"}
        for ayah in range(1, counts[surah_no - 1] + 1)
    ]


def test_monthly_exam_page_range_generates_only_page_ayahs(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "_surah_ayah_refs", fake_surah_refs)
    headers = login(client)
    student_id = create_student(client, headers)

    preview = client.get(
        f"/students/{student_id}/exam/monthly-pages?start_page=1&end_page=1",
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["ayah_count"] == 7

    generated = client.post(
        f"/students/{student_id}/exam/generate",
        headers=headers,
        json={
            "date": "2026-11-02", "exam_type": "monthly",
            "year": 2026, "month": 11, "question_count": 1,
            "monthly_source": "page_range", "start_page": 1, "end_page": 1,
        },
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["monthly_source"] == "page_range"
    assert (body["start_page"], body["end_page"]) == (1, 1)
    assert len(body["questions"]) == 1
    assert all("Pages 1–1" in q["expected"] for q in body["questions"])


def test_monthly_exam_both_source_deduplicates_overlapping_ayahs(client, monkeypatch):
    import main

    monkeypatch.setattr(main, "_surah_ayah_refs", fake_surah_refs)
    headers = login(client)
    student_id = create_student(client, headers)

    lesson = client.post(
        f"/students/{student_id}/reading",
        headers=headers,
        json={
            "entry_date": "2026-11-02T12:00:00",
            "start_surah": 1, "start_ayah": 1,
            "end_surah": 1, "end_ayah": 7,
            "new_lesson": "Al-Fatiha", "pages": "1",
            "recent_pages": "0", "general_pages": "0",
        },
    )
    assert lesson.status_code == 201, lesson.text

    generated = client.post(
        f"/students/{student_id}/exam/generate",
        headers=headers,
        json={
            "date": "2026-11-02", "exam_type": "monthly",
            "year": 2026, "month": 11, "question_count": 2,
            "monthly_source": "both", "start_page": 1, "end_page": 1,
        },
    )
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert len(body["questions"]) == 2
    assert body["monthly_source"] == "both"


def test_monthly_exam_rejects_reversed_page_range(client):
    headers = login(client)
    student_id = create_student(client, headers)
    response = client.post(
        f"/students/{student_id}/exam/generate",
        headers=headers,
        json={
            "date": "2026-11-02", "exam_type": "monthly",
            "year": 2026, "month": 11, "question_count": 1,
            "monthly_source": "page_range", "start_page": 2, "end_page": 1,
        },
    )
    assert response.status_code == 422
