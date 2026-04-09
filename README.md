  # AI-LocalSuite — Manual técnico paso a paso (uso local)

  **Ruta base del proyecto:** `/home/jonathan/ai`

  ## Puertos por defecto

  - ComfyUI: 8188
  - Open WebUI: 8080 (conecta a Ollama en 11434)
  - Ollama API: 11434 (systemd --user)
  - Voice UI: 7862 (script `voice_assistant_ui.py` o variantes live)
  - Landing Manager UI: 5000 (script `landing_manager.py`)

  ## Estructura recomendada de carpetas

  ```text
  /home/jonathan/ai
  ├── ComfyUI/                   (generación de imágenes y vídeo)
  │   └── workflows/             (workflows por personaje: akika_video.json, etc.)
  ├── piper/                     (modelos TTS Piper *.onnx y *.json)
  ├── voice_out/                 (salida de audio del TTS)
  ├── modelfiles/                (Modelfiles personalizados de Ollama)
  │   ├── security-auditor
  │   ├── python-expert
  │   ├── devops-expert
  │   ├── voice-assistant
  │   ├── custom
  │   ├── create-all-models.sh
  │   └── README.md
  ├── venv/                      (entorno virtual Python compartido)
  └── ai-local-suite/            (este repositorio)
      ├── landing_manager.py     (gestor web — puerto 5000)
      ├── transcribe_ui.py       (UI transcripción Whisper — puerto 7860)
      ├── voice_assistant_ui.py  (UI asistente de voz — puerto 7862)
      ├── voice_assistant_live3.py (variante live del asistente)
      ├── requirements.txt
      ├── .env.example
      ├── static/                (assets estáticos, actualmente vacío)
      ├── voice_out/             (salida TTS local al repo)
      └── README.md
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

  ### Modelos Personalizados (Modelfiles)

  La carpeta `~/ai/modelfiles/` contiene Modelfiles para crear modelos especializados:

  **Modelos disponibles:**
  - `security-auditor`: Experto en auditoría de seguridad y análisis de vulnerabilidades
  - `python-expert`: Desarrollador Python senior con mejores prácticas
  - `devops-expert`: Arquitecto DevOps/SRE especializado en infraestructura
  - `voice-assistant`: Optimizado para respuestas cortas (ideal para TTS)

  **Crear todos los modelos:**

  ```bash
  cd ~/ai/modelfiles
  ./create-all-models.sh
  ```

  **Crear un modelo individual:**

  ```bash
  cd ~/ai/modelfiles
  ollama create security-auditor -f security-auditor
  ```

  **Usar un modelo personalizado:**

  ```bash
  # Interactivo
  ollama run security-auditor
  
  # Una pregunta
  ollama run python-expert "¿Cómo hago async en Python?"
  ```

  Los modelos aparecerán automáticamente en Open WebUI. Ver `~/ai/modelfiles/README.md` para documentación completa.

  ## 2) Open WebUI (frontal web sobre Ollama)

  Requisitos: Docker instalado y servicio activo.

  Lanzar contenedor Open WebUI:

  ```bash
  docker run -d --name open-webui \
    --network host \
    -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    -v openwebui-data:/app/backend/data \\
    --restart unless-stopped \\
    ghcr.io/open-webui/open-webui:latest
  ```

  > **Nota importante**: Usamos `--network host` para que Open WebUI pueda conectarse a Ollama que corre en el host. Esto es esencial en WSL2.

  Comprobar estado:

  ```bash
  docker ps
  docker logs -f open-webui
  ```

  Verificar que Open WebUI puede ver Ollama:

  ```bash
  docker exec open-webui curl -s http://127.0.0.1:11434/api/tags
  ```

  Abrir en el navegador:

  ```text
  http://localhost:8080
  ```

  **Configuración inicial en la UI**:
  
  1. Crea una cuenta o inicia sesión
  2. Ve a **Settings** (⚙️) → **Admin Panel** → **Connections**
  3. Verifica que **Ollama API URL** sea `http://127.0.0.1:11434`
  4. Haz clic en el botón de verificar conexión
  5. Deberías ver los modelos disponibles (mistral, llama3.1, etc.)

  **Personalizar System Prompt (Prompt Base)**:

  Para cambiar el comportamiento por defecto del modelo:

  1. **Prompt Global**: Ve a **Settings** → **General** → busca **"Indicador del sistema"** (System Prompt)
     - Este prompt se aplicará a todas tus conversaciones
     - Ejemplo para asistente técnico:
      ```text
       Eres un experto en Linux, Docker, Python y AI local.
       Trabajas principalmente con WSL2 Ubuntu.
       Das respuestas técnicas precisas con comandos listos para ejecutar.
       Prefieres soluciones simples y eficientes.
       ```

  2. **Prompt por Conversación**: En cada chat individual, haz clic en configuración del chat para personalizar solo esa conversación

  3. **Crear Personajes/Personas**: Ve a **Workspace** → **Personalization** para crear perfiles con prompts específicos

  **Ejemplos de prompts útiles**:

  - **Para asistente de voz** (respuestas cortas):
    ```text
    Eres un asistente de voz breve y directo.
    Respondes en máximo 2-3 oraciones cortas.
    Evitas listas largas y explicaciones extensas.
    Usas un lenguaje natural y conversacional.
    ```

  - **Para programación**:
    ```text
    Eres un desarrollador senior especializado en Python y JavaScript.
    Proporcionas código limpio, comentado y siguiendo mejores prácticas.
    Explicas el razonamiento detrás de tus soluciones.
    ```

  **Troubleshooting**: Si después de actualizar Open WebUI no ves modelos:
  
  ```bash
  # Recrear el contenedor con la configuración correcta
  docker stop open-webui && docker rm open-webui
  
  docker run -d --name open-webui \
    --network host \
    -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    -v openwebui-data:/app/backend/data \\
    --restart unless-stopped \\
    ghcr.io/open-webui/open-webui:latest
  
  # Verificar que funciona
  sleep 5
  docker exec open-webui curl -s http://127.0.0.1:11434/api/tags
  ```

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
  source ~/ai/venv/bin/activate
  python main.py
  # Si necesitas acceso desde fuera del host:
  # python main.py --listen 0.0.0.0
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

  ## 7) Landing Manager UI (puerto 5000) — gestor y lanzador

  `landing_manager.py` ofrece:

  - Auto‑arranque (autostart) de servicios si están caídos: Ollama (servicio), Open WebUI (Docker), ComfyUI y Voice UI.
  - Panel con estado (UP/DOWN) por puerto y botones Start / Stop / Restart (cuando aplica).
  - Apertura directa de cada interfaz en nuevas pestañas.
  - Visualización de modelos personalizados de Ollama con comando de uso.
  - Comandos de referencia incrustados con la configuración correcta.
  - Tool integrada de generación de vídeo con AnimateDiff SDXL (ver más abajo).

  Objetivo: centralizar en una sola página la gestión local de la suite sin recordar cada comando.

  Ejecutar:

  ```bash
  /home/jonathan/ai/venv/bin/pip install -r /home/jonathan/ai/ai-local-suite/requirements.txt
  /home/jonathan/ai/venv/bin/python /home/jonathan/ai/ai-local-suite/landing_manager.py
  # Abrir: http://localhost:5000
  ```

  > **Nota**: por defecto arranca en `127.0.0.1` y `debug=False`.
  > Si necesitas exponer en red o activar debug:
  > `LANDING_HOST=0.0.0.0 LANDING_DEBUG=1 /home/jonathan/ai/venv/bin/python /home/jonathan/ai/ai-local-suite/landing_manager.py`

  Comprobar puertos en caso de conflicto:

  ```bash
  ss -tulpn | grep -E ":8188|:8080|:7862|:5000|:11434"
  ```

  **Funciones del Landing Manager**:

  - ✅ Detección automática de servicios caídos
  - ✅ Arranque automático al iniciar (autostart)
  - ✅ Panel visual con estado en tiempo real
  - ✅ Botones Start / Stop / Restart por servicio
  - ✅ Enlaces directos a cada UI
  - ✅ Panel de modelos personalizados de Ollama
  - ✅ Tool de generación de vídeo (`/tools/video-scene`)

  ### Tool: Escena de vídeo (`/tools/video-scene`)

  Interfaz integrada que encola generaciones directamente en la API de ComfyUI
  usando AnimateDiff SDXL. Características:

  - **Personajes**: Akika, Hinata, Kaede — cada uno carga su workflow base desde `~/ai/ComfyUI/workflows/{id}_video.json` si existe, con prompt positivo/negativo por defecto embebido.
  - **Presets de modelo**: WAI NSFW Illustrious, RealVis XL V5, CyberRealistic XL V8, Juggernaut XL v9. También detecta automáticamente checkpoints SDXL compatibles instalados.
  - **Perfiles de suavidad**:
    - `Cinematic Stable` — 640×960, 32 frames, 10 fps, CFG 5.5, denoise 0.62
    - `Fluid Dynamic` — 640×960, 28 frames, 12 fps, CFG 5.2, denoise 0.66
  - Todos los parámetros (resolución, frames, fps, steps, CFG, denoise, CRF, pix_fmt, seed) son editables manualmente.
  - Si ComfyUI está caído al enviar, lo arranca automáticamente antes de encolar.
  - Los vídeos se guardan en `~/ai/ComfyUI/output/scene_builder/{personaje}/{timestamp}_{slug}.mp4`.

  ```bash
  # Acceder directamente
  # http://localhost:5000/tools/video-scene
  ```

  ## 8) Puesta en marcha — orden recomendado

  ### Opción A: Usando Landing Manager (Recomendado)

  ```bash
  cd /home/jonathan/ai/ai-local-suite
  /home/jonathan/ai/venv/bin/python landing_manager.py
  # Abre http://localhost:5000 y todos los servicios arrancarán automáticamente
  ```

  El Landing Manager detectará servicios caídos y los iniciará automáticamente en este orden:
  1. Ollama (si no está activo)
  2. Open WebUI (Docker)
  3. ComfyUI
  4. Voice Assistant UI

  ### Verificación rápida de arranque

  ```bash
  curl -sS http://127.0.0.1:5000/api/status
  # Ejemplo: {"adultchatbot":false,"comfy":true,"ollama":true,"openwebui":true,"voice":true}
  ```

  ## 9) Ejecutable del Landing Manager (PyInstaller)

  Sí, se puede generar ejecutable, pero **siempre por plataforma**.

  ### Build Linux (desde WSL/Ubuntu)

  ```bash
  cd /home/jonathan/ai/ai-local-suite
  chmod +x build_landing_executable.sh
  ./build_landing_executable.sh
  ```

  Binario Linux:

  ```bash
  dist/landing-manager/landing-manager
  ```

  ### Build Windows `.exe` (desde Windows nativo)

  Ejecuta PowerShell en el repo (no dentro de WSL):

  ```powershell
  cd \\wsl.localhost\Ubuntu\home\jonathan\ai\ai-local-suite
  powershell -ExecutionPolicy Bypass -File .\build_landing_executable.ps1
  ```

  EXE generado:

  ```text
  dist\landing-manager\landing-manager.exe
  ```

  Limitaciones importantes:

  - El build en Linux no sirve como `.exe` en Windows.
  - El build en Windows no sirve como binario Linux.
  - El ejecutable empaqueta el panel Flask, pero sigue necesitando servicios externos (`~/ai/ComfyUI`, Docker/Open WebUI, Ollama, etc.).

  ### Opción B: Manual (paso a paso)

  1. **Arrancar Ollama** (servicio de usuario):
     ```bash
     systemctl --user start ollama
     systemctl --user status ollama
     ```

  2. **Lanzar Open WebUI** (Docker):
     ```bash
     docker start open-webui || docker run -d --name open-webui \
       --network host \
       -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
       -v openwebui-data:/app/backend/data \\
       --restart unless-stopped \\
       ghcr.io/open-webui/open-webui:latest
     ```

  3. **Lanzar ComfyUI**:
     ```bash
     cd ~/ai/ComfyUI
     source ~/ai/venv/bin/activate
     python main.py --listen 0.0.0.0 --port 8188 &
     ```

  4. **Lanzar Voice UI**:
     ```bash
     cd ~/ai
     source ~/ai/venv/bin/activate
     python voice_assistant_ui.py &
     ```

  5. **(Opcional) Lanzar Landing UI** para gestión centralizada:
     ```bash
     python landing_manager.py
     ```

  ### Verificar que todo funciona

  ```bash
  # Comprobar todos los puertos
  ss -tulpn | grep -E ":8188|:8080|:7862|:5000|:11434"
  
  # O acceder directamente
  # Ollama API: curl http://127.0.0.1:11434/api/tags
  # Open WebUI: http://localhost:8080
  # ComfyUI: http://localhost:8188
  # Voice UI: http://localhost:7862
  # Landing Manager: http://localhost:5000
  ```

  ## 9) Git — flujo de trabajo

  El repositorio ya existe en GitHub (`jonisf87/ai-local-suite`, rama `main`).
  Comandos habituales:

  ```bash
  cd ~/ai/ai-local-suite

  # Ver estado
  git status

  # Stagear y commitear
  git add -p                          # interactivo, recomendado
  git commit -m "descripción del cambio"

  # Subir
  git push
  ```

  > **Importante**: no subas modelos pesados (.safetensors, .ckpt, .onnx) ni el `venv/`.
  > El `.gitignore` ya los excluye. Revísalo si añades rutas nuevas.

  ## 10) Comandos útiles de diagnóstico

  **Ollama**:
  - Estado: `systemctl --user status ollama`
  - Logs: `journalctl --user -u ollama -n 100 --no-pager`
  - API: `curl http://127.0.0.1:11434/api/tags`
  - Listar modelos: `ollama list`
  - Descargar modelo: `ollama pull llama3.1`

  **Open WebUI (Docker)**:
  - Estado: `docker ps | grep open-webui`
  - Logs: `docker logs -f open-webui`
  - Reiniciar: `docker restart open-webui`
  - Verificar conexión a Ollama: `docker exec open-webui curl -s http://127.0.0.1:11434/api/tags`
  - Recrear (si actualizaste): `docker stop open-webui && docker rm open-webui` (luego usa landing manager o comando manual)

  **ComfyUI**:
  - Verificar puerto: `ss -tulpn | grep :8188`
  - Probar UI: `curl -I http://127.0.0.1:8188`
  - Matar proceso: `pkill -f "python main.py"`

  **Voice UI**:
  - Verificar puerto: `ss -tulpn | grep :7862`
  - Probar UI: `curl -I http://127.0.0.1:7862`
  - Matar proceso: `pkill -f voice_assistant`

  **Landing Manager**:
  - Verificar puerto: `ss -tulpn | grep :5000`
  - Probar UI: `curl -I http://127.0.0.1:5000`
  - Matar proceso: `pkill -f landing_manager`

  **General**:
  - GPU: `nvidia-smi`
  - FFmpeg: `ffmpeg -version`
  - Piper: `which piper && piper --help`
  - Python: `python3 --version`
  - Docker: `docker --version && docker ps`
  - Puertos en uso: `ss -tulpn | grep LISTEN`

  ## 11) Buenas prácticas

  - **Gestión**: Usa el Landing Manager (`landing_manager.py`) para controlar todos los servicios desde una interfaz única
  - **Puertos**: Fija puertos en variables al inicio de cada script para mantener coherencia
  - **Docker en WSL2**: Usa siempre `--network host` para Open WebUI para garantizar conexión con Ollama
  - **CUDA**: Evita dependencias CUDA si no son necesarias; `device="cpu"` en Whisper funciona bien para audios cortos
  - **ComfyUI**: Usa flujos mínimos (KSampler "normal") antes de complicar con Advanced
  - **Rutas**: Mantén modelos y pesos en rutas claras y consistentes (`~/ai/...`)
  - **Git**: Versiona solo scripts y docs; no subas modelos pesados al repo (usa `.gitignore`)
  - **Modelos**: Descarga solo los modelos que realmente uses para ahorrar espacio:
    - LLM pequeño: `llama3.1` (8B, ~5GB)
    - LLM mediano: `mistral-nemo` (12B, ~7GB)
    - Especializado: `codellama` para programación
  - **Backups**: Respalda los volúmenes de Docker periódicamente:
    ```bash
    docker run --rm -v openwebui-data:/data -v $(pwd):/backup ubuntu tar czf /backup/openwebui-backup.tar.gz /data
    ```
  - **Actualizaciones**: Cuando actualices Open WebUI, recrea el contenedor:
    ```bash
    docker stop open-webui && docker rm open-webui
    # Luego usa landing_manager o el comando manual para crearlo nuevamente
    ```

  ## 12) Prompt para transformar esta doc en “presentación de producto”

  Usa este prompt en tu LLM favorito (por ejemplo via Open WebUI):

  > "Convierte el siguiente manual técnico en una presentación de producto clara y persuasiva para un público no técnico. Enfatiza beneficios, casos de uso, mensajes clave y diferenciadores. Resalta que funciona 100% local (privacidad, coste), que incluye generación de imágenes (ComfyUI), chat con LLM (Ollama + Open WebUI) y asistente de voz (Whisper + Piper). Estructura en secciones: Resumen ejecutivo, Funcionalidades, Beneficios, Casos de uso, Requisitos, Guía rápida, Mantenimiento. Usa un tono conciso, visual y orientado a valor. Mantén la precisión técnica mínima necesaria. Aquí está el texto técnico completo: <<PEGA AQUÍ TODO EL MANUAL>>"

  ---

  FIN
