from datetime import date

import main


def _student(db):
    student = main.Student(
        student_code="TARGET-001",
        name="Target Test Student",
        class_name="Hifz A",
        total_pages=604,
        completed_pages=0,
        journey_start_date=date(2026, 11, 1),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


def test_weekly_target_excludes_friday_and_no_class_days(client):
    with main.SessionLocal() as db:
        student = _student(db)
        db.add_all([
            main.CalendarHoliday(holiday_date=date(2026, 11, 10), reason="Class holiday", class_name="Hifz A"),
            main.CalendarHoliday(holiday_date=date(2026, 11, 13), reason="Friday closure"),
            main.CalendarHoliday(holiday_date=date(2026, 11, 11), reason="Other class", class_name="Hifz B"),
        ])
        db.commit()

        result = main._target_period(
            student, "week", date(2026, 11, 11),
            db.query(main.CalendarHoliday).all(), db,
        )

        # Nov 7–12 has six calendar days, minus Tuesday's No Class Day.
        # Friday is outside the weekly period and is never a working day.
        assert result["total_working_days"] == 5
        assert result["no_class_days"] == 1
        assert result["target"] == round(result["base_target"] + result["carry_in"], 2)


def test_monthly_target_excludes_fridays_and_all_applicable_no_class_days(client):
    with main.SessionLocal() as db:
        student = _student(db)
        db.add_all([
            main.CalendarHoliday(holiday_date=date(2026, 11, 3), reason="Global closure"),
            main.CalendarHoliday(holiday_date=date(2026, 11, 10), reason="Class closure", class_name="Hifz A"),
            main.CalendarHoliday(holiday_date=date(2026, 11, 13), reason="Friday closure"),
            main.CalendarHoliday(holiday_date=date(2026, 11, 11), reason="Other class", class_name="Hifz B"),
        ])
        db.commit()

        result = main._target_period(
            student, "month", date(2026, 11, 11),
            db.query(main.CalendarHoliday).all(), db,
        )

        # Reset starts Nov 2: 23 Saturday–Thursday dates remain in Nov.
        # Two applicable non-Friday No Class Days are excluded; the Friday
        # holiday is not double-counted and the other-class holiday is ignored.
        assert result["total_working_days"] == 21
        assert result["no_class_days"] == 2
        assert result["target"] == round(result["base_target"] + result["carry_in"], 2)
