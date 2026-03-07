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
  - Django Chatbot: 8000 (script `manage.py runserver`)
  - Landing Manager UI: 5000 (script `landing_manager.py`)

  ## Estructura recomendada de carpetas

  ```
  /home/jonathan/ai
  ├── ComfyUI/                 (generación de imágenes)
  ├── adult_chatbot_manga/     (Django chatbot con personajes)
  ├── audio/                   (audios de prueba)
  ├── models/                  (modelos propios opcionales)
  ├── piper/                   (modelos TTS Piper *.onnx y *.json)
  ├── voice_out/               (salida de audio del TTS)  ├── modelfiles/              (Modelfiles personalizados de Ollama)
  │   ├── security-auditor     (auditor de seguridad)
  │   ├── python-expert        (experto Python)
  │   ├── devops-expert        (experto DevOps)
  │   ├── voice-assistant      (asistente de voz optimizado)
  │   ├── custom               (asistente general sin censura)
│   ├── create-all-models.sh (script para crear todos)
  │   └── README.md            (documentación de modelos)  ├── ai-local-suite/          (repositorio “suite” con scripts y docs)
  ├── transcribe_ui.py         (UI de transcripción Whisper)
  ├── voice_assistant_ui.py    (UI de asistente de voz)
  ├── voice_assistant_live*.py (variantes live del asistente de voz)
  ├── landing_manager.py       (gestor/landing para lanzar y controlar UIs)
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
    -e WEBUI_NAME="Local WebUI" \
    -v openwebui-data:/app/backend/data \
    --restart unless-stopped \
    ghcr.io/open-webui/open-webui:main
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

  ```
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
       ```
       Eres un experto en Linux, Docker, Python y AI local.
       Trabajas principalmente con WSL2 Ubuntu.
       Das respuestas técnicas precisas con comandos listos para ejecutar.
       Prefieres soluciones simples y eficientes.
       ```

  2. **Prompt por Conversación**: En cada chat individual, haz clic en configuración del chat para personalizar solo esa conversación

  3. **Crear Personajes/Personas**: Ve a **Workspace** → **Personalization** para crear perfiles con prompts específicos

  **Ejemplos de prompts útiles**:

  - **Para asistente de voz** (respuestas cortas):
    ```
    Eres un asistente de voz breve y directo.
    Respondes en máximo 2-3 oraciones cortas.
    Evitas listas largas y explicaciones extensas.
    Usas un lenguaje natural y conversacional.
    ```

  - **Para programación**:
    ```
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
    -e WEBUI_NAME="Local WebUI" \
    -v openwebui-data:/app/backend/data \
    --restart unless-stopped \
    ghcr.io/open-webui/open-webui:main
  
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

  ## 7) Landing Manager UI (puerto 5000) — gestor y lanzador

  `landing_manager.py` ofrece:

  - Auto‑arranque (autostart) de servicios si están caídos: Ollama (servicio), Open WebUI (Docker), ComfyUI y Voice UI.
  - Panel con estado (UP/DOWN) por puerto y botones Start / Stop / Restart (cuando aplica).
  - Apertura directa de cada interfaz en nuevas pestañas.
  - Comandos de referencia incrustados con la configuración correcta (`--network host` para Open WebUI).

  Objetivo: centralizar en una sola página la gestión local de la suite sin recordar cada comando.

  Ejecutar:

  ```bash
  source ~/ai/venv/bin/activate
  python /home/jonathan/ai/landing_manager.py
  # Abrir: http://localhost:5000
  ```

  > **Nota**: El landing manager está configurado para arrancar Open WebUI con `--network host` automáticamente. Si tienes un contenedor antiguo, detén y elimínalo antes: `docker stop open-webui && docker rm open-webui`

  Comprobar puertos en caso de conflicto:

  ```bash
  ss -tulpn | grep -E ":8188|:8080|:7862|:5000|:11434"
  ```

  **Funciones del Landing Manager**:

  - ✅ Detección automática de servicios caídos
  - ✅ Arranque automático al iniciar (autostart)
  - ✅ Panel visual con estado en tiempo real
  - ✅ Botones para controlar cada servicio
  - ✅ Enlaces directos a cada UI
  - ✅ Comandos de referencia actualizados

  ## 8) Puesta en marcha — orden recomendado

  ### Opción A: Usando Landing Manager (Recomendado)

  ```bash
  cd ~/ai
  source venv/bin/activate
  python landing_manager.py
  # Abre http://localhost:5000 y todos los servicios arrancarán automáticamente
  ```

  El Landing Manager detectará servicios caídos y los iniciará automáticamente en este orden:
  1. Ollama (si no está activo)
  2. Open WebUI (Docker)
  3. ComfyUI
  4. Voice Assistant UI

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
       -e WEBUI_NAME="Local WebUI" \
       -v openwebui-data:/app/backend/data \
       --restart unless-stopped \
       ghcr.io/open-webui/open-webui:main
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
