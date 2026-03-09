import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from gtts import gTTS
from gospel.text_normalizer import normalize_for_tts

SUPPORTED = {"en", "it", "es", "fr", "pt", "de"}


def _clean_for_gtts(segment: str, lang: str) -> str:
    """Normalize a liturgy segment and strip SSML markers for gTTS.

    gTTS cannot handle __POPE__, __PAUSE__, __QSTART__, __QEND__ — it reads
    them as literal words.  This function:
    - Strips the __POPE__ prefix (the header line is kept as readable text)
    - Replaces __PAUSE__ with a period so gTTS pauses naturally
    - Removes __QSTART__ / __QEND__ guillemet markers
    - Preserves newlines as sentence-boundary periods so section labels get
      a natural breath before the reading body begins
    """
    # Normalize without flattening so newlines between label/body are kept
    normalized = normalize_for_tts(segment, lang=lang, flatten_lines=False)
    # Strip __POPE__ prefix
    if normalized.startswith("__POPE__"):
        normalized = normalized[len("__POPE__"):].strip()
    # Replace markers
    normalized = normalized.replace("__PAUSE__", ".")
    normalized = normalized.replace("__QSTART__", "")
    normalized = normalized.replace("__QEND__", "")
    # Newlines between section label and body → period for natural gTTS pause
    normalized = re.sub(r"\s*\n\s*", ". ", normalized)
    # Clean up artefacts from marker removal
    normalized = re.sub(r"\.\s*\.+", ".", normalized)
    normalized = re.sub(r",\s*\.\s*", ". ", normalized)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized.strip()


def synthesize(
    text: str,
    lang: str = "it",
    speed: str = "normal",
    out_dir: str = None,
    segments: list[str] | None = None,
    pause_seconds: int = 0,
    title: str = "",
) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED:
        lang = "it"
    out_dir = out_dir or os.path.dirname(__file__)
    os.makedirs(out_dir, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"gospel_{lang}_{base}.mp3")

    normalized_segments = [_clean_for_gtts(s, lang) for s in (segments or []) if (s or "").strip()]
    if not normalized_segments:
        normalized_segments = [normalize_for_tts(text, lang=lang)]

    # Prepend title as the first spoken segment when provided
    if title:
        title_clean = normalize_for_tts(title, lang=lang)
        normalized_segments.insert(0, title_clean)

    if len(normalized_segments) == 1 or pause_seconds <= 0:
        tts = gTTS(text=normalized_segments[0], lang=lang, slow=(speed == "slow"))
        tts.save(out_path)
        return out_path

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        fallback_text = f"\n\n{' . ' * 20}\n\n".join(normalized_segments)
        gTTS(text=fallback_text, lang=lang, slow=(speed == "slow")).save(out_path)
        return out_path

    with tempfile.TemporaryDirectory() as tmp_dir:
        part_files = []
        for idx, chunk in enumerate(normalized_segments, start=1):
            part_path = os.path.join(tmp_dir, f"part_{idx}.mp3")
            gTTS(text=chunk, lang=lang, slow=(speed == "slow")).save(part_path)
            part_files.append(part_path)

        silence_path = os.path.join(tmp_dir, "silence.mp3")
        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=24000:cl=mono",
                "-t",
                str(max(0, int(pause_seconds))),
                "-q:a",
                "9",
                "-acodec",
                "libmp3lame",
                silence_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        concat_list = os.path.join(tmp_dir, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for idx, part_path in enumerate(part_files):
                f.write(f"file '{part_path.replace('\\', '/')}'\n")
                if idx < len(part_files) - 1:
                    f.write(f"file '{silence_path.replace('\\', '/')}'\n")

        subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-acodec",
                "libmp3lame",
                "-b:a",
                "128k",
                out_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return out_path
