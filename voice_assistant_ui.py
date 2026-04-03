import os
import time
import json
import subprocess
import tempfile
import requests
import gradio as gr
from faster_whisper import WhisperModel

# --- Ajustes por defecto (puedes cambiarlos en la UI) ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")  # cambia si prefieres mistral / qwen2.5:7b
PIPER_MODEL = os.environ.get("PIPER_MODEL", "/home/jonathan/ai/piper/es_ES-mls_9972-low.onnx")
PIPER_CONFIG = os.environ.get("PIPER_CONFIG", "/home/jonathan/ai/piper/es_ES-mls_9972-low.onnx.json")

# Cargamos Whisper una vez (CPU por defecto para máxima compatibilidad)
WHISPER_DEVICE_DEFAULT = "cpu"  # puedes poner "cuda" si ya tienes cuDNN OK
_whisper_cache = {}

SPACE_INVADERS_CSS = """
.gradio-container {
    font-family: "VT323", "Press Start 2P", "Lucida Console", monospace !important;
    background:
        radial-gradient(1100px 700px at 20% -10%, #152241 0%, #06070d 55%),
        radial-gradient(1000px 600px at 120% 120%, #101b32 0%, #06070d 60%) !important;
    color: #d5ffe6 !important;
}

.gradio-container::before {
    content: "";
    position: fixed;
    inset: 0;
    pointer-events: none;
    background: repeating-linear-gradient(to bottom, rgba(255,255,255,.03) 0 1px, transparent 1px 4px);
    mix-blend-mode: soft-light;
    z-index: 0;
}

.gradio-container > * {
    position: relative;
    z-index: 1;
}

h1, h2, h3, label, .prose, .gr-markdown {
    color: #d5ffe6 !important;
    text-shadow: 0 0 8px rgba(62, 252, 154, .35);
}

.block, .gr-panel, .gr-box, .gr-form, .gr-accordion {
    background: linear-gradient(160deg, #0d1220 0%, #090d18 100%) !important;
    border: 2px solid #1f7eaf !important;
    border-radius: 6px !important;
    box-shadow: 0 0 0 1px rgba(62, 252, 154, .18) inset, 0 0 18px rgba(56, 168, 255, .12) !important;
}

input, textarea, select, .gr-textbox, .gr-dropdown, .gr-audio {
    background: #081122 !important;
    border: 1px solid #2a8fd6 !important;
    color: #d5ffe6 !important;
    box-shadow: 0 0 0 1px rgba(62, 252, 154, .12) inset !important;
}

button, .gr-button {
    background: linear-gradient(180deg, #15345f 0%, #10233d 100%) !important;
    border: 1px solid #2ea8ff !important;
    color: #e5f4ff !important;
}

button:hover, .gr-button:hover {
    background: linear-gradient(180deg, #1d4b88 0%, #15345f 100%) !important;
}
"""

def get_whisper_model(size:str, device:str):
    key = (size, device)
    if key not in _whisper_cache:
        _whisper_cache[key] = WhisperModel(size, device=device)
    return _whisper_cache[key]

def transcribe(audio_path:str, size:str="medium", device:str=WHISPER_DEVICE_DEFAULT, task:str="transcribe", lang:str="auto"):
    model = get_whisper_model(size, device)
    opts = {}
    if task in ("transcribe", "translate"):
        opts["task"] = task
    if lang and lang != "auto":
        opts["language"] = lang
    segments, info = model.transcribe(audio_path, **opts)
    text = "".join(seg.text for seg in segments).strip()
    # también devolvemos timestamps por si quieres mostrarlos luego
    times = [(seg.start, seg.end, seg.text) for seg in segments]
    return text, times

