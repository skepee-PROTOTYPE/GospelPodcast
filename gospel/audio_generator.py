import os
import re
import tempfile
from datetime import datetime
from typing import Dict, Optional

from gtts import gTTS
from gospel.text_normalizer import normalize_for_tts


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    return text[:80] if text else "audio"


class AudioGenerator:
    """Generates podcast audio using gTTS.

    Parameters
    ----------
    voice: str
        A string like 'it-female' or 'en-male'. The language code
        is derived from the prefix before the first '-'.
    speed: str
        One of 'normal', 'slow', 'fast'. Controls playback speed.
    out_dir: Optional[str]
        Directory to write generated audio files. Defaults to gospel/out.
    """

    def __init__(self, voice: str = "en-female", speed: str = "normal", out_dir: Optional[str] = None):
        lang = voice.split("-")[0].lower() if voice else "en"
        self.lang = lang if lang in {"en", "it", "es", "fr", "pt", "de"} else "en"
        self.speed_label = speed
        self.speed_factor = {"slow": 0.9, "normal": 1.0, "fast": 1.1}.get(speed, 1.0)
        self.out_dir = out_dir or os.path.join(os.path.dirname(__file__), "out")
        os.makedirs(self.out_dir, exist_ok=True)

    def _apply_speed(self, seg):
        # Lazy import to avoid dependency when not needed
        from pydub import AudioSegment  # type: ignore
        if self.speed_factor == 1.0:
            return seg
        # Change speed by altering frame_rate, then reset to original
        new_frame_rate = int(seg.frame_rate * self.speed_factor)
        faster = seg._spawn(seg.raw_data, overrides={"frame_rate": new_frame_rate})
        return faster.set_frame_rate(seg.frame_rate)

    def create_podcast_episode(self, title: str, description: str) -> Dict:
        """Create an MP3 combining title and description.

        Returns a dict with 'audio_path', 'duration', 'filename'.
        """
        text = f"{title}\n{description}".strip()
        text = normalize_for_tts(text, lang=self.lang)
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{dt}_{_slugify(title) or 'gospel'}"
        final_mp3 = os.path.join(self.out_dir, f"{base}.mp3")

        # Generate initial TTS
        tts = gTTS(text=text, lang=self.lang, slow=False)

        # Fast path: no speed change, avoid ffmpeg/pydub export
        if self.speed_factor == 1.0:
            tts.save(final_mp3)
            return {
                "audio_path": final_mp3,
                "duration": 0,  # duration optional; publisher can omit
                "filename": os.path.basename(final_mp3),
            }

        # Speed adjusted path requires pydub/ffmpeg
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as tmp:
            tts.save(tmp.name)
            from pydub import AudioSegment  # type: ignore
            seg = AudioSegment.from_file(tmp.name, format="mp3")
            seg2 = self._apply_speed(seg)
            seg2.export(final_mp3, format="mp3", bitrate="128k")

        duration_seconds = int(len(seg2) / 1000)
        return {
            "audio_path": final_mp3,
            "duration": duration_seconds,
            "filename": os.path.basename(final_mp3),
        }
