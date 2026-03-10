import html
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

from google.cloud import texttospeech
from gospel.text_normalizer import normalize_for_tts, build_liturgy_segments

# Break between liturgy sections (used in SSML <break> tags).
SECTION_SILENCE_S = 2.5
_PAUSE_DURATION_S = 0.3   # semicolon pauses — short; Neural2 paces naturally
_SSML_BYTE_LIMIT  = 4800  # conservative safety margin (Cloud TTS limit is 5000)

# Neural2 male voices per supported language.
_VOICES: Dict[str, str] = {
    "it": "it-IT-Neural2-C",
    "en": "en-US-Neural2-D",
    "de": "de-DE-Neural2-B",
    "fr": "fr-FR-Neural2-B",
    "es": "es-ES-Neural2-B",
    "pt": "pt-BR-Neural2-B",
}

_LANG_BCP47: Dict[str, str] = {
    "it": "it-IT",
    "en": "en-US",
    "de": "de-DE",
    "fr": "fr-FR",
    "es": "es-ES",
    "pt": "pt-BR",
}


# Phoneme hints for biblical proper names that Neural2 consistently
# mispronounces across languages. Keys are plain-text forms (post-normalization);
# values are IPA strings for Cloud TTS <phoneme> tags.
# Only applied when lang == 'it' for now (extend as needed).
_IT_PHONEMES: dict[str, str] = {
    "Gesù":      "dʒeˈzu",
    "Gesu":      "dʒeˈzu",
    "Israele":   "israˈɛːle",
    "Geremia":   "dʒereˈmia",
    "Geremìa":   "dʒereˈmia",
    "Ezechiele": "edzeˈkjɛːle",
    "Isaia":     "izaˈia",
    "Giosuè":    "dʒozuˈɛ",
    "Mosè":      "moˈzɛ",
    "Elìa":      "eˈlia",
    "Elisa":     "eˈliːza",
    "Zachèo":    "dzakˈkɛo",
}

_PHONEMES_BY_LANG: dict[str, dict[str, str]] = {
    "it": _IT_PHONEMES,
}


def _apply_phonemes(text: str, lang: str) -> str:
    """Wrap known biblical names in SSML <phoneme> tags for correct IPA stress."""
    hints = _PHONEMES_BY_LANG.get(lang)
    if not hints:
        return text
    for word, ipa in hints.items():
        escaped_word = re.escape(html.escape(word))
        replacement = f'<phoneme alphabet="ipa" ph="{ipa}">{html.escape(word)}</phoneme>'
        text = re.sub(rf"\b{escaped_word}\b", replacement, text)
    return text



