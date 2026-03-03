import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

from gtts import gTTS
from gospel.text_normalizer import normalize_for_tts, build_liturgy_segments

# Silence duration (seconds) inserted between liturgy sections.
SECTION_SILENCE_S = 2.5

# gTTS top-level domain overrides — controls regional accent.
# 'pt' routes to translate.google.pt → European Portuguese (Portugal)
# All other languages use the default 'com' (US/global).
_LANG_TLD: dict[str, str] = {
    "pt": "pt",
}


def _tld(lang: str) -> str:
    return _LANG_TLD.get(lang, "com")


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    return text[:80] if text else "audio"


def _ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


# Chunk types returned by _split_chunks
# 'narr'  — normal narrator speech
# 'quote' — scripture quote (pitch effect applied)
# 'pause' — real silence (from semicolon in source text)
_PAUSE_DURATION_S = 0.7


def _split_chunks(text: str) -> list[tuple[str, str]]:
    """Split *text* on __QSTART__, __QEND__, and __PAUSE__ markers.

    Returns a list of (chunk_text, chunk_type) tuples where chunk_type is one
    of 'narr', 'quote', or 'pause'.  Whitespace-only narrator/quote chunks
    are dropped.
    """
    parts = re.split(r"(__QSTART__|__QEND__|__PAUSE__)", text)
    chunks: list[tuple[str, str]] = []
    in_quote = False
    for part in parts:
        if part == "__QSTART__":
            in_quote = True
        elif part == "__QEND__":
            in_quote = False
        elif part == "__PAUSE__":
            chunks.append(("", "pause"))
        else:
            cleaned = re.sub(r"\s+", " ", part).strip()
            if cleaned:
                chunks.append((cleaned, "quote" if in_quote else "narr"))
    return chunks


def _save_tts(text: str, lang: str, path: str, ffmpeg: Optional[str] = None) -> None:
    """Generate TTS audio for *text*, writing to *path*.

    If the text contains __QSTART__ / __QEND__ markers and ffmpeg is available,
    quoted sections are rendered with a subtle pitch-lower effect to distinguish
    them from the narrator voice.  Otherwise falls back to a plain single TTS call.
    """
    # Flatten newlines so gTTS doesn't insert sentence-boundary pauses
    flat = re.sub(r"\s*\n\s*", " ", text).strip()

    chunks = _split_chunks(flat)
    has_effects = any(ct in ("quote", "pause") for _, ct in chunks)

    if not has_effects or not ffmpeg or len(chunks) <= 1:
        # Simple path: no special markers or no ffmpeg — single TTS call
        plain = re.sub(r"__QSTART__|__QEND__|__PAUSE__", "", flat).strip()
        gTTS(text=plain, lang=lang, tld=_tld(lang), slow=False).save(path)
        return

    # Multi-chunk path: generate each chunk separately, apply effects
    tmp_dir = tempfile.mkdtemp()
    try:
        chunk_paths: list[str] = []
        for idx, (chunk, ctype) in enumerate(chunks):
            if ctype == "pause":
                # Generate a real silence clip for the semicolon pause
                sil_path = os.path.join(tmp_dir, f"chunk_{idx}_pause.mp3")
                subprocess.run(
                    [
                        ffmpeg, "-y",
                        "-f", "lavfi",
                        "-i", f"anullsrc=r=24000:cl=mono",
                        "-t", str(_PAUSE_DURATION_S),
                        "-codec:a", "libmp3lame", "-q:a", "4",
                        sil_path,
                    ],
                    check=True,
                    capture_output=True,
                )
                chunk_paths.append(sil_path)
                continue

            raw_path = os.path.join(tmp_dir, f"chunk_{idx}_raw.mp3")
            gTTS(text=chunk, lang=lang, tld=_tld(lang), slow=False).save(raw_path)

            if ctype == "quote":
                # Apply: slight pitch decrease (~7%) + speed restore via atempo.
                fx_path = os.path.join(tmp_dir, f"chunk_{idx}_fx.mp3")
                subprocess.run(
                    [
                        ffmpeg, "-y", "-i", raw_path,
                        "-af", "asetrate=24000*0.93,aresample=24000,atempo=1.075",
                        "-codec:a", "libmp3lame", "-q:a", "4",
                        fx_path,
                    ],
                    check=True,
                    capture_output=True,
                )
                chunk_paths.append(fx_path)
            else:
                chunk_paths.append(raw_path)

        n = len(chunk_paths)
        if n == 1:
            import shutil as _shutil
            _shutil.copy2(chunk_paths[0], path)
            return

        cmd = [ffmpeg, "-y"]
        for cp in chunk_paths:
            cmd += ["-i", cp]
        inputs_str = "".join(f"[{i}:a]" for i in range(n))
        cmd += [
            "-filter_complex", f"{inputs_str}concat=n={n}:v=0:a=1[out]",
            "-map", "[out]",
            "-codec:a", "libmp3lame", "-q:a", "4",
            path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg chunk concat failed:\n{result.stderr[-400:]}")
    finally:
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)


