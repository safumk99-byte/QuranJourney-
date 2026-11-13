from mushaf_geometry import calculate_juz_page_progress


COUNTS = [2, 2, 2]
GEOMETRY = (
    {(3, 1): 10, (3, 2): 10, (2, 1): 10, (2, 2): 10},
    {(3, 1): 1, (3, 2): 1, (2, 1): 2, (2, 2): 2},
)
# Juz interval begins at 2:1 and ends at 3:2 in Quran ordinal order.
INTERVAL = (2, 5)


def test_reverse_surah_curriculum_counts_first_surah_in_order():
    assert calculate_juz_page_progress([(4, 5)], INTERVAL, COUNTS, GEOMETRY) == 1.0


def test_later_surah_does_not_count_before_first_curriculum_surah():
    assert calculate_juz_page_progress([(2, 2)], INTERVAL, COUNTS, GEOMETRY) == 0.0


def test_progress_stops_at_first_missing_ayah():
    assert calculate_juz_page_progress([(4, 4)], INTERVAL, COUNTS, GEOMETRY) == 0.5


def test_overlapping_ranges_are_deduplicated():
    assert calculate_juz_page_progress([(2, 5), (2, 5)], INTERVAL, COUNTS, GEOMETRY) == 2.0



def test_progress_starts_from_first_recorded_ayah_when_app_begins_mid_juz():
    assert calculate_juz_page_progress(
        [(3, 1), (3, 2), (2, 1)], INTERVAL, COUNTS, GEOMETRY,
        anchor_ordinal=4,
    ) == 2.0


def test_missing_ayah_after_anchor_still_stops_progress():
    assert calculate_juz_page_progress(
        [(3, 1), (2, 1)], INTERVAL, COUNTS, GEOMETRY,
        anchor_ordinal=4,
    ) == 0.5
