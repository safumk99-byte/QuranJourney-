import main

def login(client):
    response = client.post("/auth/login", json={
        "login_id": "test_teacher",
        "password": "Test-Teacher-Password-123!",
    })
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}

def test_save_audio_answer_through_audio_endpoint(client, monkeypatch):
    headers = login(client)
    student = client.post(
        "/students",
        headers=headers,
        json={"student_code": "AUDIO-001", "name": "Audio Student"},
    ).json()
    student_id = student["id"]
    client.post(
        f"/students/{student_id}/challenge/ranges",
        headers=headers,
        json={"start_juz": 2, "end_juz": 2, "status": "Learning"},
    )
    monkeypatch.setattr(main, "_juz_ayah_refs", lambda juz: [
        {"surah": 2, "surah_name": "Al-Baqarah", "ayah": n, "text": f"Ayah {n}"}
        for n in range(1, 10)
    ])
    generated = client.post(
        f"/students/{student_id}/challenge/generate/2026-10-26",
        headers=headers,
    )
    assert generated.status_code == 200, generated.text
    response = client.put(
        f"/students/{student_id}/challenge/sessions/2026-10-26/audio/1",
        headers=headers,
        json={"audio_base64": "dGVzdC1hdWRpbw==", "audio_type": "audio/webm"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["saved"] is True
    sessions = client.get(f"/students/{student_id}/challenge/sessions", headers=headers)
    question = next(s for s in sessions.json() if s["date"] == "2026-10-26")["q"][0]
    assert question["submitted"] is True
    assert question["audio_base64"] == "dGVzdC1hdWRpbw=="
