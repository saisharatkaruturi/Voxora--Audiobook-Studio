"""Piper: fast, fully local neural TTS (ONNX). https://github.com/OHF-Voice/piper1-gpl

Voices are `.onnx` + `.onnx.json` pairs in PIPER_VOICES_PATH. The public catalog
(voices.json) lists 170+ voices, including Hindi, Telugu, Malayalam, Marathi,
Bengali and Nepali; they can be installed from the Voice Studio.
"""

from __future__ import annotations

import json
import os
import queue
import threading
from collections import OrderedDict
from pathlib import Path

import numpy as np

from app.core.errors import ProviderError, ProviderUnavailableError
from app.document_processing.language import LANGUAGE_NAMES
from app.providers.tts.base import SynthesisOptions, SynthesisResult, TTSProvider, VoiceInfo

CATALOG_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
ACCENTS = {
    "en_US": "American English", "en_GB": "British English", "en_IN": "Indian English", "en_AU": "Australian English",
    "hi_IN": "Hindi (India)", "te_IN": "Telugu (India)", "ml_IN": "Malayalam (India)", "mr_IN": "Marathi (India)",
    "bn_BD": "Bengali (Bangladesh)", "ne_NP": "Nepali (Nepal)", "ta_IN": "Tamil (India)", "kn_IN": "Kannada (India)",
}


_PHONEMIZE_LOCK = threading.Lock()


def _onnx_providers() -> list[str]:
    try:
        import onnxruntime

        return onnxruntime.get_available_providers()
    except Exception:
        return []


