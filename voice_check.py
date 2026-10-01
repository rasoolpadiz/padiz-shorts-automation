# -*- coding: utf-8 -*-
"""Offline check for the Persian narration layer (pipeline.generate_voice).

Verifies - without any API key and without touching YouTube quota - that:
  * Farid/Dilara edge voices map onto the right Gemini voices,
  * Gemini audio (WAV container or raw PCM) is converted to a playable MP3,
  * the styled `speech_metadata` request is sent first, with a plain-text retry,
  * edge-tts still works as the fallback and is used when Gemini cannot answer,
  * a bad key or a fully failing run switches narration to edge-tts for good.

Usage:  python voice_check.py
"""
import os
import sys
import wave
import types as pytypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import pipeline
from google.genai import types as genai_types

FA_TEXT = "آیا می‌دانستید اختاپوس‌ها سه تا قلب دارند و خون آن‌ها آبی است؟\n"
OUT_DIR = os.path.join(pipeline.BASE_DIR, "voice_check")
os.makedirs(OUT_DIR, exist_ok=True)
results = []

# Requests recorded by the offline fake Gemini client.
CALLS = {"models": [], "contents": [], "voices": [], "shapes": []}

# Models the fake client pretends are unavailable (newest-lite and paid-only Pro).
UNAVAILABLE_MODELS = ("gemini-3.8-flash-lite-tts", "gemini-2.5-pro-preview-tts")


def record(model, contents, config):
    voice_cfg = config.speech_config.voice_config
    prebuilt = voice_cfg.prebuilt_voice_config
    CALLS["models"].append(model)
    CALLS["contents"].append(contents)
    CALLS["voices"].append(voice_cfg.voice or (prebuilt.voice_name if prebuilt else None))
    CALLS["shapes"].append("voice" if voice_cfg.voice else "prebuilt")
    assert config.response_modalities == ["AUDIO"], "AUDIO modality missing"


class FakeModels:
    """Answers with the newest model; unavailable models and styled parts raise."""

    def generate_content(self, model, contents, config=None):
        record(model, contents, config)
        if model in UNAVAILABLE_MODELS:
            raise RuntimeError("model not available for this account")
        if isinstance(contents, list):
            # Pretend the style metadata is unsupported, so the plain-text retry runs.
            raise RuntimeError("speech_metadata is not supported by this model")
        return fake_response(wav_bytes(), mime="audio/wav")


class FakeClient:
    def __init__(self, api_key=None):
        self.models = FakeModels()


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    safe = str(detail).encode("ascii", "backslashreplace").decode("ascii")
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {safe}")


def fake_response(payload, mime="audio/wav"):
    part = genai_types.Part(inline_data=genai_types.Blob(data=payload, mime_type=mime))
    content = genai_types.Content(role="model", parts=[part])
    return pytypes.SimpleNamespace(candidates=[pytypes.SimpleNamespace(content=content)])


def wav_bytes(seconds=0.5, rate=24000):
    path = os.path.join(OUT_DIR, "seed.wav")
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x01" * int(rate * seconds))
    with open(path, "rb") as fh:
        return fh.read()


def run():
    # 1. voice mapping ------------------------------------------------------
    check("Farid -> male Gemini voice", pipeline.gemini_voice_for("fa-IR-FaridNeural") == "Puck",
          pipeline.gemini_voice_for("fa-IR-FaridNeural"))
    check("Dilara -> female Gemini voice", pipeline.gemini_voice_for("fa-IR-DilaraNeural") == "Kore",
          pipeline.gemini_voice_for("fa-IR-DilaraNeural"))

    # 2. no key: Gemini declines, edge-tts narrates --------------------------
    os.environ.pop("GEMINI_API_KEY", None)
    pipeline._gemini_voice_disabled = False
    check("Gemini declines without GEMINI_API_KEY",
          pipeline.generate_voice_gemini(FA_TEXT, os.path.join(OUT_DIR, "nokey.mp3")) is False)

    fallback = os.path.join(OUT_DIR, "fallback.mp3")
    pipeline.generate_voice(FA_TEXT, "fa-IR-FaridNeural", fallback)
    ok = os.path.exists(fallback) and os.path.getsize(fallback) > 1000
    check("edge-tts fallback produces a playable MP3", ok,
          f"size={os.path.getsize(fallback)} dur={pipeline.get_audio_duration(fallback):.2f}s"
          if ok else "missing")

    # 3. mocked Gemini (WAV) ------------------------------------------------
    os.environ["GEMINI_API_KEY"] = "offline-test-key"
    pipeline.genai = pytypes.SimpleNamespace(Client=FakeClient)
    pipeline.HAS_GENAI = True
    pipeline._gemini_voice_disabled = False

    gemini_out = os.path.join(OUT_DIR, "gemini.mp3")
    ok = pipeline.generate_voice_gemini(FA_TEXT, gemini_out, voice_name="Puck")
    check("Gemini WAV payload converted to MP3", ok and os.path.getsize(gemini_out) > 1000,
          f"size={os.path.getsize(gemini_out)} dur={pipeline.get_audio_duration(gemini_out):.2f}s"
          if ok else "failed")
    check("newest free-tier TTS model tried first",
          CALLS["models"][0] == "gemini-3.8-flash-tts", str(CALLS["models"][:4]))
    check("gemini-3 models use voice_config.voice field", CALLS["shapes"][0] == "voice",
          CALLS["shapes"][0])
    check("styled speech_metadata sent first, plain text retried",
          CALLS["contents"][0][0].parts[0].speech_metadata.style is not None
          and CALLS["contents"][1] == FA_TEXT)


