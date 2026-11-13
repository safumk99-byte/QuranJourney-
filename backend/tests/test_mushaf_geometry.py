import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_mushaf_geometry.py"
SPEC = importlib.util.spec_from_file_location("build_mushaf_geometry", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
rectangle_union_area = MODULE.rectangle_union_area


def test_rectangle_union_area_counts_non_overlapping_ayah_segments():
    boxes = [(0, 0, 10, 10), (10, 0, 20, 10)]
    assert rectangle_union_area(boxes) == 200


def test_rectangle_union_area_does_not_double_count_overlaps():
    boxes = [(0, 0, 10, 10), (5, 0, 15, 10)]
    assert rectangle_union_area(boxes) == 150


def test_rectangle_union_area_handles_vertical_and_partial_overlap():
    boxes = [(0, 0, 10, 10), (0, 5, 10, 15), (10, 0, 20, 10)]
    assert rectangle_union_area(boxes) == 250