def _strip_xml_illegal(text: str) -> str:
    """Remove characters that are illegal in XML 1.0 (control chars except tab/LF/CR)."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)


def _escape_and_mark(text: str) -> str:
    """HTML-escape plain text and replace audio markers with SSML tags.

    Markers produced by text_normalizer:
      __PAUSE__  -> short break (semicolon pause)
      __QSTART__ -> open prosody for scripture guillemet quote (deeper pitch)
      __QEND__   -> close prosody

    NOTE: Do NOT use this for text that will be wrapped in <emphasis> or other
    structural tags — use _escape_header() instead, which skips break injection.
    """
    safe = html.escape(_strip_xml_illegal(text))
    safe = safe.replace("__PAUSE__",  f'<break time="{_PAUSE_DURATION_S}s"/>')
    safe = safe.replace("__QSTART__", '<break time="200ms"/><prosody pitch="-6%" rate="97%">')
    safe = safe.replace("__QEND__",   '</prosody><break time="150ms"/>')
    # Neural2 voices already produce natural sentence-boundary pauses at . ! ?
    # Adding explicit <break> tags on top creates a double-pause that sounds choppy.
    # We rely on Neural2's built-in prosody instead.
    return safe


def _escape_header(text: str) -> str:
    """HTML-escape text for use inside structural SSML tags like <emphasis>.

    Intentionally does NOT inject <break> tags — those are invalid inside
    <emphasis> and will cause a 400 from Neural2 voices.
    """
    safe = html.escape(_strip_xml_illegal(text))
    safe = safe.replace("__PAUSE__",  f'<break time="{_PAUSE_DURATION_S}s"/>')
    safe = safe.replace("__QSTART__", "")
    safe = safe.replace("__QEND__",   "")
    return safe


def _section_to_ssml(segment: str) -> str:
    """Convert one liturgy segment to SSML inner content.

    Segments may be prefixed with ``__POPE__`` to signal they contain the
    pope's comment — these receive a distinct lower-pitch rendering.

    The *first line* is the section label (e.g. "Prima Lettura") wrapped in
    ``<emphasis>``.  If the *second line* is a short book-attribution with no
    sentence punctuation (e.g. "Dal libro della Gènesi"), it is also rendered
    in ``<emphasis>`` as a sub-header, followed by a longer pause before the
    reading body begins.  Otherwise only the first line is the header.
    """
    is_pope = segment.startswith("__POPE__")
    text = segment[len("__POPE__"):].strip() if is_pope else segment.strip()

    # Normalise internal newlines
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    lines = text.split("\n")

    header_raw = lines[0].strip() if lines else ""

    # Detect a sub-header: second line is short and contains no sentence punctuation
    sub_header_raw = ""
    body_start = 1
    if len(lines) >= 2:
        second = lines[1].strip()
        if second and len(second) < 60 and not re.search(r'[.!?:,]', second):
            sub_header_raw = second
            body_start = 2

    body_raw = re.sub(r"\s*\n\s*", " ", "\n".join(lines[body_start:])).strip()

    parts: list[str] = []

    if header_raw:
        parts.append(
            f'<emphasis level="moderate">{_escape_header(header_raw)}</emphasis>'
        )

    if sub_header_raw:
        # Short breath between section label and book attribution
        parts.append('<break time="0.5s"/>')
        # Add a terminal period so Neural2 uses falling (complete) intonation
        # rather than the hesitant rising tone it produces on unpunctuated phrases.
        sub_text = sub_header_raw if re.search(r'[.!?:]$', sub_header_raw) else sub_header_raw + '.'
        parts.append(
            f'<emphasis level="moderate">{_escape_header(sub_text)}</emphasis>'
        )

    if body_raw:
        # Longer pause after header(s) to signal the reading is starting
        parts.append('<break time="1.0s"/>')
        body_ssml = _escape_and_mark(body_raw)
        if is_pope:
            # Pope's reflection — slightly slower and deeper for distinction
            parts.append(f'<prosody pitch="-4%" rate="95%">{body_ssml}</prosody>')
        else:
            parts.append(body_ssml)

    return "".join(parts)


def _build_episode_ssml(title: str, segments: list[str], lang: str = "it") -> str:
    """Build a complete SSML document for the whole episode."""
    # Title with stronger emphasis
    title_ssml = (
        f'<emphasis level="strong">'
        f'{_escape_header(re.sub(r"[ \t]*\n[ \t]*", " ", title).strip())}'
        f'</emphasis>'
    )
    parts = [title_ssml]
    for seg in segments:
        parts.append(f'<break time="{SECTION_SILENCE_S}s"/>')
        parts.append(_section_to_ssml(seg))
    ssml = "<speak>" + "".join(parts) + "</speak>"
    return _apply_phonemes(ssml, lang)


# -- Cloud TTS synthesis -------------------------------------------------------

def _synthesize(ssml: str, voice_name: str, language_code: str,
                speaking_rate: float = 1.0) -> bytes:
    """Call Cloud TTS and return raw MP3 bytes."""
    client = texttospeech.TextToSpeechClient()
    response = client.synthesize_speech(
        input=texttospeech.SynthesisInput(ssml=ssml),
        voice=texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name,
        ),
        audio_config=texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=speaking_rate,
        ),
    )
    return response.audio_content


def _synth_segment_safe(ssml: str, voice_name: str, language_code: str,
                        speaking_rate: float, ffmpeg: Optional[str],
                        tmp_dir: str, part_name: str) -> str:
    """Synthesize one segment SSML to an MP3 file, chunking if needed.

    When the SSML fits within the Cloud TTS byte limit a single API call is
    made.  If not, the inner text is split at sentence boundaries and each
    chunk is synthesised separately, then concatenated via ffmpeg.

    Returns the path to the resulting MP3 file.
    """
    out_path = os.path.join(tmp_dir, f"{part_name}.mp3")

    if len(ssml.encode("utf-8")) <= _SSML_BYTE_LIMIT or not ffmpeg:
        with open(out_path, "wb") as f:
            f.write(_synthesize(ssml, voice_name, language_code, speaking_rate))
        return out_path

    # Extract inner SSML content between <speak> … </speak>
    inner_match = re.match(r"<speak>(.*)</speak>", ssml, re.DOTALL)
    inner = inner_match.group(1) if inner_match else ssml

    # Tokenise on break tags AND block-level open/close tags so we can track
    # nesting depth and only split at breaks that are at the *outer* level
    # (i.e. not inside <prosody> or <emphasis>). Splitting inside a block tag
    # produces orphaned opening/closing tags that Neural2 rejects with 400.
    _token_re = re.compile(
        r'(<break\s[^>]*/>'           # self-closing break
        r'|</(?:prosody|emphasis)>'   # closing block tag
        r'|<(?:prosody|emphasis)\b[^>]*>)',  # opening block tag
        re.IGNORECASE,
    )
    tokens = _token_re.split(inner)

    chunks: list[str] = []
    current: list[str] = []
    current_bytes = len("<speak></speak>".encode("utf-8"))
    tag_depth = 0   # tracks how many block tags (prosody/emphasis) are open

    for token in tokens:
        t_bytes = len(token.encode("utf-8"))

        is_break   = bool(re.match(r'<break\s', token, re.IGNORECASE))
        is_open    = bool(re.match(r'<(?:prosody|emphasis)\b', token, re.IGNORECASE))
        is_close   = bool(re.match(r'</(?:prosody|emphasis)', token, re.IGNORECASE))

        # Only split at a break when we are at the outer level (not inside any
        # block-level tag) and the current chunk is already large enough.
        if is_break and tag_depth == 0 and current and current_bytes + t_bytes > _SSML_BYTE_LIMIT:
            chunks.append("<speak>" + "".join(current) + "</speak>")
            current = []
            current_bytes = len("<speak></speak>".encode("utf-8"))

        current.append(token)
        current_bytes += t_bytes

        if is_open:
            tag_depth += 1
        elif is_close:
            tag_depth = max(0, tag_depth - 1)

    if current:
        chunks.append("<speak>" + "".join(current) + "</speak>")

    if len(chunks) == 1:
        with open(out_path, "wb") as f:
            f.write(_synthesize(chunks[0], voice_name, language_code, speaking_rate))
        return out_path

    chunk_paths: list[str] = []
    for ci, chunk_ssml in enumerate(chunks):
        cp = os.path.join(tmp_dir, f"{part_name}_chunk{ci}.mp3")
        with open(cp, "wb") as f:
            f.write(_synthesize(chunk_ssml, voice_name, language_code, speaking_rate))
        chunk_paths.append(cp)

    _concat_mp3s(chunk_paths, out_path, ffmpeg)
    return out_path


# -- ffmpeg helpers ------------------------------------------------------------

def _ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"[^a-zA-Z0-9\-]", "", text)
    return text[:80] if text else "audio"


def _probe_duration(path: str, ffmpeg: str) -> int:
    probe = subprocess.run([ffmpeg, "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", probe.stderr)
    if m:
        h, mn, s = m.groups()
        return int(int(h) * 3600 + int(mn) * 60 + float(s))
    return 0


def _generate_silence(path: str, ffmpeg: str, duration: float) -> None:
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
            "-t", str(duration),
            "-codec:a", "libmp3lame", "-q:a", "9",
            path,
        ],
        check=True, capture_output=True,
    )


def _concat_mp3s(paths: List[str], out_path: str, ffmpeg: str) -> None:
    n = len(paths)
    if n == 1:
        shutil.copy2(paths[0], out_path)
        return
    cmd = [ffmpeg, "-y"]
    for p in paths:
        cmd += ["-i", p]
    inputs_str = "".join(f"[{i}:a]" for i in range(n))
    cmd += [
        "-filter_complex", f"{inputs_str}concat=n={n}:v=0:a=1[out]",
        "-map", "[out]",
        "-codec:a", "libmp3lame", "-q:a", "4",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr[-600:]}")


# -- AudioGenerator ------------------------------------------------------------

class AudioGenerator:
    """Generates podcast audio using Google Cloud TTS (Neural2 male voices).

    Parameters
    ----------
    voice: str
        Cloud TTS voice name (e.g. 'it-IT-Neural2-C') or a legacy key like
        'it-female' -- the language prefix is mapped to the Neural2 catalogue.
    speed: str
        One of 'normal' (1.0), 'slow' (0.85), 'fast' (1.15).
    out_dir: Optional[str]
        Output directory. Defaults to gospel/out.
    """

    def __init__(self, voice: str = "it-IT-Neural2-C", speed: str = "normal",
                 out_dir: Optional[str] = None):
        lang_prefix = voice.split("-")[0].lower() if voice else "it"
        self.lang = lang_prefix if lang_prefix in _VOICES else "it"
        if re.match(r"^[a-z]{2}-[A-Z]{2}-", voice):
            self.voice_name = voice
        else:
            self.voice_name = _VOICES.get(self.lang, _VOICES["it"])
        self.language_code = _LANG_BCP47.get(self.lang, "it-IT")
        self.speaking_rate = {"slow": 0.85, "normal": 1.0, "fast": 1.15}.get(speed, 1.0)
        self.out_dir = out_dir or os.path.join(os.path.dirname(__file__), "out")
        os.makedirs(self.out_dir, exist_ok=True)

    def _synth(self, ssml: str) -> bytes:
        return _synthesize(ssml, self.voice_name, self.language_code, self.speaking_rate)

    def create_podcast_episode(self, title: str, description: str) -> Dict:
        """Create an MP3 episode from title + liturgy description.

        Structure: title -> 2.5 s break -> section 1 -> ... -> section N.
        Sections are split by build_liturgy_segments (prima lettura, vangelo,
        pope comment). The pope comment is announced by name before the quote.
        Section headers use SSML <emphasis>, guillemet quotes get pitch -5%,
        pope text pitch -4% / rate 95%. Semicolon pauses are 0.3 s breaks.

        When the SSML fits within Cloud TTS 5000-byte limit, one API call
        produces the entire episode. If too large, sections are synthesised
        individually and concatenated with ffmpeg silence clips.

        Returns a dict with 'audio_path', 'duration', 'filename'.
        """
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{dt}_{_slugify(title) or 'gospel'}"
        final_mp3 = os.path.join(self.out_dir, f"{base}.mp3")

        title_text = normalize_for_tts(title, lang=self.lang)
        segments   = build_liturgy_segments(description, lang=self.lang)
        full_ssml  = _build_episode_ssml(title_text, segments, lang=self.lang)

        if len(full_ssml.encode("utf-8")) <= _SSML_BYTE_LIMIT:
            with open(final_mp3, "wb") as f:
                f.write(self._synth(full_ssml))
        else:
            ffmpeg = _ffmpeg_bin()
            if not ffmpeg:
                with open(final_mp3, "wb") as f:
                    f.write(self._synth(full_ssml))
            else:
                tmp_dir = tempfile.mkdtemp()
                try:
                    silence_path = os.path.join(tmp_dir, "silence.mp3")
                    _generate_silence(silence_path, ffmpeg, SECTION_SILENCE_S)

                    # title as first part, then each segment
                    title_ssml = _apply_phonemes(
                        f'<speak><emphasis level="strong">'
                        f'{_escape_header(title_text)}'
                        f'</emphasis></speak>',
                        self.lang,
                    )
                    interleaved: List[str] = []
                    title_path = _synth_segment_safe(
                        title_ssml, self.voice_name, self.language_code,
                        self.speaking_rate, ffmpeg, tmp_dir, "part_title",
                    )
                    interleaved.append(title_path)
                    for idx, seg in enumerate(segments):
                        ssml = _apply_phonemes(
                            f"<speak>{_section_to_ssml(seg)}</speak>", self.lang
                        )
                        p = _synth_segment_safe(
                            ssml, self.voice_name, self.language_code,
                            self.speaking_rate, ffmpeg, tmp_dir, f"part_{idx}",
                        )
                        interleaved.append(silence_path)
                        interleaved.append(p)

                    _concat_mp3s(interleaved, final_mp3, ffmpeg)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        ffmpeg = _ffmpeg_bin()
        duration = _probe_duration(final_mp3, ffmpeg) if ffmpeg else 0
        return {
            "audio_path": final_mp3,
            "duration":   duration,
            "filename":   os.path.basename(final_mp3),
        }

    def create_episode_from_segments(self, title: str, segments: list[str]) -> Dict:
        """Create an MP3 episode from a title and pre-built liturgy segments.

        Same synthesis pipeline as :py:meth:`create_podcast_episode` but skips
        the ``build_liturgy_segments`` step — useful when segments are produced
        by an alternative source such as
        :py:class:`~gospel.html_scraper.VaticanHTMLScraper`.
        """
        dt = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{dt}_{_slugify(title) or 'gospel'}"
        final_mp3 = os.path.join(self.out_dir, f"{base}.mp3")

        title_text = normalize_for_tts(title, lang=self.lang)
        full_ssml  = _build_episode_ssml(title_text, segments, lang=self.lang)

        if len(full_ssml.encode("utf-8")) <= _SSML_BYTE_LIMIT:
            with open(final_mp3, "wb") as f:
                f.write(self._synth(full_ssml))
        else:
            ffmpeg = _ffmpeg_bin()
            if not ffmpeg:
                with open(final_mp3, "wb") as f:
                    f.write(self._synth(full_ssml))
            else:
                tmp_dir = tempfile.mkdtemp()
                try:
                    silence_path = os.path.join(tmp_dir, "silence.mp3")
                    _generate_silence(silence_path, ffmpeg, SECTION_SILENCE_S)

                    title_ssml = _apply_phonemes(
                        f'<speak><emphasis level="strong">'
                        f'{_escape_header(title_text)}'
                        f'</emphasis></speak>',
                        self.lang,
                    )
                    interleaved: List[str] = []
                    title_path = _synth_segment_safe(
                        title_ssml, self.voice_name, self.language_code,
                        self.speaking_rate, ffmpeg, tmp_dir, "part_title",
                    )
                    interleaved.append(title_path)
                    for idx, seg in enumerate(segments):
                        ssml = _apply_phonemes(
                            f"<speak>{_section_to_ssml(seg)}</speak>", self.lang
                        )
                        p = _synth_segment_safe(
                            ssml, self.voice_name, self.language_code,
                            self.speaking_rate, ffmpeg, tmp_dir, f"part_{idx}",
                        )
                        interleaved.append(silence_path)
                        interleaved.append(p)

                    _concat_mp3s(interleaved, final_mp3, ffmpeg)
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)

        ffmpeg = _ffmpeg_bin()
        duration = _probe_duration(final_mp3, ffmpeg) if ffmpeg else 0
        return {
            "audio_path": final_mp3,
            "duration":   duration,
            "filename":   os.path.basename(final_mp3),
        }
