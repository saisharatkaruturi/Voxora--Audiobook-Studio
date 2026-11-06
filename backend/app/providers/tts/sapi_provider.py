"""Windows SAPI 5 voices (local, built into Windows). Uses COM via comtypes.

Voice quality is basic compared with Piper, but it needs no downloads and
supports pitch control. Additional voices (e.g. Hindi/Tamil/Telugu) appear
here when installed as Windows language packs with speech support.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import threading
import wave
from pathlib import Path
from xml.sax.saxutils import escape

from app.core.errors import ProviderError, ProviderUnavailableError
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo

SVSF_IS_XML = 8
SAFT_22KHZ_16BIT_MONO = 22
SSFM_CREATE_FOR_WRITE = 3
_LCID_TO_LOCALE = {
    "409": "en-US", "809": "en-GB", "4009": "en-IN", "c09": "en-AU", "439": "hi-IN", "44a": "te-IN", "449": "ta-IN",
    "44b": "kn-IN", "44c": "ml-IN", "445": "bn-IN", "44e": "mr-IN", "40c": "fr-FR", "407": "de-DE", "c0a": "es-ES",
}


class SapiTTS(TTSProvider):
    name = "sapi"
    display_name = "Windows voices (local)"
    is_local = True
    supports_pitch = True
    supports_timestamps = True
    max_chunk_chars = 1500
    privacy_note = "Uses voices built into Windows. No text leaves your machine."

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def is_available(self) -> tuple[bool, str | None]:
        if sys.platform != "win32":
            return False, "Windows voices are only available on Windows."
        try:
            import comtypes.client  # noqa: F401
        except ImportError:
            return False, "comtypes is not installed (pip install comtypes)."
        return True, None

    def _com(self):
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        return comtypes.client

    def list_voices(self) -> list[VoiceInfo]:
        ok, _ = self.is_available()
        if not ok:
            return []
        voices: list[VoiceInfo] = []
        with self._lock:
            client = self._com()
            speaker = client.CreateObject("SAPI.SpVoice")
            tokens = speaker.GetVoices()
            for i in range(tokens.Count):
                token = tokens.Item(i)
                desc = token.GetDescription()
                lcid = (token.GetAttribute("Language") or "").split(";")[0].lower()
                locale = _LCID_TO_LOCALE.get(lcid)
                gender = (token.GetAttribute("Gender") or "").lower() or None
                name = token.GetAttribute("Name") or desc
                voices.append(
                    VoiceInfo(
                        provider=self.name,
                        id=token.Id,
                        name=name.replace("Microsoft ", "").replace(" Desktop", ""),
                        language=(locale or "en-US").split("-")[0],
                        locale=locale,
                        accent=desc.split(" - ")[-1] if " - " in desc else None,
                        gender=gender,
                        quality="standard",
                        description=desc,
                    )
                )
        return voices

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        ok, reason = self.is_available()
        if not ok:
            raise ProviderUnavailableError(self.name, reason or "SAPI unavailable", retryable=False)
        rate = max(-10, min(10, round(10 * math.log(max(options.speed, 0.3)) / math.log(3))))
        pitch = max(-10, min(10, round(options.pitch)))
        volume = max(0, min(100, round(options.volume * 100)))
        with self._lock:
            client = self._com()
            try:
                voice = client.CreateObject("SAPI.SpVoice")
                for i in range(voice.GetVoices().Count):
                    token = voice.GetVoices().Item(i)
                    if token.Id == options.voice_id:
                        voice.Voice = token
                        break
                else:
                    raise ProviderUnavailableError(self.name, f"Windows voice '{options.voice_id}' is not installed.", retryable=False)
                voice.Rate = rate
                voice.Volume = volume
                frames: list[bytes] = []
                times: list[tuple[float, float]] = []
                cursor = 0
                sample_rate = 22050
                gap = b"\x00\x00" * int(sample_rate * options.sentence_pause_ms / 1000)
                for n, sentence in enumerate(sentences):
                    fd, tmp = tempfile.mkstemp(suffix=".wav")
                    os.close(fd)
                    try:
                        stream = client.CreateObject("SAPI.SpFileStream")
                        fmt = client.CreateObject("SAPI.SpAudioFormat")
                        fmt.Type = SAFT_22KHZ_16BIT_MONO
                        stream.Format = fmt
                        stream.Open(tmp, SSFM_CREATE_FOR_WRITE)
                        voice.AudioOutputStream = stream
                        voice.Speak(f'<pitch absmiddle="{pitch}">{escape(sentence)}</pitch>', SVSF_IS_XML)
                        stream.Close()
                        with wave.open(tmp, "rb") as wf:
                            data = wf.readframes(wf.getnframes())
                    finally:
                        Path(tmp).unlink(missing_ok=True)
                    if n and gap:
                        frames.append(gap)
                        cursor += len(gap) // 2
                    frames.append(data)
                    times.append((cursor / sample_rate, (cursor + len(data) // 2) / sample_rate))
                    cursor += len(data) // 2
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(self.name, f"Windows speech synthesis failed: {exc}") from exc
        return SynthesisResult(audio=b"".join(frames), format="pcm_s16le", sample_rate=sample_rate, sentence_times=times)

    def signature(self, voice_id: str) -> str:
        return f"sapi:{voice_id}"
