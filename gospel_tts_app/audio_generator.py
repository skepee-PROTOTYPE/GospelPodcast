import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from gtts import gTTS
from gospel.text_normalizer import normalize_for_tts

SUPPORTED = {"en", "it", "es", "fr", "pt", "de"}


def synthesize(
    text: str,
    lang: str = "it",
    speed: str = "normal",
    out_dir: str = None,
    segments: list[str] | None = None,
    pause_seconds: int = 0,
) -> str:
    lang = (lang or "it").lower()
    if lang not in SUPPORTED:
        lang = "it"
    out_dir = out_dir or os.path.dirname(__file__)
    os.makedirs(out_dir, exist_ok=True)
    base = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"gospel_{lang}_{base}.mp3")

    normalized_segments = [normalize_for_tts(s, lang=lang) for s in (segments or []) if (s or "").strip()]
    if not normalized_segments:
        normalized_segments = [normalize_for_tts(text, lang=lang)]

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
