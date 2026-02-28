# Gospel TTS App

Simple CLI to generate Daily Gospel audio in the selected language using Vatican News RSS + Google Text-to-Speech.

## Quick Start

1. Install dependencies:

```bash
pip install -r gospel_tts_app/requirements.txt
```

2. Generate Italian audio from RSS:

```bash
python gospel_tts_app/tts_cli.py --lang it --out gospel_tts_app/it_latest.mp3
```

3. Generate from custom text:

```bash
python gospel_tts_app/tts_cli.py --lang it --text "Nel principio era il Verbo." --out gospel_tts_app/sample_it.mp3
```

## Notes
- Supported languages: it, en, es, fr, pt, de.
- Speed: `normal` (default) or `slow`. `slow` uses gTTS slower mode. `fast` is not supported without ffmpeg.
