def login(client):
    response = client.post("/auth/login", json={
        "login_id": "test_teacher",
        "password": "Test-Teacher-Password-123!",
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_student(client, headers, code="JUZ-001"):
    response = client.post("/students", headers=headers, json={
        "student_code": code,
        "name": "Automatic Juz Test",
        "current_juz": 1,
        "next_juz_pages": 0,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def lesson(client, headers, student_id, *, start_ayah=142, end_ayah=145, pages="1"):
    return client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-11-01T12:00:00",
        "start_surah": 2,
        "start_ayah": start_ayah,
        "end_surah": 2,
        "end_ayah": end_ayah,
        "new_lesson": "Al-Baqarah",
        "pages": pages,
        "recent_pages": "0",
        "general_pages": "0",
    })


def get_student(client, headers, student_id):
    response = client.get("/students", headers=headers)
    assert response.status_code == 200
    return next(row for row in response.json() if row["id"] == student_id)


def test_new_lesson_updates_next_juz_progress_and_duplicate_ayah_is_not_counted_twice(client):
    headers = login(client)
    student_id = create_student(client, headers)

    first = lesson(client, headers, student_id)
    assert first.status_code == 201, first.text
    first_progress = get_student(client, headers, student_id)
    assert first_progress["current_juz"] == 1
    assert first_progress["next_juz_pages"] == 1.0

    # Re-recording the exact same ayah range does not inflate the unique page coverage.
    second = lesson(client, headers, student_id)
    assert second.status_code == 201, second.text
    duplicate_progress = get_student(client, headers, student_id)
    assert duplicate_progress["next_juz_pages"] == 1.0


def test_edit_and_delete_recalculate_automatic_juz_progress(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-002")
    created = lesson(client, headers, student_id)
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    edited = client.patch(f"/students/{student_id}/reading/{entry_id}", headers=headers, json={
        "end_ayah": 146,
    })
    assert edited.status_code == 200, edited.text
    edited_progress = get_student(client, headers, student_id)["next_juz_pages"]
    assert edited_progress > 1.0

    deleted = client.delete(f"/students/{student_id}/reading/{entry_id}", headers=headers)
    assert deleted.status_code == 204
    final = get_student(client, headers, student_id)
    assert final["current_juz"] == 1
    assert final["next_juz_pages"] == 0.0


def test_revision_only_entry_does_not_change_juz_progress(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-003")
    response = client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-11-01T12:00:00",
        "recent_start_surah": 2,
        "recent_start_ayah": 142,
        "recent_end_surah": 2,
        "recent_end_ayah": 145,
        "recent_revision": "Al-Baqarah",
        "pages": "0",
        "recent_pages": "1",
        "general_pages": "0",
    })
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 1
    assert progress["next_juz_pages"] == 0.0


def test_completing_all_unique_pages_of_next_juz_advances_current_juz(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-004")
    # Juz 2 in the 604-page Madinah Mushaf runs from Al-Baqarah 2:142 to 2:252.
    ranges = [(142, 163), (164, 185), (186, 207), (208, 229), (230, 252)]
    for start_ayah, end_ayah in ranges:
        response = lesson(
            client, headers, student_id,
            start_ayah=start_ayah, end_ayah=end_ayah, pages="5",
        )
        assert response.status_code == 201, response.text

    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 2
    assert progress["next_juz_pages"] == 0.0
