"""Voice converter: turns the studio's TTS speech into each character's own voice.

Hebrew TTS has a single male voice (Avri). Seed-VC (https://github.com/Plachtaa/seed-vc, GPL-3.0,
zero-shot) keeps his words and timing but swaps the voice for a short reference recording, so
lip-sync timings from the TTS stay valid. It runs as a separate local process because it needs its
own Python 3.11 environment and GPU (MPS); the studio calls it over HTTP and falls back to Avri
when it isn't running.

  POST /convert?speaker=stats   body: MP3 audio   ->   MP3 audio in that character's voice

Run (see README "Character voices"):
  tools/seed-vc/.venv/bin/python voice/converter_server.py
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
SEED_VC_DIR = Path(os.getenv("SEED_VC_DIR", ROOT / "tools" / "seed-vc"))
VOICES_DIR = Path(os.getenv("VOICES_DIR", ROOT / "tools" / "voices"))  # private recordings, not in git
PORT = 8020

# Studio speaker id -> reference recording (~10s of that character's voice)
REFERENCES = {"host": "avi", "stats": "miki", "karusela": "yossi", "agent": "moti", "fan": "tzachi"}

log = logging.getLogger("voice")

os.chdir(SEED_VC_DIR)  # Seed-VC loads its configs and checkpoints by relative path
sys.path.insert(0, str(SEED_VC_DIR))
import inference  # noqa: E402  (Seed-VC's own inference script)

# inference.main() reloads the models and saves with torchaudio (which needs torchcodec) on every
# call; load the models once and capture the output wave instead.
_models = inference.load_models(argparse.Namespace(
    fp16=False, f0_condition=False, checkpoint=None, config=None))
inference.load_models = lambda args: _models
_output = {}
inference.torchaudio.save = lambda _path, wave, sr: _output.update(wave=wave, sr=sr)


def convert(mp3: bytes, speaker: str) -> bytes:
    """Speak the same audio in `speaker`'s voice. Output length equals input length."""
    with tempfile.NamedTemporaryFile(suffix=".mp3") as source:
        source.write(mp3)
        source.flush()
        inference.main(argparse.Namespace(
            source=source.name, target=str(VOICES_DIR / f"{REFERENCES[speaker]}.wav"),
            output=tempfile.gettempdir(), diffusion_steps=30, length_adjust=1.0,
            inference_cfg_rate=0.7, f0_condition=False, auto_f0_adjust=False, semi_tone_shift=0,
            checkpoint=None, config=None, fp16=False))
    out = BytesIO()
    sf.write(out, _output["wave"].squeeze(0).numpy(), _output["sr"], format="MP3")
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        url = urlparse(self.path)
        speaker = parse_qs(url.query).get("speaker", [""])[0]
        if url.path != "/convert" or speaker not in REFERENCES:
            self.send_error(404, "use POST /convert?speaker=<host|stats|karusela|agent|fan>")
            return
        started = time.time()
        audio = convert(self.rfile.read(int(self.headers["Content-Length"])), speaker)
        log.info("%s converted in %.1fs", speaker, time.time() - started)
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    missing = [f"{name}.wav" for name in REFERENCES.values() if not (VOICES_DIR / f"{name}.wav").exists()]
    if missing:
        sys.exit(f"missing reference recordings in {VOICES_DIR}: {', '.join(missing)}")
    log.info("voice converter ready on http://localhost:%d", PORT)
    # Single-threaded on purpose: one conversion at a time on the GPU.
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
