"""Madani Mushaf 1405 ayah geometry based progress calculations.

Coordinates are bounding boxes, not exact glyph ink masks. Fractions are
therefore geometric estimates. Source: GitCreativeCode/quran-ayah-coords,
CC BY-SA 4.0.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable

_GEOMETRY_PATH = Path(__file__).with_name("mushaf_ayah_geometry.json")


def load_geometry(path: Path = _GEOMETRY_PATH):
    """Return (ayah-area map, page map), keyed by (surah, ayah)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("license") != "CC-BY-SA-4.0":
        raise ValueError("Unsupported or unlicensed Mushaf geometry dataset")
    areas, pages = {}, {}
    for page_data in data.get("pages", []):
        page = int(page_data["page"])
        for item in page_data.get("ayah_areas", []):
            key = (int(item["surah"]), int(item["ayah"]))
            areas[key] = int(item["area"])
            pages[key] = page
    return areas, pages


def _ordinal(surah: int, ayah: int, counts: list[int]) -> int:
    if not 1 <= surah <= len(counts) or not 1 <= ayah <= counts[surah - 1]:
        raise ValueError(f"Invalid ayah coordinate: {surah}:{ayah}")
    return sum(counts[:surah - 1]) + ayah - 1


def calculate_juz_page_progress(
    covered_ranges: Iterable[tuple[int, int]],
    juz_interval: tuple[int, int],
    surah_counts: list[int],
    geometry,
    anchor_ordinal: int | None = None,
) -> float:
    """Cumulative page-equivalents for this Juz.

    When the app starts mid-curriculum, the curriculum portion before the
    first recorded New Lesson (anchor_ordinal) is treated as historically
    completed. From the anchor onward, only contiguous recorded Ayahs count.
    """
    start, end = juz_interval
    area_by_ayah, page_by_ayah = geometry
    covered: set[int] = set()
    for left, right in covered_ranges:
        lo, hi = max(start, min(left, right)), min(end, max(left, right))
        if lo <= hi:
            covered.update(range(lo, hi + 1))

    # Curriculum: descending Surah number, ascending Ayah within each Surah.
    ordered = []
    for surah in range(len(surah_counts), 0, -1):
        for ayah in range(1, surah_counts[surah - 1] + 1):
            ordinal = _ordinal(surah, ayah, surah_counts)
            if start <= ordinal <= end:
                ordered.append(ordinal)
    sequential: set[int] = set()
    if anchor_ordinal is not None and anchor_ordinal in ordered:
        anchor_index = ordered.index(anchor_ordinal)
        # The app was introduced after the student had already progressed
        # through this part of the active Juz. Preserve that prior study.
        sequential.update(ordered[:anchor_index])

    for ordinal in ordered:
        if ordinal not in covered:
            page_totals = {}
            page_done = {}
            for key, area in area_by_ayah.items():
                key_ord = _ordinal(key[0], key[1], surah_counts)
                if key_ord in ordered:
                    page = page_by_ayah[key]
                    page_totals[page] = page_totals.get(page, 0) + area
                    if key_ord in sequential:
                        page_done[page] = page_done.get(page, 0) + area
            return round(sum(
                min(1.0, page_done.get(page, 0) / total)
                for page, total in page_totals.items() if total > 0
            ), 4)
        sequential.add(ordinal)

    page_totals, page_done = {}, {}
    for key, area in area_by_ayah.items():
        ordinal = _ordinal(key[0], key[1], surah_counts)
        if ordinal in ordered:
            page = page_by_ayah[key]
            page_totals[page] = page_totals.get(page, 0) + area
            if ordinal in sequential:
                page_done[page] = page_done.get(page, 0) + area
    return round(sum(
        min(1.0, page_done.get(page, 0) / total)
        for page, total in page_totals.items() if total > 0
    ), 4)