class AudioGenerator:
    """Generates podcast audio using gTTS + ffmpeg for multi-section episodes.

    Parameters
    ----------
    voice: str
        A string like 'it-female' or 'en-male'. The language code
        is derived from the prefix before the first '-'.
    speed: str
        One of 'normal', 'slow', 'fast'. Currently informational only;
        speed adjustment requires ffmpeg atempo (reserved for future use).
    out_dir: Optional[str]
        Directory to write generated audio files. Defaults to gospel/out.
    """

    def __init__(self, voice: str = "en-female", speed: str = "normal", out_dir: Optional[str] = None):
        lang = voice.split("-")[0].lower() if voice else "en"
        self.lang = lang if lang in {"en", "it", "es", "fr", "pt", "de"} else "en"
        self.speed_label = speed
        self.out_dir = out_dir or os.path.join(os.path.dirname(__file__), "out")
        os.makedirs(self.out_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_silence(self, path: str, ffmpeg: str) -> None:
        """Write a silent MP3 of SECTION_SILENCE_S seconds using ffmpeg."""
        subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=mono:sample_rate=24000",
                "-t", str(SECTION_SILENCE_S),
                "-codec:a", "libmp3lame", "-q:a", "9",
                path,
            ],
            check=True,
            capture_output=True,
        )

    def _concat_with_silence(
        self,
        all_texts: List[str],   # [title, seg1, seg2, …]
        final_mp3: str,
        ffmpeg: str,
    ) -> int:
        """Concatenate TTS segments with silence between them via ffmpeg.

        Returns duration of the final file in seconds.
        """
        tmp_dir = tempfile.mkdtemp()
        try:
            # --- Generate individual TTS files ---
            tts_paths: List[str] = []
            for idx, text in enumerate(all_texts):
                p = os.path.join(tmp_dir, f"seg_{idx}.mp3")
                _save_tts(text, self.lang, p, ffmpeg)
                tts_paths.append(p)

            # --- Generate one silence file ---
            silence_path = os.path.join(tmp_dir, "silence.mp3")
            self._generate_silence(silence_path, ffmpeg)

            # --- Build interleaved list: title, [silence, seg]+ ---
            interleaved: List[str] = [tts_paths[0]]
            for p in tts_paths[1:]:
                interleaved.append(silence_path)
                interleaved.append(p)

            # --- ffmpeg filter_complex concat ---
            n = len(interleaved)
            cmd = [ffmpeg, "-y"]
            for fp in interleaved:
                cmd += ["-i", fp]
            inputs_str = "".join(f"[{i}:a]" for i in range(n))
            filter_str = f"{inputs_str}concat=n={n}:v=0:a=1[out]"
            cmd += [
                "-filter_complex", filter_str,
                "-map", "[out]",
                "-codec:a", "libmp3lame", "-q:a", "4",
                final_mp3,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr[-600:]}")

            # --- Probe duration ---
            probe = subprocess.run([ffmpeg, "-i", final_mp3], capture_output=True, text=True)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
            if m:
                h, mn, s = m.groups()
                return int(int(h) * 3600 + int(mn) * 60 + float(s))
            return 0

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_podcast_episode(self, title: str, description: str) -> Dict:
        """Create an MP3 combining title and description.

        When the description contains recognisable liturgy sections (first
        reading, optional second reading, gospel, pope comment) a
        ~3.5-second silence is inserted between them and the responsorial
        psalm is skipped entirely.

        Returns a dict with 'audio_path', 'duration', 'filename'.
        """
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{dt}_{_slugify(title) or 'gospel'}"
        final_mp3 = os.path.join(self.out_dir, f"{base}.mp3")

        title_text = normalize_for_tts(title, lang=self.lang)
        segments = build_liturgy_segments(description, lang=self.lang)

        ffmpeg = _ffmpeg_bin()
        if len(segments) > 1 and ffmpeg:
            # Multi-section episode: title + [silence + section]*
            all_texts = [title_text] + segments
            duration = self._concat_with_silence(all_texts, final_mp3, ffmpeg)
            return {
                "audio_path": final_mp3,
                "duration": duration,
                "filename": os.path.basename(final_mp3),
            }

        # Single-segment fallback (no liturgy structure or no ffmpeg).
        full_text = f"{title_text}\n{segments[0]}".strip() if segments else title_text
        _save_tts(full_text, self.lang, final_mp3, ffmpeg)
        return {
            "audio_path": final_mp3,
            "duration": 0,
            "filename": os.path.basename(final_mp3),
        }

