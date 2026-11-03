import main


def test_official_mushaf_page_endpoint_returns_png(client, monkeypatch):
    monkeypatch.setattr(main, "_load_mushaf_page_image", lambda page, width: b"png-test-data")
    response = client.get("/quran/mushaf/page/1?width=480")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-mushaf-edition"] == "MADANI_1405"
    assert response.content == b"png-test-data"


def test_mushaf_page_endpoint_validates_page_and_width(client):
    assert client.get("/quran/mushaf/page/0?width=480").status_code == 404
    assert client.get("/quran/mushaf/page/605?width=480").status_code == 404
    assert client.get("/quran/mushaf/page/1?width=600").status_code == 400


def test_official_mushaf_ayah_coordinates_endpoint_returns_matching_edition(client, monkeypatch):
    def fake_coordinates(width):
        return {
            "edition": "MADANI_1405",
            "width": width,
            "pages": {
                "1": {
                    "ayahs": [{"surah": 1, "ayah": 1, "rects": [[10, 20, 100, 40]]}],
                    "markers": [{"surah": 1, "ayah": 1, "x": 90, "y": 40}],
                    "headers": [],
                }
            },
        }

    monkeypatch.setattr(main, "_load_mushaf_ayah_coordinates", fake_coordinates)
    response = client.get("/quran/mushaf/page/1/coordinates?width=480")
    assert response.status_code == 200
    payload = response.json()
    assert payload["edition"] == "MADANI_1405"
    assert payload["page"] == 1
    assert payload["width"] == 480
    assert payload["ayahs"][0]["rects"] == [[10, 20, 100, 40]]


def test_mushaf_coordinates_endpoint_returns_404_for_missing_page(client, monkeypatch):
    monkeypatch.setattr(
        main,
        "_load_mushaf_ayah_coordinates",
        lambda width: {"edition": "MADANI_1405", "width": width, "pages": {}},
    )
    response = client.get("/quran/mushaf/page/604/coordinates?width=480")
    assert response.status_code == 404
