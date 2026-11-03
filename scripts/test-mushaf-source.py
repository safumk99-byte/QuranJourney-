#!/usr/bin/env python3
"""Verify the official Quran for Android MADANI_1405 page and ayah-info assets."""
from __future__ import annotations

import io
import sqlite3
import tempfile
import urllib.request
import zipfile

BASE = "https://android.quran.com/data"
WIDTH = 480


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


def main() -> None:
    for page in (1, 2, 3, 604):
        image = fetch(f"{BASE}/width_{WIDTH}/page{page:03d}.png")
        width, height = png_dimensions(image)
        if width != WIDTH or height <= 0:
            raise RuntimeError(f"Unexpected page {page} dimensions: {width}x{height}")
        print(f"PASS: official Madani page {page:03d}.png ({width}x{height}, {len(image)} bytes)")

    archive_bytes = fetch(
        f"{BASE}/databases/ayahinfo/ayahinfo_{WIDTH}.zip"
    )
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        candidates = [
            name for name in archive.namelist()
            if name.lower().endswith(".db") and "__macosx" not in name.lower()
        ]
        if not candidates:
            raise RuntimeError("Official ayah-info ZIP contains no SQLite database.")
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
            required = {"glyphs", "ayah_markers", "sura_headers"}
            if not required.issubset(tables):
                raise RuntimeError(f"Missing ayah-info tables: {sorted(required - tables)}")

            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(glyphs)")
            }
            required_columns = {
                "page_number", "line_number", "sura_number", "ayah_number",
                "min_x", "min_y", "max_x", "max_y",
            }
            if not required_columns.issubset(columns):
                raise RuntimeError(
                    f"Missing glyph coordinate columns: {sorted(required_columns - columns)}"
                )

            distinct_ayahs = connection.execute(
                "SELECT COUNT(DISTINCT CAST(sura_number AS TEXT) || ':' || CAST(ayah_number AS TEXT)) FROM glyphs"
            ).fetchone()[0]
            if distinct_ayahs != 6236:
                raise RuntimeError(f"Expected 6,236 ayahs in glyph data, found {distinct_ayahs}")

            for page in (1, 2, 3, 604):
                count = connection.execute(
                    "SELECT COUNT(*) FROM glyphs WHERE page_number = ?", (page,)
                ).fetchone()[0]
                if count <= 0:
                    raise RuntimeError(f"No ayah glyph coordinates for page {page}")
                print(f"PASS: page {page:03d} has {count} matching glyph-coordinate rows")

            marker_count = connection.execute(
                "SELECT COUNT(*) FROM ayah_markers"
            ).fetchone()[0]
            header_count = connection.execute(
                "SELECT COUNT(*) FROM sura_headers"
            ).fetchone()[0]
            if marker_count <= 0 or header_count <= 0:
                raise RuntimeError("Ayah markers or surah-header positions are missing")
            print(
                f"PASS: official ayah-info database ({len(database_bytes)} bytes), "
                f"{distinct_ayahs} ayahs, {marker_count} markers, {header_count} surah headers"
            )
        finally:
            connection.close()


if __name__ == "__main__":
    main()
