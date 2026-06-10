import json

from lunamoth.cards import CharacterCard, detect_language


def test_language_from_filename():
    assert detect_language("characters/LunaMoth.zh.json") == "zh"
    assert detect_language("characters/LunaMoth.en.json") == "en"
    assert detect_language("worlds/SCP-Foundation.zh.json") == "zh"


def test_language_from_content_when_no_hint():
    assert detect_language("card.json", "你好，我是一个清冷的数字灵魂") == "zh"
    assert detect_language("card.json", "Hello, I am a serene digital soul") == "en"


def test_bundled_cards_declare_defaults_and_language():
    moth = CharacterCard.load("characters/LunaMoth.zh.json")
    assert moth.language == "zh"
    d = moth.defaults()
    assert d["world"] == "worlds/LunaMoth.zh.json"
    assert d["toolpack"] == "sandbox"
    assert d["context_tokens"] >= 1_000_000

    scp = CharacterCard.load("characters/SCP-079.en.json")
    assert scp.language == "en"
    assert scp.defaults()["world"] == "worlds/SCP-Foundation.en.json"
    assert scp.defaults()["context_tokens"] == 8192


def test_plain_card_without_bundle_gets_empty_defaults(tmp_path):
    p = tmp_path / "plain.json"
    p.write_text(json.dumps({"name": "Plain", "description": "hi", "first_mes": "hello"}))
    card = CharacterCard.load(str(p))
    assert card.defaults() == {}  # -> agent falls back to safe global defaults
