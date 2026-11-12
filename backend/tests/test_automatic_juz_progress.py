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


def lesson(client, headers, student_id, *, start_surah=114, start_ayah=1, end_surah=114, end_ayah=5, pages="1"):
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


def test_active_juz_28_progress_is_counted_in_juz_28_not_27(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-028", current_juz=28)
    response = lesson(
        client, headers, student_id,
        start_surah=66, start_ayah=1, end_surah=66, end_ayah=12, pages="1.5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 28
    assert progress["next_juz_pages"] > 0


def test_active_juz_pages_use_teacher_entered_new_lesson_pages_not_mushaf_ayah_fraction(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-PAGES", current_juz=28)
    response = lesson(
        client, headers, student_id,
        start_surah=66, start_ayah=1, end_surah=66, end_ayah=12, pages="1.5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 28
    assert progress["next_juz_pages"] == 1.5


def test_overlapping_new_lesson_ranges_do_not_double_count_pages(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-OVERLAP", current_juz=28)
    first = lesson(
        client, headers, student_id,
        start_surah=66, start_ayah=1, end_surah=66, end_ayah=12, pages="1.5",
    )
    assert first.status_code == 201, first.text
    before = get_student(client, headers, student_id)["next_juz_pages"]
    second = lesson(
        client, headers, student_id,
        start_surah=66, start_ayah=1, end_surah=66, end_ayah=12, pages="1.5",
    )
    assert second.status_code == 201, second.text
    after = get_student(client, headers, student_id)["next_juz_pages"]
    assert after == before == 1.5


def test_completed_juz_29_advances_to_juz_28_and_counts_madani_pages():
    from main import SURAH_AYAH_COUNTS, _QURAN_PAGE_INTERVALS, _QURAN_JUZ_INTERVALS, _ayah_ordinal

    # Official curriculum sequence: complete Juz 29 (77 down to 67),
    # then complete Juz 28 through Al-Hashr (66 down to 59).
    covered = []
    for surah in range(77, 66, -1):
        covered.append((_ayah_ordinal(surah, 1),
                        _ayah_ordinal(surah, SURAH_AYAH_COUNTS[surah - 1])))
    for surah in range(66, 58, -1):
        covered.append((_ayah_ordinal(surah, 1),
                        _ayah_ordinal(surah, SURAH_AYAH_COUNTS[surah - 1])))

    juz28 = next((left, right) for number, left, right in _QURAN_JUZ_INTERVALS if number == 28)
    expected_pages = 0.0
    for _page, page_left, page_right in _QURAN_PAGE_INTERVALS:
        left, right = max(juz28[0], page_left), min(juz28[1], page_right)
        if left > right:
            continue
        total = right - left + 1
        amount = sum(max(0, min(right, b) - max(left, a) + 1) for a, b in covered)
        expected_pages += amount / total

    # Juz 28's first eight curriculum Surahs (66 through 59) cover 16 full
    # Madani pages; Al-Mujadilah (58) remains as the next lesson.
    assert expected_pages == 16.0
