def login(client):
    response = client.post("/auth/login", json={
        "login_id": "test_teacher",
        "password": "Test-Teacher-Password-123!",
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def create_student(client, headers, code="JUZ-001", current_juz=30):
    response = client.post("/students", headers=headers, json={
        "student_code": code,
        "name": "Automatic Juz Test",
        "current_juz": current_juz,
        "next_juz_pages": 0,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def lesson(client, headers, student_id, *, start_surah=66, start_ayah=1, end_surah=66, end_ayah=5, pages="1"):
    return client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-11-01T12:00:00",
        "start_surah": start_surah,
        "start_ayah": start_ayah,
        "end_surah": end_surah,
        "end_ayah": end_ayah,
        "new_lesson": "New Lesson",
        "pages": pages,
        "recent_pages": "0",
        "general_pages": "0",
    })


def get_student(client, headers, student_id):
    response = client.get("/students", headers=headers)
    assert response.status_code == 200
    return next(row for row in response.json() if row["id"] == student_id)


def test_progress_tracks_active_juz_30_and_deduplicates_ayahs(client):
    headers = login(client)
    student_id = create_student(client, headers)

    first = lesson(client, headers, student_id)
    assert first.status_code == 201, first.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 30
    assert progress["next_juz_pages"] > 0

    second = lesson(client, headers, student_id)
    assert second.status_code == 201, second.text
    duplicate_progress = get_student(client, headers, student_id)
    assert duplicate_progress["next_juz_pages"] == progress["next_juz_pages"]


def test_juz_26_is_the_final_curriculum_unit(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-002", current_juz=26)
    # A lesson outside the active final Juz must not change its progress.
    response = lesson(
        client, headers, student_id,
        start_surah=44, start_ayah=1, end_surah=44, end_ayah=59, pages="5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 26
    assert progress["next_juz_pages"] == 0.0


def test_legacy_progress_values_normalize_to_real_juz_numbers():
    from main import _normalize_curriculum_juz

    assert [_normalize_curriculum_juz(i) for i in range(1, 6)] == [30, 29, 28, 27, 26]
    assert _normalize_curriculum_juz(30) == 30


def test_edit_and_delete_recalculate_progress_juz(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-003")
    created = lesson(client, headers, student_id)
    assert created.status_code == 201, created.text
    entry_id = created.json()["id"]

    edited = client.patch(f"/students/{student_id}/reading/{entry_id}", headers=headers, json={
        "end_ayah": 6,
    })
    assert edited.status_code == 200, edited.text
    edited_progress = get_student(client, headers, student_id)["next_juz_pages"]
    assert edited_progress > 0

    deleted = client.delete(f"/students/{student_id}/reading/{entry_id}", headers=headers)
    assert deleted.status_code == 204
    final = get_student(client, headers, student_id)
    assert final["current_juz"] == 30
    assert final["next_juz_pages"] == 0.0


def test_revision_only_entry_does_not_change_progress_juz(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-004")
    response = client.post(f"/students/{student_id}/reading", headers=headers, json={
        "entry_date": "2026-11-01T12:00:00",
        "recent_start_surah": 67,
        "recent_start_ayah": 1,
        "recent_end_surah": 67,
        "recent_end_ayah": 5,
        "recent_revision": "Al-Mulk",
        "pages": "0",
        "recent_pages": "1",
        "general_pages": "0",
    })
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 30
    assert progress["next_juz_pages"] == 0.0


def test_legacy_progress_values_normalize_to_real_juz_numbers():
    from main import _normalize_curriculum_juz

    assert [_normalize_curriculum_juz(i) for i in range(1, 6)] == [30, 29, 28, 27, 26]
    assert _normalize_curriculum_juz(30) == 30
