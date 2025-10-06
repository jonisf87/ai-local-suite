# voice_assistant_live3.py
# UI local: Whisper (ASR) → Ollama (LLM) → Piper (TTS)
# Máxima compatibilidad con distintas versiones de Gradio.

import os
import inspect
import subprocess
import datetime as dt
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import gradio as gr
import requests
from faster_whisper import WhisperModel

# ---------- Config ----------
OUT_DIR = Path.home() / "ai" / "voice_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PIPER_BIN = "piper"
PIPER_MODEL = str(Path.home() / "ai" / "piper" / "es_ES-mls_9972-low.onnx")
PIPER_CONFIG = PIPER_MODEL + ".json"

DEFAULT_ASR_MODEL = "medium"   # tiny/base/small/medium/large-v3
DEFAULT_ASR_DEVICE = "cpu"     # usa "cpu" (seguro). Cambia a "cuda" si tienes cuDNN listo
DEFAULT_LLM_MODEL = "llama3.1"
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# ---------- Whisper cache ----------
_WHISPER = {"name": None, "device": None, "model": None}
def get_whisper(model_name: str, device: str) -> WhisperModel:
    if (_WHISPER["model"] is None or
        _WHISPER["name"] != model_name or
        _WHISPER["device"] != device):
        _WHISPER["model"] = WhisperModel(model_name, device=device)
        _WHISPER["name"] = model_name
        _WHISPER["device"] = device
    return _WHISPER["model"]

# ---------- Helpers ----------
def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def ollama_generate(prompt: str,
                    model: str = DEFAULT_LLM_MODEL,
                    temperature: float = 0.7,
                    top_p: float = 0.9,
                    system: Optional[str] = None) -> str:
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "top_p": top_p},
    }
    if system:
        payload["system"] = system
    try:
        r = requests.post(url, json=payload, timeout=600)
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        return f"[Ollama error] {e}"

def translate_to_english_with_llm(text: str) -> str:
    if not text:
        return ""
    prompt = (
        "Translate the following Spanish (or mixed-language) text into clear English. "
        "Only output the translation:\n\n"
        f"{text}"
    )
    return ollama_generate(prompt)

def transcribe_whisper(audio_path: str,
                       model_name: str = DEFAULT_ASR_MODEL,
                       device: str = DEFAULT_ASR_DEVICE,
                       language: Optional[str] = None,
                       task: str = "transcribe") -> Tuple[str, str]:
    model = get_whisper(model_name, device)
    segments, info = model.transcribe(
        audio_path,
        task=task,                  # "transcribe" o "translate"
        language=language or None,  # None = auto
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    text = "".join(s.text for s in segments).strip()
    if task == "translate":
        return text, text
    translated = translate_to_english_with_llm(text) if text else ""
    return text, translated

def chat_with_llm(user_text: str) -> str:
    if not user_text:
        return ""
    prompt = (
        "Eres un asistente útil que responde de forma breve y clara. "
        "Responde en el idioma del usuario:\n\n"
        f"Usuario: {user_text}\nAsistente:"
    )
    return ollama_generate(prompt)

def tts_piper(text: str,
              out_wav: Path,
              model_path: str = PIPER_MODEL,
              config_path: str = PIPER_CONFIG,
              length_scale: float = 1.0) -> Path:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        PIPER_BIN,
        "--model", model_path,
        "--config", config_path,
        "--length_scale", str(length_scale),
        "--output_file", str(out_wav),
    ]
    try:
        subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Piper TTS error:\n{e.stderr.decode(errors='ignore')}") from e
    return out_wav

def pipeline_core(audio_file: Optional[str],
                  sample_rate: int,
                  task: str,
                  language: Optional[str],
                  asr_model: str,
                  tts_speed: float,
                  chat_history: Optional[List[Dict[str, str]]] = None):
    messages = chat_history[:] if chat_history else []
    if not audio_file or not Path(audio_file).exists():
        messages.append({"role": "assistant", "content": "No recibí audio. ¿Puedes grabar de nuevo?"})
        return messages, "", "", "No hay audio.", None

    trans, trans_en = transcribe_whisper(
        audio_file,
        model_name=asr_model or DEFAULT_ASR_MODEL,
        device=DEFAULT_ASR_DEVICE,
        language=language or None,
        task=task,
    )
    reply = chat_with_llm(trans or trans_en)
    out_wav = OUT_DIR / f"reply_{_ts()}.wav"
    wav_path = None
    if reply:
        try:
            tts_piper(reply, out_wav, length_scale=tts_speed or 1.0)
            wav_path = str(out_wav)
        except Exception as e:
            reply += f"\n\n[Nota TTS] {e}"

    if trans:
        messages.append({"role": "user", "content": trans})
    elif trans_en:
        messages.append({"role": "user", "content": trans_en})
    messages.append({"role": "assistant", "content": reply or "(sin respuesta)"})
    return messages, trans, trans_en, reply, wav_path

