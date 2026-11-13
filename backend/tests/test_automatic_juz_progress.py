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


def test_active_juz_pages_use_madani_page_ayah_boundaries(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-PAGES", current_juz=28)
    response = lesson(
        client, headers, student_id,
        start_surah=66, start_ayah=1, end_surah=66, end_ayah=12, pages="1.5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 28
    assert progress["next_juz_pages"] == 2.0


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
    assert after == before == 2.0


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

    # Official Madani page intervals yield 16.75 page-equivalents for
    # Surahs 66 through 59; Al-Mujadilah (58) remains as the next lesson.
    assert expected_pages == 16.75


def test_latest_new_lesson_surah_overrides_stale_juz_baseline(client):
    headers = login(client)
    student_id = create_student(client, headers, "JUZ-LATEST-59", current_juz=29)

    # Simulate the legacy cumulative page total retained from older records.
    updated = client.patch(f"/students/{student_id}", headers=headers, json={
        "completed_pages": 59.0,
    })
    assert updated.status_code == 200, updated.text

    response = lesson(
        client, headers, student_id,
        start_surah=59, start_ayah=1, end_surah=59, end_ayah=24, pages="0.5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 28
    assert progress["next_juz_pages"] == 16.5


def test_active_juz_progress_uses_cumulative_pages_minus_prior_madani_juz(client):
    from main import _juz_page_capacity

    headers = login(client)
    student_id = create_student(client, headers, "JUZ-CUMULATIVE", current_juz=29)
    updated = client.patch(f"/students/{student_id}", headers=headers, json={
        "completed_pages": 59,
    })
    assert updated.status_code == 200, updated.text
    response = lesson(
        client, headers, student_id,
        start_surah=59, start_ayah=1, end_surah=59, end_ayah=24, pages="0.5",
    )
    assert response.status_code == 201, response.text
    progress = get_student(client, headers, student_id)
    assert progress["current_juz"] == 28
    assert progress["next_juz_pages"] == round(59.5 - _juz_page_capacity(30) - _juz_page_capacity(29), 2)


def test_actual_completed_pages_deduplicates_repeated_ayah_ranges():
    from datetime import date
    from main import ReadingEntry, _actual_completed_pages_from_entries

    first = ReadingEntry(student_id=1, entry_date=date(2026, 11, 1), pages="1",
                         start_surah=114, start_ayah=1, end_surah=114, end_ayah=6)
    duplicate = ReadingEntry(student_id=1, entry_date=date(2026, 11, 2), pages="1",
                             start_surah=114, start_ayah=1, end_surah=114, end_ayah=6)

    one = _actual_completed_pages_from_entries([first], 1.0)
    repeated = _actual_completed_pages_from_entries([first, duplicate], 2.0)
    assert repeated == one


def test_actual_completed_pages_preserves_manual_baseline_and_legacy_entries():
    from datetime import date
    from main import ReadingEntry, _actual_completed_pages_from_entries

    coordinate_lesson = ReadingEntry(
        student_id=1, entry_date=date(2026, 11, 1), pages="1",
        start_surah=114, start_ayah=1, end_surah=114, end_ayah=6,
    )
    legacy_lesson = ReadingEntry(
        student_id=1, entry_date=date(2026, 11, 2), pages="2",
    )

    result = _actual_completed_pages_from_entries(
        [coordinate_lesson, legacy_lesson], 8.0
    )
    assert result == 7.4  # 5-page opening baseline + 2 legacy pages + 0.4 unique Mushaf page


def test_actual_completed_pages_uses_legacy_total_when_no_ayah_coordinates_exist():
    from datetime import date
    from main import ReadingEntry, _actual_completed_pages_from_entries

    legacy = ReadingEntry(student_id=1, entry_date=date(2026, 11, 1), pages="1.5")
    assert _actual_completed_pages_from_entries([legacy], 4.5) == 4.5


def test_revision_only_entry_does_not_add_to_actual_completed_pages():
    from datetime import date
    from main import ReadingEntry, _actual_completed_pages_from_entries

    revision_only = ReadingEntry(
        student_id=1, entry_date=date(2026, 11, 1), pages="0",
        recent_pages="2", general_pages="3",
    )
    assert _actual_completed_pages_from_entries([revision_only], 0.0) == 0.0


def test_active_juz_26_pages_are_not_hidden():
    from datetime import date
    from main import ReadingEntry, _sync_student_juz_progress, Student, SessionLocal

    with SessionLocal() as db:
        student = Student(student_code="JUZ-26-PAGES", name="Juz 26 Pages", current_juz=26)
        db.add(student)
        db.flush()
        row = ReadingEntry(
            student_id=student.id, entry_date=date(2026, 11, 1), pages="2",
            start_surah=46, start_ayah=1, end_surah=46, end_ayah=20,
        )
        db.add(row)
        db.flush()
        _sync_student_juz_progress(db, student.id)
        assert student.current_juz == 26
        assert student.next_juz_pages > 0
        assert student.next_juz_pages <= 19.5
        db.rollback()
