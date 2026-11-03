#!/usr/bin/env python3
"""Verify Quran for Android MADANI_1405 images and matching ayah-info DBs."""
from __future__ import annotations

import io
import sqlite3
import tempfile
import urllib.request
import zipfile

BASE = "https://android.quran.com/data"
WIDTHS = (480, 800)
PAGES = (1, 2, 3, 604)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "QuranJourney-Mushaf-Source-Check/1.0"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read()


def png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError("Official page asset is not a valid PNG.")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def verify_width(width: int) -> None:
    image_sizes = {}
    for page in PAGES:
        image = fetch(f"{BASE}/width_{width}/page{page:03d}.png")
        actual_width, height = png_dimensions(image)
        if actual_width != width or height <= 0:
            raise RuntimeError(
                f"Unexpected page {page} dimensions for width {width}: "
                f"{actual_width}x{height}"
            )
        image_sizes[page] = (actual_width, height)
        print(
            f"PASS: Madani page {page:03d} at width {width} "
            f"({actual_width}x{height}, {len(image)} bytes)"
        )

    archive_bytes = fetch(
        f"{BASE}/databases/ayahinfo/ayahinfo_{width}.zip"
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        candidates = [
            name for name in archive.namelist()
            if name.lower().endswith(".db") and "__macosx" not in name.lower()
        ]
        if not candidates:
            raise RuntimeError(f"Width {width} ayah-info ZIP contains no SQLite database.")
        database_bytes = archive.read(candidates[0])

    with tempfile.NamedTemporaryFile(suffix=".db") as database_file:
        database_file.write(database_bytes)
        database_file.flush()
        connection = sqlite3.connect(f"file:{database_file.name}?mode=ro", uri=True)
        try:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "glyphs" not in tables:
                raise RuntimeError(f"Width {width} database has no glyph coordinate table.")

            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(glyphs)")
            }
            required_columns = {
                "page_number", "line_number", "sura_number", "ayah_number",
                "min_x", "min_y", "max_x", "max_y",
            }
            if not required_columns.issubset(columns):
                raise RuntimeError(
                    f"Width {width} database is missing glyph columns: "
                    f"{sorted(required_columns - columns)}"
                )

            distinct_ayahs = connection.execute(
                "SELECT COUNT(DISTINCT CAST(sura_number AS TEXT) || ':' || CAST(ayah_number AS TEXT)) FROM glyphs"
            ).fetchone()[0]
            if distinct_ayahs != 6236:
                raise RuntimeError(
                    f"Width {width} expected 6,236 ayahs, found {distinct_ayahs}"
                )
            page_count, first_page, last_page = connection.execute(
                "SELECT COUNT(DISTINCT page_number), MIN(page_number), MAX(page_number) FROM glyphs"
            ).fetchone()
            if (page_count, first_page, last_page) != (604, 1, 604):
                raise RuntimeError(
                    f"Width {width} expected coordinates for all 604 pages, "
                    f"found {page_count} pages from {first_page} to {last_page}"
                )
            image_height = image_sizes[1][1]
            if any(size[1] != image_height for size in image_sizes.values()):
                raise RuntimeError(f"Width {width} page image heights are inconsistent")
            all_bounds = connection.execute(
                "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) FROM glyphs"
            ).fetchone()
            left, top, right, bottom = all_bounds
            if left < 0 or top < 0 or right > width or bottom > image_height:
                raise RuntimeError(
                    f"Width {width} all-page coordinates {all_bounds} exceed "
                    f"image dimensions {width}x{image_height}"
                )
            print(
                f"PASS: width {width} has ayah coordinates on all 604 pages "
                f"within {width}x{image_height} image bounds"
            )

            for page in PAGES:
                count = connection.execute(
                    "SELECT COUNT(*) FROM glyphs WHERE page_number = ?", (page,)
                ).fetchone()[0]
                if count <= 0:
                    raise RuntimeError(
                        f"Width {width} has no glyph coordinates for page {page}"
                    )
                image_width, image_height = image_sizes[page]
                bounds = connection.execute(
                    "SELECT MIN(min_x), MIN(min_y), MAX(max_x), MAX(max_y) "
                    "FROM glyphs WHERE page_number = ?", (page,)
                ).fetchone()
                left, top, right, bottom = bounds
                if left < 0 or top < 0 or right > image_width or bottom > image_height:
                    raise RuntimeError(
                        f"Width {width} page {page} coordinate bounds {bounds} "
                        f"do not fit image {image_width}x{image_height}"
                    )
                print(
                    f"PASS: width {width} page {page:03d} has {count} "
                    f"glyph rows within image bounds"
                )

            print(
                f"PASS: width {width} official ayah-info DB ({len(database_bytes)} bytes), "
                f"{distinct_ayahs} ayahs; optional tables: "
                f"{', '.join(sorted(tables - {'glyphs'})) or 'none'}"
            )
        finally:
            connection.close()


def main() -> None:
    for width in WIDTHS:
        verify_width(width)


if __name__ == "__main__":
    main()
