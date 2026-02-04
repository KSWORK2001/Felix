import base64
import tempfile
from datetime import datetime
from typing import Any, Dict, List, Optional


class Assistant:
    def __init__(self, db, base_dir: str):
        self.db = db
        self.base_dir = base_dir

    def transcribe_audio(self, audio_base64: str, filename: str) -> str:
        raw = base64.b64decode(audio_base64)
        suffix = ("." + filename.split(".")[-1]) if "." in filename else ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(raw)
            tmp_path = f.name

        try:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                return "[Whisper not installed - please install faster-whisper]"

            try:
                model = WhisperModel("base", device="cpu", compute_type="int8")
                segments, _info = model.transcribe(tmp_path)
                text = " ".join([seg.text.strip() for seg in segments]).strip()
                if not text:
                    return "[No speech detected]"
                return text
            except Exception as e:
                return f"[Transcription error: {str(e)[:100]}]"
        finally:
            try:
                import os

                os.unlink(tmp_path)
            except Exception:
                pass

    def generate_speech_wav_base64(self, text: str) -> Optional[str]:
        if not text or not text.strip():
            return None

        try:
            from kokoro import KPipeline
            import soundfile as sf
            import numpy as np

            pipeline = KPipeline(lang_code="a", device="cuda")
            
            generator = pipeline(text, voice="af_heart", speed=1.0)
            
            audio_chunks = []
            sample_rate = 24000
            
            for chunk in generator:
                if hasattr(chunk, 'audio') and chunk.audio is not None:
                    audio_chunks.append(chunk.audio)
                elif isinstance(chunk, tuple) and len(chunk) >= 1:
                    audio_data = chunk[0] if not isinstance(chunk[0], int) else chunk[1] if len(chunk) > 1 else None
                    if audio_data is not None:
                        audio_chunks.append(audio_data)
                        if isinstance(chunk, tuple) and len(chunk) > 1 and isinstance(chunk[-1], int):
                            sample_rate = chunk[-1]
            
            if not audio_chunks:
                return None
                
            audio = np.concatenate(audio_chunks) if len(audio_chunks) > 1 else audio_chunks[0]

            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                wav_path = f.name

            try:
                sf.write(wav_path, audio, sample_rate)
                with open(wav_path, "rb") as wf:
                    return base64.b64encode(wf.read()).decode("utf-8")
            finally:
                try:
                    import os
                    os.unlink(wav_path)
                except Exception:
                    pass
        except ImportError:
            return None
        except Exception as e:
            print(f"[Felix TTS Error]: {e}")
            return None