def pipeline_from_mic(audio_file, sample_rate, task, language, asr_model, tts_speed, chat_state):
    return pipeline_core(audio_file, sample_rate, task, language, asr_model, tts_speed, chat_history=chat_state)

def pipeline_from_upload(audio_file, sample_rate, task, language, asr_model, tts_speed, chat_state):
    return pipeline_core(audio_file, sample_rate, task, language, asr_model, tts_speed, chat_history=chat_state)

# ---------- UI builders con detección de firma ----------
def create_audio_mic():
    sig = inspect.signature(gr.Audio.__init__)
    kwargs = {}
    if "sources" in sig.parameters:
        kwargs["sources"] = ["microphone"]
    elif "source" in sig.parameters:
        kwargs["source"] = "microphone"
    if "type" in sig.parameters:
        kwargs["type"] = "filepath"
    # No pasar show_recording_waveform ni show_controls: rompen en versiones antiguas
    return gr.Audio(**kwargs)

def create_chatbot():
    sig = inspect.signature(gr.Chatbot.__init__)
    kwargs = {"label": "Historial", "height": 420}
    if "type" in sig.parameters:
        kwargs["type"] = "messages"   # si existe, evitamos warning
    return gr.Chatbot(**kwargs)

TITLE = "# 🗣️ Asistente de Voz Local — Whisper + Ollama + Piper"

def build_ui():
    with gr.Blocks(css="#chat_hist {max-height: 480px;}") as ui:
        gr.Markdown(TITLE)

        with gr.Row():
            with gr.Column(scale=4):
                mic = create_audio_mic()
                process_btn = gr.Button("▶️ Procesar último clip")

                # Controles
                asr_model_dd = gr.Dropdown(
                    label="Modelo Whisper",
                    choices=["tiny", "base", "small", "medium", "large-v3"],
                    value=DEFAULT_ASR_MODEL,
                )
                lang_dd = gr.Dropdown(
                    label="Idioma (vacío = auto)",
                    choices=["", "es", "en", "fr", "de", "it", "pt", "gl", "ca"],
                    value="es",
                )
                task_dd = gr.Dropdown(
                    label="Tarea ASR",
                    choices=["transcribe", "translate"],
                    value="transcribe",
                )
                sample_rate_dd = gr.Slider(
                    label="Sample Rate (informativo)",
                    minimum=16000, maximum=48000, step=1000, value=16000
                )
                tts_speed_sl = gr.Slider(
                    label="Velocidad voz (Piper length_scale)",
                    minimum=0.6, maximum=1.6, step=0.05, value=1.0
                )

            with gr.Column(scale=6):
                chatbox = create_chatbot()
                transcribed_txt = gr.Textbox(label="Transcripción (ASR)")
                translated_txt = gr.Textbox(label="Traducción (EN)")
                reply_txt = gr.Textbox(label="Respuesta del asistente")
                reply_wav = gr.Audio(label="Respuesta en voz (Piper)", type="filepath")

        chat_state = gr.State(value=[])

        inputs_common = [
            mic,               # ruta del audio (filepath)
            sample_rate_dd,
            task_dd,
            lang_dd,
            asr_model_dd,
            tts_speed_sl,
            chat_state,
        ]
        outputs_common = [
            chatbox,
            transcribed_txt,
            translated_txt,
            reply_txt,
            reply_wav,
        ]

        # En versiones nuevas existe stop_recording; si no, usamos change
        if hasattr(mic, "stop_recording"):
            mic.stop_recording(
                fn=pipeline_from_mic,
                inputs=inputs_common,
                outputs=outputs_common,
                queue=True,
            )
        else:
            mic.change(
                fn=pipeline_from_mic,
                inputs=inputs_common,
                outputs=outputs_common,
                queue=True,
            )

        process_btn.click(
            fn=pipeline_from_upload,
            inputs=inputs_common,
            outputs=outputs_common,
            queue=True,
        )

        ui.queue().launch(server_name="0.0.0.0", server_port=7862)

if __name__ == "__main__":
    build_ui()
