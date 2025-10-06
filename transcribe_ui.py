import gradio as gr
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
import os

# ===== CONFIGURACIÓN DEL MODELO =====
MODEL_SIZE = "medium"
DEVICE = "cuda"  # cambia a "cpu" si no tienes GPU
model = WhisperModel(MODEL_SIZE, device=DEVICE)

# ===== FUNCIÓN PRINCIPAL =====
def transcribe_audio(audio_path, traducir_es, traducir_en):
    if audio_path is None:
        return "⚠️ No se ha subido ningún archivo."

    # --- Transcripción ---
    segments, info = model.transcribe(audio_path)
    full_text = " ".join([seg.text for seg in segments])

    # --- Guardado automático ---
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    os.makedirs("transcripts", exist_ok=True)
    output_file = f"transcripts/{base_name}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(full_text)

    # --- Traducciones opcionales ---
    result = f"🗣️ **Transcripción original:**\n{full_text}\n"
    if traducir_es:
        try:
            translated_es = GoogleTranslator(source='auto', target='es').translate(full_text)
            result += f"\n🇪🇸 **Traducción al español:**\n{translated_es}\n"
        except Exception as e:
            result += f"\n⚠️ Error traduciendo al español: {e}\n"

    if traducir_en:
        try:
            translated_en = GoogleTranslator(source='auto', target='en').translate(full_text)
            result += f"\n🇬🇧 **Translation to English:**\n{translated_en}\n"
        except Exception as e:
            result += f"\n⚠️ Error traduciendo al inglés: {e}\n"

    return result

# ===== INTERFAZ GRADIO =====
with gr.Blocks(theme=gr.themes.Soft()) as ui:
    gr.Markdown("# 🎧 Transcriptor Inteligente Local (Whisper + Gradio)")
    gr.Markdown("Sube un archivo de audio y obtén la transcripción con traducción opcional al español e inglés.")

    with gr.Row():
        audio_input = gr.Audio(label="Archivo de audio", type="filepath")

    with gr.Row():
        traducir_es_checkbox = gr.Checkbox(label="Traducir al español 🇪🇸", value=True)
        traducir_en_checkbox = gr.Checkbox(label="Traducir al inglés 🇬🇧", value=False)

    output_text = gr.Textbox(label="Resultado", lines=15)

    transcribe_btn = gr.Button("🚀 Transcribir")

    transcribe_btn.click(
        fn=transcribe_audio,
        inputs=[audio_input, traducir_es_checkbox, traducir_en_checkbox],
        outputs=[output_text]
    )

# ===== LANZAMIENTO SERVIDOR =====
if __name__ == "__main__":
    ui.launch(server_name="0.0.0.0", server_port=7860)
