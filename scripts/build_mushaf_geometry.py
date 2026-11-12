#!/usr/bin/env python3
"""Build Madani 1405 ayah-position geometry for QuranJourney's curriculum.

Source: GitCreativeCode/quran-ayah-coords (CC BY-SA 4.0).
This stores ayah bounding boxes, not exact ink masks; page fractions are
bounding-box area estimates and must be labelled accordingly in the UI.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

COORDS_BASE = "https://raw.githubusercontent.com/GitCreativeCode/quran-ayah-coords/main/glyph_coords"
PAGE_MAP_URL = "https://raw.githubusercontent.com/safumk99-byte/QuranJourney-/main/backend/quran_page_map.json"
SOURCE = "https://github.com/GitCreativeCode/quran-ayah-coords"
LICENSE = "CC-BY-SA-4.0"


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": "QuranJourney-MushafGeometry/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def rectangle_union_area(rectangles: list[tuple[int, int, int, int]]) -> int:
    """Exact union area of axis-aligned integer rectangles."""
    if not rectangles:
        return 0
    xs = sorted({x for rect in rectangles for x in (rect[0], rect[1])})
    area = 0
    for left, right in zip(xs, xs[1:]):
        if right <= left:
            continue
        spans = sorted(
            (y1, y2) for x1, y1, x2, y2 in rectangles
            if x1 < right and x2 > left and y2 > y1
        )
        covered_y = 0
        if spans:
            low, high = spans[0]
            for start, end in spans[1:]:
                if start > high:
                    covered_y += high - low
                    low, high = start, end
                else:
                    high = max(high, end)
            covered_y += high - low
        area += (right - left) * covered_y
    return area


def validate_page(page_number: int, rows: list[dict], expected_start: list[int]) -> None:
    if not rows:
        raise ValueError(f"Page {page_number}: no coordinate rows")
    if any(int(row.get("page_number", -1)) != page_number for row in rows):
        raise ValueError(f"Page {page_number}: mismatched page_number")
    first = min(rows, key=lambda row: (row["line_number"], row["position"]))
    if [first["surah_number"], first["ayah_number"]] != expected_start:
        raise ValueError(
            f"Page {page_number}: first ayah mismatch; "
            f"expected {expected_start}, got {[first['surah_number'], first['ayah_number']]}"
        )
    seen = set()
    for row in rows:
        key = tuple(row[k] for k in (
            "line_number", "surah_number", "ayah_number", "position",
            "min_x", "max_x", "min_y", "max_y",
        ))
        if key in seen:
            raise ValueError(f"Page {page_number}: duplicate coordinate row {key}")
        seen.add(key)
        if row["min_x"] >= row["max_x"] or row["min_y"] >= row["max_y"]:
            raise ValueError(f"Page {page_number}: invalid bounding box {key}")


def build_dataset(output: Path, start_surah: int = 46, start_ayah: int = 1) -> dict:
    page_map_data = fetch_json(PAGE_MAP_URL)
    page_starts = page_map_data["pages"]
    # Page entries are [page_number, start_surah, start_ayah]. Select the
    # page containing the curriculum start, which may begin before the exact
    # starting ayah (e.g. Juz 26 starts at 46:1 on a page beginning at 45:33).
    target = (start_surah, start_ayah)
    page_number = 1
    for page, surah, ayah in page_starts:
        if (surah, ayah) <= target:
            page_number = page
        else:
            break

    pages = []
    for page, surah, ayah in page_starts:
        if page < page_number:
            continue
        rows = fetch_json(f"{COORDS_BASE}/{page}.json")
        validate_page(page, rows, [surah, ayah])
        grouped: dict[tuple[int, int], list[tuple[int, int, int, int]]] = {}
        all_boxes = []
        ayah_boxes = []
        for row in rows:
            box = (row["min_x"], row["min_y"], row["max_x"], row["max_y"])
            all_boxes.append(box)
            grouped.setdefault((row["surah_number"], row["ayah_number"]), []).append(box)
            ayah_boxes.append({
                "surah": row["surah_number"],
                "ayah": row["ayah_number"],
                "line": row["line_number"],
                "position": row["position"],
                "box": list(box),
            })
        page_area = rectangle_union_area(all_boxes)
        ayah_area = [
            {"surah": surah, "ayah": ayah, "area": rectangle_union_area(boxes)}
            for (surah, ayah), boxes in sorted(grouped.items())
        ]
        pages.append({
            "page": page,
            "page_area": page_area,
            "ayah_areas": ayah_area,
            "ayah_boxes": ayah_boxes,
        })

    result = {
        "schema_version": 1,
        "mushaf": "Madani 1405 (King Fahd Complex coordinate source)",
        "source": SOURCE,
        "license": LICENSE,
        "method": "Sum of each covered ayah's bounding-box union area divided by page bounding-box union area",
        "accuracy_note": "Geometric estimate, not exact ink-area measurement.",
        "pages": pages,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="backend/mushaf_ayah_geometry.json")
    args = parser.parse_args()
    dataset = build_dataset(Path(args.output))
    print(f"Built {len(dataset['pages'])} pages into {args.output}")
