from __future__ import annotations

import asyncio

from tests.support import install_dependency_stubs

install_dependency_stubs()

from backend.tools import sound


def test_blocked_sound_terms_are_rejected():
    result = asyncio.run(sound.play_sound({"query": "murder scream"}))

    assert result["sounds"] == []
    assert "different sound" in result["text"]


def test_extract_openverse_sounds_prefers_direct_preview_urls_over_api_downloads():
    data = {
        "results": [
            {
                "title": "Bird chirp",
                "source": "jamendo",
                "url": "https://cdn.example.org/bird-original.wav",
            },
            {
                "title": "Cow moo",
                "source": "freesound",
                "url": "https://cdn.example.org/cow-preview.mp3",
                "filetype": "mp3",
                "creator": "Farmer Ada",
                "foreign_landing_url": "https://example.org/cow",
                "alt_files": [
                    {"filetype": "json", "url": "https://cdn.example.org/cow.json"},
                    {
                        "filetype": "wav",
                        "url": "https://freesound.org/apiv2/sounds/123/download/",
                    },
                ],
            },
        ]
    }

    sounds = sound._extract_openverse_sounds(data, "cow moo")

    assert sounds[0] == {
        "url": "https://cdn.example.org/cow-preview.mp3",
        "title": "Cow moo",
        "alt": "Cow moo",
        "autoplay": True,
        "credit": "Farmer Ada",
        "page_url": "https://example.org/cow",
    }
    assert sounds[1]["url"] == "https://cdn.example.org/bird-original.wav"


def test_extract_freesound_sounds_prefers_hq_preview_urls():
    data = {
        "results": [
            {
                "name": "Cat Meow Close",
                "username": "SoundMaker",
                "url": "https://freesound.org/people/SoundMaker/sounds/12345/",
                "previews": {
                    "preview-hq-mp3": "https://cdn.freesound.org/previews/123/12345-hq.mp3",
                    "preview-lq-mp3": "https://cdn.freesound.org/previews/123/12345-lq.mp3",
                },
            }
        ]
    }

    sounds = sound._extract_freesound_sounds(data, "cat meow")

    assert sounds == [
        {
            "url": "https://cdn.freesound.org/previews/123/12345-hq.mp3",
            "title": "Cat Meow Close",
            "alt": "Cat Meow Close",
            "autoplay": True,
            "credit": "SoundMaker",
            "page_url": "https://freesound.org/people/SoundMaker/sounds/12345/",
        }
    ]


def test_pick_audio_url_falls_back_to_direct_alt_file_when_primary_url_missing():
    result = {
        "title": "Bird chirp",
        "alt_files": [
            {"filetype": "json", "url": "https://cdn.example.org/meta.json"},
            {"filetype": "ogg", "url": "https://cdn.example.org/bird.ogg"},
        ],
    }

    assert sound._pick_audio_url(result) == "https://cdn.example.org/bird.ogg"


def test_play_sound_uses_cache_for_repeat_queries(monkeypatch):
    sound._SOUND_CACHE.clear()
    calls = []

    async def fake_search_freesound_audio(query):
        raise AssertionError("Freesound should not be queried without an API key")

    async def fake_search_openverse_audio(query):
        calls.append(query)
        return {
            "sounds": [
                {"url": "https://cdn.example.org/cow.mp3", "title": "Cow moo"}
            ]
        }

    monkeypatch.setattr(sound, "FREESOUND_API_KEY", "")
    monkeypatch.setattr(sound, "_search_freesound_audio", fake_search_freesound_audio)
    monkeypatch.setattr(sound, "_search_openverse_audio", fake_search_openverse_audio)

    first = asyncio.run(sound.play_sound({"query": "cow moo"}))
    second = asyncio.run(sound.play_sound({"query": "Cow Moo"}))

    assert first == second
    assert calls == ["cow moo"]


def test_play_sound_returns_text_when_no_sound_is_found(monkeypatch):
    sound._SOUND_CACHE.clear()

    async def fake_search_freesound_audio(query):
        raise AssertionError("Freesound should not be queried without an API key")

    async def fake_search_openverse_audio(query):
        return {"sounds": []}

    monkeypatch.setattr(sound, "FREESOUND_API_KEY", "")
    monkeypatch.setattr(sound, "_search_freesound_audio", fake_search_freesound_audio)
    monkeypatch.setattr(sound, "_search_openverse_audio", fake_search_openverse_audio)

    result = asyncio.run(sound.play_sound({"query": "dinosaur roar"}))

    assert result["sounds"] == []
    assert "couldn't find a sound" in result["text"]


def test_play_sound_prefers_freesound_when_api_key_is_configured(monkeypatch):
    sound._SOUND_CACHE.clear()
    calls = []

    async def fake_search_freesound_audio(query):
        calls.append(("freesound", query))
        return {
            "sounds": [
                {"url": "https://cdn.freesound.org/previews/123/cat.mp3", "title": "Cat meow"}
            ]
        }

    async def fake_search_openverse_audio(query):
        calls.append(("openverse", query))
        return {
            "sounds": [
                {"url": "https://cdn.example.org/cat.mp3", "title": "Cat meow"}
            ]
        }

    monkeypatch.setattr(sound, "FREESOUND_API_KEY", "test-key")
    monkeypatch.setattr(sound, "_search_freesound_audio", fake_search_freesound_audio)
    monkeypatch.setattr(sound, "_search_openverse_audio", fake_search_openverse_audio)

    result = asyncio.run(sound.play_sound({"query": "cat meow"}))

    assert result["sounds"][0]["url"] == "https://cdn.freesound.org/previews/123/cat.mp3"
    assert calls == [("freesound", "cat meow")]