def main():
    run()

    # 4. mocked Gemini returning raw PCM, only from the 2.5 TTS model --------
    class FakeModelsPCM:
        """Only the 2.5-era TTS model answers, so the legacy voice field is used."""

        def generate_content(self, model, contents, config=None):
            record(model, contents, config)
            if model != "gemini-2.5-flash-preview-tts":
                raise RuntimeError("model not available for this account")
            return fake_response(b"\x00\x01" * 24000, mime="audio/L16;codec=pcm;rate=24000")

    CALLS["models"].clear()
    CALLS["shapes"].clear()
    pipeline.genai = pytypes.SimpleNamespace(
        Client=lambda api_key=None: pytypes.SimpleNamespace(models=FakeModelsPCM()))
    pipeline._gemini_voice_disabled = False
    pcm_out = os.path.join(OUT_DIR, "gemini_pcm.mp3")
    ok = pipeline.generate_voice_gemini(FA_TEXT, pcm_out, voice_name="Kore")
    check("Gemini raw PCM payload converted to MP3", ok and os.path.getsize(pcm_out) > 1000,
          f"dur={pipeline.get_audio_duration(pcm_out):.2f}s" if ok else "failed")
    check("older models fall back through the chain and use prebuilt_voice_config",
          CALLS["models"][-1] == "gemini-2.5-flash-preview-tts"
          and CALLS["shapes"][-1] == "prebuilt" and len(CALLS["models"]) >= 5,
          f"tried={len(CALLS['models'])} last_shape={CALLS['shapes'][-1]}")

    # 5. generate_voice prefers Gemini, edge-tts not used -------------------
    edge_calls = {"n": 0}
    real_edge = pipeline.generate_voice_edge

    async def spy_edge(text, voice, path):
        edge_calls["n"] += 1
        await real_edge(text, voice, path)

    pipeline.generate_voice_edge = spy_edge
    pipeline.genai = pytypes.SimpleNamespace(Client=FakeClient)
    pipeline._gemini_voice_disabled = False
    CALLS["voices"].clear()
    preferred = os.path.join(OUT_DIR, "preferred.mp3")
    pipeline.generate_voice(FA_TEXT, "fa-IR-DilaraNeural", preferred)
    check("generate_voice uses Gemini when available",
          edge_calls["n"] == 0 and os.path.exists(preferred), f"edge_calls={edge_calls['n']}")
    check("Dilara narration requests the female Gemini voice", CALLS["voices"][-1] == "Kore",
          CALLS["voices"][-1])

    # 6. every model failing: edge-tts takes over, Gemini switches off ------
    class ExplodingModels:
        def generate_content(self, model, contents, config=None):
            raise RuntimeError("quota exceeded")

    pipeline.genai = pytypes.SimpleNamespace(
        Client=lambda api_key=None: pytypes.SimpleNamespace(models=ExplodingModels()))
    pipeline._gemini_voice_disabled = False
    edge_calls["n"] = 0

    async def spy_edge_fail(text, voice, path):
        edge_calls["n"] += 1
        await real_edge(text, voice, path)

    pipeline.generate_voice_edge = spy_edge_fail
    failed_out = os.path.join(OUT_DIR, "fallback_after_error.mp3")
    pipeline.generate_voice(FA_TEXT, "fa-IR-FaridNeural", failed_out)
    check("edge-tts fallback used after Gemini errors",
          edge_calls["n"] == 1 and os.path.getsize(failed_out) > 1000,
          f"edge_calls={edge_calls['n']}")
    check("Gemini disabled for the rest of the run", pipeline.gemini_voice_enabled() is False)

    # 7. invalid key aborts immediately ------------------------------------
    class BadKeyModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, model, contents, config=None):
            self.calls += 1
            raise RuntimeError("400 API key not valid. Please pass a valid API key.")

    bad = BadKeyModels()
    pipeline.genai = pytypes.SimpleNamespace(
        Client=lambda api_key=None: pytypes.SimpleNamespace(models=bad))
    pipeline._gemini_voice_disabled = False
    pipeline.generate_voice_gemini(FA_TEXT, os.path.join(OUT_DIR, "badkey.mp3"))
    check("invalid API key stops further attempts", bad.calls == 1, f"requests={bad.calls}")

    # 8. explicit kill switch ----------------------------------------------
    pipeline._gemini_voice_disabled = False
    os.environ["DISABLE_GEMINI_VOICE"] = "1"
    enabled_with_switch = pipeline.gemini_voice_enabled()
    declined = pipeline.generate_voice_gemini(FA_TEXT, os.path.join(OUT_DIR, "disabled.mp3"))
    os.environ.pop("DISABLE_GEMINI_VOICE", None)
    check("DISABLE_GEMINI_VOICE=1 skips Gemini entirely",
          enabled_with_switch is False and declined is False)

    failed = [r for r in results if not r[1]]
    print("\n==== SUMMARY ====")
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    for name, ok, detail in failed:
        print(f"  FAILED: {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