def ollama_generate(prompt:str, model:str=DEFAULT_MODEL, temperature:float=0.7, system:str="Eres un asistente útil y conciso. Responde en español."):
    url = f"{OLLAMA_URL}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "options": {"temperature": temperature},
        "system": system,
        "stream": False
    }
    r = requests.post(url, json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    return data.get("response", "").strip()

def tts_piper(text:str, out_wav:str, model_path:str=PIPER_MODEL, config_path:str=PIPER_CONFIG, length_scale:float=1.0):
    os.makedirs(os.path.dirname(out_wav), exist_ok=True)
    cmd = [
        "piper",
        "--model", model_path,
        "--config", config_path,
        "--length_scale", str(length_scale),
        "--output_file", out_wav
    ]
    # Piper recibe el texto por stdin
    proc = subprocess.run(
        cmd,
        input=text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False
    )
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="ignore")
        raise RuntimeError(f"Error en Piper:\n{err}")
    return out_wav

def pipeline(mic_file, whisper_size, whisper_device, whisper_task, whisper_lang, model_name, temperature, tts_speed):
    if not mic_file:
        return gr.update(value=None), "", "No se recibió audio del micrófono."

    # 1) STT
    try:
        user_text, _timestamps = transcribe(
            mic_file, size=whisper_size, device=whisper_device, task=whisper_task, lang=whisper_lang
        )
    except Exception as e:
        return gr.update(value=None), "", f"Fallo en transcripción: {e}"

    if not user_text:
        return gr.update(value=None), "", "No se detectó texto en el audio."

    # 2) LLM
    try:
        system_msg = "Eres un asistente útil y conciso. Responde en español, en 2-3 frases como máximo."
        assistant = ollama_generate(user_text, model=model_name, temperature=temperature, system=system_msg)
    except Exception as e:
        return gr.update(value=None), user_text, f"Fallo en Ollama: {e}"

    # 3) TTS
    try:
        out_name = f"reply_{int(time.time())}.wav"
        out_path = os.path.join("/home/jonathan/ai/voice_out", out_name)
        wav_path = tts_piper(assistant, out_path, length_scale=tts_speed)
    except Exception as e:
        return gr.update(value=None), user_text, f"Fallo en Piper: {e}"

    return wav_path, user_text, assistant

with gr.Blocks(title="Asistente de Voz Local", css=SPACE_INVADERS_CSS) as ui:
    gr.Markdown("# 🗣️ Asistente de Voz (Whisper + Ollama + Piper) — Offline")
    with gr.Row():
        with gr.Column():
            audio_in = gr.Audio(sources=["microphone"], type="filepath", label="🎤 Graba aquí (clic para grabar y otra vez para parar)")
            btn = gr.Button("▶️ Transcribir → Responder → Hablar", variant="primary")
        with gr.Column():
            t_user = gr.Textbox(label="🧑‍💻 Texto detectado", interactive=False)
            t_assistant = gr.Textbox(label="🤖 Respuesta", interactive=False)
            audio_out = gr.Audio(label="🔊 Voz sintetizada", interactive=False)

    with gr.Accordion("Ajustes", open=False):
        with gr.Row():
            whisper_size = gr.Dropdown(
                ["tiny", "base", "small", "medium", "large-v2"], value="medium", label="Modelo Whisper"
            )
            whisper_device = gr.Dropdown(["cpu", "cuda"], value=WHISPER_DEVICE_DEFAULT, label="Dispositivo Whisper")
            whisper_task = gr.Dropdown(["transcribe", "translate"], value="transcribe", label="Tarea")
            whisper_lang = gr.Dropdown(
                ["auto","es","en","gl","pt","fr","de","it","ca"], value="auto", label="Lengua forzada (opcional)"
            )
        with gr.Row():
            model_name = gr.Textbox(value=DEFAULT_MODEL, label="Modelo Ollama (ej: llama3.1 / mistral / qwen2.5:7b)")
            temperature = gr.Slider(0.0, 1.5, value=0.7, step=0.1, label="Temperatura (creatividad)")
            tts_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.05, label="Velocidad de voz (Piper length_scale)")

    btn.click(
        fn=pipeline,
        inputs=[audio_in, whisper_size, whisper_device, whisper_task, whisper_lang, model_name, temperature, tts_speed],
        outputs=[audio_out, t_user, t_assistant]
    )

if __name__ == "__main__":
    # Puerto 7862 para no chocar con otras UIs
    ui.launch(server_name="0.0.0.0", server_port=7862)