class PiperTTS(TTSProvider):
    name = "piper"
    display_name = "Piper (local)"
    is_local = True
    supports_timestamps = True  # we synthesize sentence by sentence, so timings are exact
    max_chunk_chars = 2000
    privacy_note = "Runs entirely on this computer. No text leaves your machine."

    def __init__(self, voices_path: Path, max_loaded: int = 3, sessions: int | None = None):
        self.voices_path = voices_path
        self.voices_path.mkdir(parents=True, exist_ok=True)
        self._loaded: OrderedDict[str, object] = OrderedDict()
        self._lock = threading.Lock()
        self.max_loaded = max_loaded
        # Parallel sessions per voice. Measured (scripts/benchmark_tts.py, 12 cores): 6 sessions x 2
        # threads = 6.0x realtime vs 1 x 12 threads = 2.7x. ONNX inference releases the GIL.
        self.use_cuda = "CUDAExecutionProvider" in _onnx_providers()
        cores = os.cpu_count() or 4
        self.sessions = sessions or (2 if self.use_cuda else max(1, min(6, cores // 2)))
        self.threads_per_session = 1 if self.use_cuda else max(1, cores // self.sessions)
        self.max_chunk_parallelism = self.sessions

    def is_available(self) -> tuple[bool, str | None]:
        try:
            import piper  # noqa: F401
        except ImportError:
            return False, "piper-tts is not installed (pip install piper-tts)."
        if not any(self.voices_path.glob("*.onnx")):
            return False, "No Piper voices installed yet. Install one from the Voice Studio."
        return True, None

    # ------------------------------------------------------------------ catalog
    def catalog(self) -> dict:
        path = self.voices_path / "voices.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return {}

    def refresh_catalog(self) -> dict:
        import httpx

        resp = httpx.get(CATALOG_URL, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        (self.voices_path / "voices.json").write_bytes(resp.content)
        return resp.json()

    def _voice_from_config(self, key: str, config: dict, installed: bool) -> VoiceInfo:
        lang = config.get("language", {})
        code = lang.get("code") or key.split("-")[0]
        family = lang.get("family") or code.split("_")[0]
        quality = config.get("quality") or config.get("audio", {}).get("quality")
        name = (config.get("name") or key.split("-")[1] if "-" in key else key).replace("_", " ").title()
        speakers = config.get("num_speakers", 1)
        return VoiceInfo(
            provider=self.name,
            id=key,
            name=name,
            language=family,
            locale=code.replace("_", "-"),
            accent=ACCENTS.get(code) or f"{lang.get('name_english', LANGUAGE_NAMES.get(family, family))} ({lang.get('country_english', code)})",
            quality=quality,
            installed=installed,
            description=f"Piper {quality} quality" + (f", {speakers} speakers" if speakers and speakers > 1 else ""),
            meta={"size_bytes": sum(f.get("size_bytes", 0) for f in config.get("files", {}).values()) or None},
        )

    def list_voices(self, include_catalog: bool = False) -> list[VoiceInfo]:
        voices: dict[str, VoiceInfo] = {}
        for onnx in sorted(self.voices_path.glob("*.onnx")):
            cfg_path = onnx.with_suffix(".onnx.json")
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            key = onnx.stem
            catalog_entry = self.catalog().get(key, {})
            merged = {**cfg, **{k: v for k, v in catalog_entry.items() if k in ("name", "quality", "files", "num_speakers")}}
            if "language" not in merged or "family" not in merged.get("language", {}):
                merged["language"] = catalog_entry.get("language") or {"code": cfg.get("language", {}).get("code", key.split("-")[0])}
            voices[key] = self._voice_from_config(key, merged, installed=True)
        if include_catalog:
            for key, entry in self.catalog().items():
                if key not in voices:
                    voices[key] = self._voice_from_config(key, entry, installed=False)
        return list(voices.values())

    def install_voice(self, key: str, progress=None) -> VoiceInfo:
        import httpx

        entry = self.catalog().get(key) or self.refresh_catalog().get(key)
        if not entry:
            raise ProviderError(self.name, f"Unknown Piper voice '{key}'.", retryable=False)
        files = [f for f in entry["files"] if f.endswith((".onnx", ".onnx.json"))]
        total = sum(entry["files"][f]["size_bytes"] for f in files) or 1
        done = 0
        for rel in files:
            dest = self.voices_path / Path(rel).name
            tmp = dest.with_suffix(dest.suffix + ".part")
            with httpx.stream("GET", VOICE_BASE_URL + rel, timeout=60, follow_redirects=True) as resp:
                resp.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_bytes(1024 * 256):
                        fh.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(min(done / total, 1.0))
            tmp.replace(dest)
        return self._voice_from_config(key, entry, installed=True)

    def remove_voice(self, key: str) -> None:
        for suffix in (".onnx", ".onnx.json"):
            (self.voices_path / f"{key}{suffix}").unlink(missing_ok=True)
        with self._lock:
            self._loaded.pop(key, None)

    # ------------------------------------------------------------------ synthesis
    def _new_voice(self, model: Path):
        import json as _json

        import onnxruntime
        from piper import PiperVoice
        from piper.config import PiperConfig

        opts = onnxruntime.SessionOptions()
        opts.intra_op_num_threads = self.threads_per_session
        opts.inter_op_num_threads = 1
        providers = [("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"}), "CPUExecutionProvider"] if self.use_cuda else ["CPUExecutionProvider"]
        session = onnxruntime.InferenceSession(str(model), sess_options=opts, providers=providers)
        config = PiperConfig.from_dict(_json.loads(Path(f"{model}.json").read_text(encoding="utf-8")))
        voice = PiperVoice(session=session, config=config)
        phonemize = voice.phonemize

        def locked(text: str):
            with _PHONEMIZE_LOCK:  # espeak-ng keeps global state; only inference runs in parallel
                return phonemize(text)

        voice.phonemize = locked
        return voice

    def _voice(self, key: str):
        """Borrow one of this voice's parallel sessions (blocks while all are busy)."""
        with self._lock:
            pool = self._loaded.get(key)
            if pool is None:
                model = self.voices_path / f"{key}.onnx"
                if not model.exists():
                    raise ProviderUnavailableError(
                        self.name, f"Piper voice '{key}' is not installed. Install it from the Voice Studio.", retryable=False
                    )
                pool = queue.Queue()
                for _ in range(self.sessions):
                    pool.put(self._new_voice(model))
                self._loaded[key] = pool
                while len(self._loaded) > self.max_loaded:
                    self._loaded.popitem(last=False)
            self._loaded.move_to_end(key)
        return pool

    def synthesize(self, sentences: list[str], options: SynthesisOptions) -> SynthesisResult:
        from piper import SynthesisConfig

        pool = self._voice(options.voice_id)
        voice = pool.get()
        rate = voice.config.sample_rate
        config = SynthesisConfig(length_scale=1.0 / max(0.5, min(options.speed, 2.0)), volume=max(0.0, min(options.volume, 2.0)))
        gap = np.zeros(int(rate * options.sentence_pause_ms / 1000), dtype=np.int16)
        pieces: list[np.ndarray] = []
        times: list[tuple[float, float]] = []
        cursor = 0
        try:
            for i, sentence in enumerate(sentences):
                audio = [chunk.audio_int16_array for chunk in voice.synthesize(sentence, config)]
                arr = np.concatenate(audio) if audio else np.zeros(0, dtype=np.int16)
                if i and len(gap):
                    pieces.append(gap)
                    cursor += len(gap)
                pieces.append(arr)
                times.append((cursor / rate, (cursor + len(arr)) / rate))
                cursor += len(arr)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(self.name, f"Piper failed to synthesize text: {exc}") from exc
        finally:
            pool.put(voice)
        pcm = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.int16)
        return SynthesisResult(audio=pcm.tobytes(), format="pcm_s16le", sample_rate=rate, sentence_times=times)

    def signature(self, voice_id: str) -> str:
        model = self.voices_path / f"{voice_id}.onnx"
        return f"piper:{voice_id}:{model.stat().st_size if model.exists() else 0}"
