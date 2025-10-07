#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Landing que:
- Verifica y arranca servicios locales: ComfyUI, Open WebUI (Docker + Ollama) y Asistente de Voz.
- Expone panel con botones para abrir UIs y acciones start/stop/restart por servicio.
- Muestra estado en tiempo real por puerto.
Entorno: WSL2 Ubuntu. Requiere: python3, Flask, (docker para Open WebUI).

Puertos por defecto:
- ComfyUI:      8188
- Open WebUI:   8080  (habla con Ollama en 11434)
- Ollama API:   11434 (systemd --user)
- Voice UI:     7862  (tu script voice_assistant_ui.py)
"""

import os
import socket
import subprocess
import time
import threading
from pathlib import Path
from flask import Flask, render_template_string, redirect

# --- RUTAS Y PUERTOS ----------------------------------------------------------
HOME = Path.home()
AI_DIR = HOME / "ai"

# ComfyUI
COMFY_DIR = AI_DIR / "ComfyUI"
COMFY_CMD = f"cd {COMFY_DIR} && {AI_DIR}/venv/bin/python main.py"
COMFY_PORT = 8188

# Open WebUI (Docker)
OW_CONTAINER = "open-webui"
OW_IMAGE = "ghcr.io/open-webui/open-webui:latest"
OW_PORT = 8080
OLLAMA_PORT = 11434

# Asistente de voz (tu UI en Gradio)
VOICE_SCRIPT = AI_DIR / "voice_assistant_ui.py"      # ajusta si usas el live3/live5
VOICE_CMD = f"{AI_DIR}/venv/bin/python {VOICE_SCRIPT}"
VOICE_PORT = 7862

# --- HTML ---------------------------------------------------------------------
HTML = """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Centro de IA Local — Gestor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial; background:#0f1115; color:#e5ecf5; margin:0; }
  .wrap { max-width: 1060px; margin: 48px auto; padding: 0 20px; }
  h1 { font-size: 28px; margin: 0 0 10px; }
  .sub { opacity:.82; margin-bottom: 28px; }
  .grid { display:grid; gap:16px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
  .card { background:#131826; border:1px solid #222a3c; border-radius:14px; padding:16px; }
  .head { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
  .name { font-weight:600; }
  .url  { font-size:13px; opacity:.8 }
  .status { font-size:12px; padding:4px 8px; border-radius:999px; }
  .up { background:#13341f; color:#8ae6a2; border:1px solid #1f5e33; }
  .down { background:#3a1e1e; color:#f2a6a6; border:1px solid #6b3030; }
  .btns { display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }
  a.btn { text-decoration:none; padding:10px 12px; border-radius:10px; background:#1a2132; border:1px solid #2a3144; color:#e5ecf5; font-size:14px; }
  a.btn:hover { background:#202944; }
  .help { margin-top: 28px; font-size: 14px; opacity:.9 }
  code { background:#1a2132; padding:2px 6px; border-radius:6px; border:1px solid #2a3144 }
  pre { background:#0b0f18; border:1px solid #222a3c; border-radius:10px; padding:14px; overflow:auto; }
</style>
<script>
async function doAction(svc, action) {
  try { await fetch(`/svc/${svc}/${action}`, { method: "POST" }); location.reload(); }
  catch(e){ alert("Error: " + e); }
}
</script>
</head>
<body>
<div class="wrap">
  <h1>🤖 Centro de IA Local — Gestor</h1>
  <div class="sub">Arranca/parar servicios y abre las UIs. Si algo marca <b>DOWN</b>, pulsa START para levantarlo.</div>

  <div class="grid">

    <div class="card">
      <div class="head">
        <div>
          <div class="name">🎨 ComfyUI (SDXL)</div>
          <div class="url">http://localhost:{{comfy_port}}</div>
        </div>
        <span class="status {{ 'up' if comfy_up else 'down' }}">{{ 'UP' if comfy_up else 'DOWN' }}</span>
      </div>
      <div class="btns">
        <a class="btn" href="http://localhost:{{comfy_port}}" target="_blank">Abrir UI</a>
        <a class="btn" href="javascript:doAction('comfy','start')">Start</a>
        <a class="btn" href="javascript:doAction('comfy','stop')">Stop</a>
        <a class="btn" href="javascript:doAction('comfy','restart')">Restart</a>
      </div>
    </div>

    <div class="card">
      <div class="head">
        <div>
          <div class="name">💬 Open WebUI (Ollama)</div>
          <div class="url">http://localhost:{{ow_port}}  &middot; Ollama: {{ 'UP' if ollama_up else 'DOWN' }}</div>
        </div>
        <span class="status {{ 'up' if ow_up else 'down' }}">{{ 'UP' if ow_up else 'DOWN' }}</span>
      </div>
      <div class="btns">
        <a class="btn" href="http://localhost:{{ow_port}}" target="_blank">Abrir UI</a>
        <a class="btn" href="javascript:doAction('ollama','start')">Start Ollama</a>
        <a class="btn" href="javascript:doAction('openwebui','start')">Start Open WebUI</a>
        <a class="btn" href="javascript:doAction('openwebui','stop')">Stop Open WebUI</a>
      </div>
    </div>

    <div class="card">
      <div class="head">
        <div>
          <div class="name">🗣️ Asistente de Voz (Whisper + Piper)</div>
          <div class="url">http://localhost:{{voice_port}}</div>
        </div>
        <span class="status {{ 'up' if voice_up else 'down' }}">{{ 'UP' if voice_up else 'DOWN' }}</span>
      </div>
      <div class="btns">
        <a class="btn" href="http://localhost:{{voice_port}}" target="_blank">Abrir UI</a>
        <a class="btn" href="javascript:doAction('voice','start')">Start</a>
        <a class="btn" href="javascript:doAction('voice','stop')">Stop</a>
        <a class="btn" href="javascript:doAction('voice','restart')">Restart</a>
      </div>
    </div>

  </div>

  <div class="help">
    <h3>Guía (manual) rápida</h3>
    <pre><code># ComfyUI
cd ~/ai/ComfyUI
source ~/ai/venv/bin/activate
python main.py

# Ollama (servicio de usuario)
systemctl --user start ollama
systemctl --user status ollama

# Open WebUI (Docker)
docker start {{ow_container}} || docker run -d --name {{ow_container}} \\
  -p {{ow_port}}:8080 \\
  -e OLLAMA_BASE_URL=http://127.0.0.1:{{ollama_port}} \\
  -v openwebui-data:/app/backend/data \\
  --restart unless-stopped {{ow_image}}

# Asistente de voz
cd ~/ai
source ~/ai/venv/bin/activate
python {{voice_script}}</code></pre>
  </div>
</div>
</body>
</html>
"""

# --- UTILIDAD ----------------------------------------------------------------
def port_open(port: int, host="127.0.0.1", timeout=0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False

def run_bg(cmd: str, pidfile: Path):
    """Lanza cmd en background, registra PID en pidfile."""
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    pidfile.write_text(str(proc.pid))
    return proc.pid

def kill_from_pidfile(pidfile: Path):
    if not pidfile.exists():
        return
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 15)  # SIGTERM
        time.sleep(0.3)
    except Exception:
        pass
    try:
        pidfile.unlink(missing_ok=True)
    except Exception:
        pass

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def have_docker() -> bool:
    try:
        subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except Exception:
        return False

# --- MANEJO SERVICIOS --------------------------------------------------------
RUN_DIR = AI_DIR / "run"
ensure_dir(RUN_DIR)

COMFY_PID = RUN_DIR / "comfyui.pid"
VOICE_PID = RUN_DIR / "voice.pid"

def comfy_start():
    if port_open(COMFY_PORT):
        return "already"
    # Arranca en bg
    return run_bg(COMFY_CMD, COMFY_PID)

def comfy_stop():
    kill_from_pidfile(COMFY_PID)

def voice_start():
    if port_open(VOICE_PORT):
        return "already"
    if not VOICE_SCRIPT.exists():
        return f"script_not_found:{VOICE_SCRIPT}"
    return run_bg(VOICE_CMD, VOICE_PID)

def voice_stop():
    kill_from_pidfile(VOICE_PID)

def ollama_start():
    # servicio de usuario
    try:
        subprocess.run(["systemctl", "--user", "start", "ollama"], check=False)
        return True
    except Exception:
        return False

def openwebui_start():
    if not have_docker():
        return "nodocker"
    if port_open(OW_PORT):
        return "already"
    # intenta start si ya existe
    r = subprocess.run(["docker", "start", OW_CONTAINER], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode == 0:
        return "started"
    # si no existe, run
    cmd = [
        "docker","run","-d","--name",OW_CONTAINER,
        "-p", f"{OW_PORT}:8080",
        "-e", f"OLLAMA_BASE_URL=http://127.0.0.1:{OLLAMA_PORT}",
        "-v","openwebui-data:/app/backend/data",
        "--restart","unless-stopped",
        OW_IMAGE
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return "run_ok" if r.returncode == 0 else f"run_fail:{r.stderr.decode(errors='ignore')}"

def openwebui_stop():
    if not have_docker():
        return "nodocker"
    subprocess.run(["docker","stop",OW_CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- AUTOINICIO EN SEGUNDO PLANO ---------------------------------------------
def autostart():
    # 1) Ollama (para Open WebUI)
    if not port_open(OLLAMA_PORT):
        ollama_start()
        # pequeño margen
        time.sleep(1.5)

    # 2) Open WebUI (Docker)
    if not port_open(OW_PORT):
        openwebui_start()

    # 3) ComfyUI
    if not port_open(COMFY_PORT):
        comfy_start()

    # 4) Voice UI
    if not port_open(VOICE_PORT):
        voice_start()

# --- FLASK APP ---------------------------------------------------------------
app = Flask(__name__)

@app.route("/")
def index():
    ctx = dict(
        comfy_port=COMFY_PORT,
        ow_port=OW_PORT,
        ollama_port=OLLAMA_PORT,
        voice_port=VOICE_PORT,
        comfy_up=port_open(COMFY_PORT),
        ow_up=port_open(OW_PORT),
        ollama_up=port_open(OLLAMA_PORT),
        voice_up=port_open(VOICE_PORT),
        ow_container=OW_CONTAINER,
        ow_image=OW_IMAGE,
        voice_script=VOICE_SCRIPT.name
    )
    return render_template_string(HTML, **ctx)

@app.post("/svc/comfy/<action>")
def svc_comfy(action):
    if action == "start": comfy_start()
    elif action == "stop": comfy_stop()
    elif action == "restart":
        comfy_stop(); time.sleep(0.3); comfy_start()
    return ("", 204)

@app.post("/svc/voice/<action>")
def svc_voice(action):
    if action == "start": voice_start()
    elif action == "stop": voice_stop()
    elif action == "restart":
        voice_stop(); time.sleep(0.3); voice_start()
    return ("", 204)

@app.post("/svc/openwebui/<action>")
def svc_ow(action):
    if action == "start": openwebui_start()
    elif action == "stop": openwebui_stop()
    return ("", 204)

@app.post("/svc/ollama/<action>")
def svc_ollama(action):
    if action == "start": ollama_start()
    return ("", 204)

def _open_browser():
    try:
        import webbrowser
        webbrowser.open("http://localhost:5000")
    except Exception:
        pass

if __name__ == "__main__":
    # Autoarranque en un hilo para no bloquear Flask
    threading.Thread(target=autostart, daemon=True).start()
    threading.Timer(1.0, _open_browser).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
