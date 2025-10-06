AI-LocalSuite — Manual técnico paso a paso (uso local)
Ruta base del proyecto: /home/jonathan/ai

Puertos por defecto:
- ComfyUI:      8188
- Open WebUI:   8080  (conecta a Ollama en 11434)
- Ollama API:   11434 (systemd --user)
- Voice UI:     7862  (script voice_assistant_ui.py o live)
- Landing UI:   5000  (script landing UI)

Estructura recomendada de carpetas:
  # AI-LocalSuite — Manual técnico paso a paso (uso local)

  **Ruta base del proyecto:** `/home/jonathan/ai`

  ## Puertos por defecto

  - ComfyUI: 8188
  - Open WebUI: 8080 (conecta a Ollama en 11434)
  - Ollama API: 11434 (systemd --user)
  - Voice UI: 7862 (script `voice_assistant_ui.py` o variantes live)
  - Landing UI: 5000 (script `landing_ui.py`)

  ## Estructura recomendada de carpetas

  ```
  /home/jonathan/ai
  ├── ComfyUI/                 (generación de imágenes)
  ├── audio/                   (audios de prueba)
  ├── models/                  (modelos propios opcionales)
  ├── piper/                   (modelos TTS Piper *.onnx y *.json)
  ├── voice_out/               (salida de audio del TTS)
  ├── ai-local-suite/          (repositorio “suite” con scripts y docs)
  ├── transcribe_ui.py         (UI de transcripción Whisper)
  ├── voice_assistant_ui.py    (UI de asistente de voz)
  ├── voice_assistant_live*.py (variantes live del asistente de voz)
  ├── landing_ui.py            (landing local para lanzar UIs)
  └── (otros scripts .py)
  ```

  ---

  ## 0) Preparación de sistema (WSL2 Ubuntu)

  Actualizar paquetes:

  ```bash
  sudo apt update && sudo apt upgrade -y
  ```

  Instalar herramientas base:

  ```bash
  sudo apt install -y build-essential curl git python3 python3-venv python3-pip ffmpeg
  ```

  Comprobar versión de Python:

  ```bash
  python3 --version
  ```

  Crear y activar entorno virtual (ejemplo en `~/ai`):

  ```bash
  mkdir -p ~/ai && cd ~/ai
  python3 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip wheel
  ```

  ## 1) Ollama (LLM local) + servicio de usuario

  Instalar Ollama:

  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```

  Ver estado del servicio de usuario:

  ```bash
  systemctl --user status ollama
  ```

  Si no está activo:

  ```bash
  systemctl --user enable ollama
  systemctl --user start ollama
  ```

  Probar API:

  ```bash
  curl http://127.0.0.1:11434/api/tags
  ```

  Descargar modelos base (elige 1–2):

  ```bash
  ollama pull llama3.1
  ollama pull mistral
  ollama pull qwen2.5:7b
  ollama pull codellama
  ```

  Comprobar logs si algo falla:

  ```bash
  journalctl --user -u ollama -n 100 --no-pager
  ```

  ## 2) Open WebUI (frontal web sobre Ollama)

  Requisitos: Docker instalado y servicio activo.

  Lanzar contenedor Open WebUI:

  ```bash
  docker run -d --name open-webui \
    -p 8080:8080 \
    -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    -e WEBUI_NAME="Local WebUI" \
    -v openwebui-data:/app/backend/data \
    --restart unless-stopped \
    ghcr.io/open-webui/open-webui:latest
  ```

  Comprobar estado:

  ```bash
  docker ps
  docker logs -f open-webui
  ```

  Abrir en el navegador:

  ```
  http://localhost:8080
  ```

  > En Settings → Providers debe apuntar a `http://127.0.0.1:11434`.

  ## 3) Whisper (transcripción) con faster-whisper

  Desde el entorno virtual:

  ```bash
  source ~/ai/venv/bin/activate
  pip install faster-whisper gradio av
  ```

  Prueba rápida por línea de comandos (CPU):

  ```bash
  python - <<'EOF'
  from faster_whisper import WhisperModel
  model = WhisperModel("medium", device="cpu")
  segments, info = model.transcribe("/home/jonathan/ai/audio/test.mp3")
  for s in segments:
      print(f"[{s.start:.2f} -> {s.end:.2f}] {s.text}")
  EOF
  ```

  Lanzar la UI de transcripción (por defecto en 7860):

  ```bash
  python /home/jonathan/ai/transcribe_ui.py
  # Abrir: http://localhost:7860
  ```

  Nota CUDA (opcional): si aparece error de cuDNN, prueba con `device="cpu"` o instala la versión de cuDNN compatible.

  ## 4) Piper (Text-to-Speech offline)

  Instalar el binario Piper (ejemplo Ubuntu):

  ```bash
  sudo apt install -y piper-tts
  ```

  Descargar modelos de voz (ejemplo español):

  ```bash
  mkdir -p ~/ai/piper ~/ai/voice_out
  # Copia en ~/ai/piper los archivos .onnx y su .json (ej: es_ES-mls_9972-low.onnx y es_ES-mls_9972-low.onnx.json)
  ```

  Probar TTS:

  ```bash
  echo "Hola, esto es una prueba." | \
    piper --model ~/ai/piper/es_ES-mls_9972-low.onnx \
          --config ~/ai/piper/es_ES-mls_9972-low.onnx.json \
          --length_scale 1.0 \
          --output_file ~/ai/voice_out/test.wav
  ```

  Reproducir el WAV desde Windows/WSL con un reproductor del host.

  ## 5) ComfyUI (SDXL / imágenes generativas)

  Ubicación típica: `~/ai/ComfyUI`

  Arranque (puerto 8188):

  ```bash
  cd ~/ai/ComfyUI
  # Opción A
  python main.py --listen 0.0.0.0 --port 8188
  # Opción B (si tienes script run.sh)
  ./run.sh --listen 0.0.0.0 --port 8188
  ```

  Abrir: `http://localhost:8188`

  Modelos de upscale recomendados (`~/ai/ComfyUI/models/upscale_models/`):

  - `RealESRGAN_x4plus.pth`

  Modelos SDXL (`~/ai/ComfyUI/models/checkpoints/`):

  - `sdxl_base_1.0.safetensors`
  - `sdxl_refiner_1.0.safetensors`

  Errores típicos y notas de solución están en el manual original; sigue la guía si aparecen mensajes relacionados con shapes o versiones.

  ## 6) Voice Assistant UI (Whisper + Ollama + Piper)

  Requisitos básicos:

  - Ollama activo (11434)
  - Modelos Piper en `~/ai/piper`
  - Carpeta de salida TTS: `~/ai/voice_out`
  - `faster-whisper` instalado

  Lanzar la UI (puerto 7862):

  ```bash
  source ~/ai/venv/bin/activate
  python /home/jonathan/ai/voice_assistant_ui.py
  # Abrir: http://localhost:7862
  ```

  Flujo interno resumido:

  1. Grabar audio o subir un WAV/MP3.
  2. Whisper transcribe.
  3. Prompt a Ollama.
  4. Respuesta de texto → TTS Piper → WAV en `~/ai/voice_out`.
  5. La UI reproduce el WAV.

  ## 7) Landing UI (puerto 5000) — lanzador y guía

  Objetivo: ofrecer una portada con botones para abrir las UIs (ComfyUI, Open WebUI, Voice UI, Transcribe UI) y mostrar estado/health.

  Ejecutar:

  ```bash
  source ~/ai/venv/bin/activate
  python /home/jonathan/ai/landing_ui.py
  # Abrir: http://localhost:5000
  ```

  Comprobar puertos en caso de conflicto:

  ```bash
  ss -tulpn | grep -E ":8188|:8080|:7862|:5000|:11434"
  ```

  ## 8) Puesta en marcha — orden recomendado

  1. Arrancar Ollama (systemd user)
  2. Lanzar Open WebUI (Docker)
  3. Lanzar ComfyUI
  4. Lanzar Voice UI
  5. Lanzar Landing UI

  ## 9) Git — subir `ai-local-suite` a repositorio privado

  Estructura mínima del repositorio:

  ```
  ~/ai/ai-local-suite/
  ├── README.md
  ├── scripts/
  └── (otros archivos)
  ```

  Comandos básicos para inicializar y subir:

  ```bash
  cd ~/ai/ai-local-suite
  git init
  git add .
  git commit -m "AI Local Suite: primera versión"
  git branch -M main
  git remote add origin git@github.com:TU_USUARIO/ai-local-suite.git
  git push -u origin main
  ```

  > Crea el repo en GitHub (privado) y añade tu clave SSH si usas SSH.

  ## 10) Comandos útiles de diagnóstico

  - Ollama: `systemctl --user status ollama`, `journalctl --user -u ollama -n 100 --no-pager`, `curl http://127.0.0.1:11434/api/tags`
  - Open WebUI (Docker): `docker ps`, `docker logs -f open-webui`, `curl -I http://127.0.0.1:8080`
  - ComfyUI: `ss -tulpn | grep :8188`, `curl -I http://127.0.0.1:8188`
  - Voice UI: `ss -tulpn | grep :7862`, `curl -I http://127.0.0.1:7862`
  - Landing UI: `ss -tulpn | grep :5000`, `curl -I http://127.0.0.1:5000`
  - General: `nvidia-smi`, `ffmpeg -version`, `which piper`, `piper --help`

  ## 11) Buenas prácticas

  - Fija puertos en variables al inicio de cada script para mantener coherencia.
  - Evita dependencias CUDA si no son necesarias; `cpu` en Whisper funciona para audios cortos.
  - En ComfyUI, usa flujos mínimos (KSampler “normal”) antes de complicar con Advanced.
  - Mantén modelos y pesos en rutas claras (`~/ai/...`).
  - Versiona sólo scripts y docs; no subas modelos pesados al repo (usa `.gitignore`).

  ## 12) Prompt para transformar esta doc en “presentación de producto”

  Usa este prompt en tu LLM favorito (por ejemplo via Open WebUI):

  > "Convierte el siguiente manual técnico en una presentación de producto clara y persuasiva para un público no técnico. Enfatiza beneficios, casos de uso, mensajes clave y diferenciadores. Resalta que funciona 100% local (privacidad, coste), que incluye generación de imágenes (ComfyUI), chat con LLM (Ollama + Open WebUI) y asistente de voz (Whisper + Piper). Estructura en secciones: Resumen ejecutivo, Funcionalidades, Beneficios, Casos de uso, Requisitos, Guía rápida, Mantenimiento. Usa un tono conciso, visual y orientado a valor. Mantén la precisión técnica mínima necesaria. Aquí está el texto técnico completo: <<PEGA AQUÍ TODO EL MANUAL>>"

  ---

  FIN
