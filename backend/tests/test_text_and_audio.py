import numpy as np
import pytest

from app.ai.narration import normalize_for_speech
from app.audio.processing import remap_time, shorten_long_pauses, silence, trim_edges
from app.document_processing.language import detect_language
from app.document_processing.segmentation import Sentence, split_long, split_sentences
from app.document_processing.structure import classify
from app.providers.tts.timing import approximate_sentence_times

RATE = 16000


# --------------------------------------------------------------------------- segmentation / chunking


def test_sentence_split_respects_abbreviations():
    text = "Dr. Smith arrived at 10:30 p.m. on Friday. He was late! Was anyone surprised?"
    sents = [s.text for s in split_sentences(text)]
    assert sents[0].startswith("Dr. Smith arrived")
    assert len(sents) == 3


def test_sentence_offsets_point_into_the_source():
    text = "One sentence here. Another one follows."
    for s in split_sentences(text):
        assert text[s.start : s.end] == s.text


def test_long_sentences_are_split_under_the_provider_limit():
    long = ", ".join(["a clause with several words in it"] * 40) + "."
    parts = split_long(Sentence(long, 0, len(long)), 200)
    assert len(parts) > 1
    assert all(len(p.text) <= 200 for p in parts)
    assert "".join(long[p.start : p.end] for p in parts).replace(" ", "") == long.replace(" ", "")


# --------------------------------------------------------------------------- narration cleanup


def test_narration_cleanup_expands_without_rewriting():
    out = normalize_for_speech("Dr. Smith arrived at 10:30 p.m.", "en")
    assert out.startswith("Doctor Smith arrived at")
    assert "p.m." not in out
    assert "Smith" in out and "arrived" in out


@pytest.mark.parametrize("src", ["It cost $5.", "See https://example.com/page for more.", "Chapter IV begins."])
def test_narration_cleanup_keeps_meaning_words(src):
    out = normalize_for_speech(src, "en")
    assert out  # never empties text
    assert len(out.split()) >= len(src.split()) - 1


# --------------------------------------------------------------------------- structure & language


@pytest.mark.parametrize(
    "title,kind",
    [("Chapter 1", "chapter"), ("CHAPTER ONE", "chapter"), ("Chapter One: The Beginning", "chapter"), ("PART I", "part"), ("BOOK TWO", "part"), ("Epilogue", "epilogue"), ("Contents", "toc"), ("Preface", "preface")],
)
def test_heading_classification(title, kind):
    assert classify(title)[0] == kind


def test_language_detection_per_paragraph():
    assert detect_language("The door slowly opened and a cold wind swept through the hall.") == "en"
    assert detect_language("धीरे से दरवाज़ा खुला, और ठंडी हवा अंदर आई।") == "hi"
    assert detect_language("మెల్లగా తలుపు తెరుచుకుంది.") == "te"


# --------------------------------------------------------------------------- timing


def test_approximate_timings_cover_the_audio_in_order():
    times = approximate_sentence_times(["Short.", "A much longer sentence with more words."], 5.0, 0.2)
    assert times[0][0] >= 0 and times[-1][1] <= 5.0 + 1e-6
    assert times[0][1] <= times[1][0]
    assert (times[1][1] - times[1][0]) > (times[0][1] - times[0][0])


# --------------------------------------------------------------------------- audio processing


def _tone(seconds: float) -> np.ndarray:
    return (np.sin(np.arange(int(seconds * RATE)) * 0.1) * 8000).astype(np.int16)


def test_trim_edges_removes_leading_silence():
    pcm = np.concatenate([silence(RATE, 800), _tone(1.0), silence(RATE, 800)])
    trimmed, lead = trim_edges(pcm, RATE)
    assert len(trimmed) < len(pcm)
    assert lead / RATE > 0.6


def test_long_pauses_are_shortened_and_timings_remapped():
    pcm = np.concatenate([_tone(1.0), silence(RATE, 3000), _tone(1.0)])
    out, cuts = shorten_long_pauses(pcm, RATE)
    assert len(out) < len(pcm)
    assert cuts
    # A time after the pause moves earlier by the removed amount; one before it is unchanged.
    assert remap_time(0.5, cuts) == pytest.approx(0.5, abs=0.01)
    assert remap_time(4.5, cuts) < 4.5


def _tone_raw(path, seconds: float, rate: int = 24000, freq: float = 440.0, amp: float = 0.25):
    import numpy as np

    t = np.arange(int(seconds * rate)) / rate
    # A tone with a slow tremolo, so gating sees level variation like speech.
    x = amp * np.sin(2 * np.pi * freq * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.7 * t))
    path.write_bytes((x * 32767).astype(np.int16).tobytes())


def test_frame_join_matches_a_decode_and_gives_exact_chapter_offsets(tmp_path):
    import re
    import subprocess

    from app.audio.ffmpeg import ffmpeg_exe
    from app.audio.mp3join import join_mp3
    from app.audio.processing import encode_raw

    parts = []
    for i, secs in enumerate((3.2, 7.9, 1.4)):
        raw = tmp_path / f"{i}.raw"
        _tone_raw(raw, secs, freq=300 + 200 * i)
        out = tmp_path / f"{i}.mp3"
        encode_raw(raw, 24000, out, "mp3", "96k")
        parts.append(out)
    joined = tmp_path / "full.mp3"
    durations = join_mp3(parts, joined)
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(joined), "-f", "null", "-"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "error" not in proc.stderr.lower()
    h, m, s = re.findall(r"time=(\d+):(\d+):([\d.]+)", proc.stderr)[-1]
    assert abs(int(h) * 3600 + int(m) * 60 + float(s) - sum(durations)) < 0.05
    # Each chapter's offset is its true encoded length (encoder padding included).
    assert all(abs(d - want) < 0.15 for d, want in zip(durations, (3.2, 7.9, 1.4)))


def test_loudness_estimate_tracks_ebu_r128(tmp_path):
    from app.audio.processing import estimate_loudness, measure_loudness

    for amp in (0.05, 0.3):
        raw = tmp_path / f"t{amp}.raw"
        _tone_raw(raw, 20, freq=1000, amp=amp)
        assert abs(estimate_loudness(raw, 24000) - measure_loudness(raw, 24000)) < 1.0
