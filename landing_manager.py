#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Landing que:
- Verifica y arranca servicios locales: ComfyUI, Open WebUI (Docker + Ollama) y Asistente de Voz.
- Expone panel con botones para abrir UIs y acciones start/stop/restart por servicio.
- Muestra estado en tiempo real por puerto (polling JS cada 5s).
- Herramienta de generación de vídeo con AnimateDiff SDXL.
- Herramienta de generación de vídeo con Wan2.1 T2V.

Entorno: WSL2 Ubuntu. Requiere: python3, Flask, (docker para Open WebUI).

Puertos por defecto:
- ComfyUI:      8188
- Open WebUI:   8080  (habla con Ollama en 11434)
- Ollama API:   11434 (systemd --user)
- Voice UI:     7862  (tu script voice_assistant_ui.py)
"""

import json
import inspect
import importlib
import logging
import os
import sys
import random
import re
import socket
import subprocess
import time
import threading
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import request as urlrequest, error as urlerror
from flask import Flask, render_template_string, request, jsonify, send_from_directory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- RUTAS Y PUERTOS ----------------------------------------------------------
HOME = Path.home()
REPO_DIR = Path(__file__).resolve().parent
AI_DIR = Path(os.environ.get("AI_SUITE_HOME", str(HOME / "ai"))).expanduser().resolve()


def _first_existing_path(paths: list[Path | None]) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None


_env_python = os.environ.get("AI_SUITE_PYTHON", "").strip()
if _env_python:
    _env_python_path = Path(_env_python).expanduser()
else:
    _env_python_path = Path()
VENV_PYTHON = _first_existing_path(
    [
        _env_python_path if _env_python else None,
        AI_DIR / "venv" / "bin" / "python",
        REPO_DIR / ".venv" / "bin" / "python",
    ]
)
if VENV_PYTHON is None:
    VENV_PYTHON = Path(sys.executable)

COMFY_DIR = AI_DIR / "ComfyUI"
COMFY_CMD = [str(VENV_PYTHON), "main.py"]
COMFY_PORT = 8188
WORKFLOWS_DIR = COMFY_DIR / "workflows"
USE_EXTERNAL_WORKFLOW_FILES = (
    os.environ.get("LANDING_USE_EXTERNAL_WORKFLOWS", "0") == "1"
)

OW_CONTAINER = "open-webui"
OW_IMAGE = "ghcr.io/open-webui/open-webui:latest"
OW_PORT = 8080
OLLAMA_PORT = 11434

_voice_script_candidate = _first_existing_path(
    [AI_DIR / "voice_assistant_ui.py", REPO_DIR / "voice_assistant_ui.py"]
)
if _voice_script_candidate is None:
    VOICE_SCRIPT: Path = AI_DIR / "voice_assistant_ui.py"
else:
    VOICE_SCRIPT: Path = _voice_script_candidate
VOICE_CMD = [str(VENV_PYTHON), str(VOICE_SCRIPT)]
VOICE_PORT = 7862

ADULT_CHATBOT_DIR = AI_DIR / "adult_chatbot_manga"
ADULT_CHATBOT_PORT = 8000
ADULT_CHATBOT_CMD = (
    [
        str(VENV_PYTHON),
        "manage.py",
        "runserver",
        f"0.0.0.0:{ADULT_CHATBOT_PORT}",
    ]
)

LANDING_HOST = os.environ.get("LANDING_HOST", "127.0.0.1")
LANDING_DEBUG = os.environ.get("LANDING_DEBUG", "0") == "1"

WAN_WRAPPER_DIR = COMFY_DIR / "custom_nodes" / "ComfyUI-WanVideoWrapper"
OLLAMA_MODELFILES_DIR = AI_DIR / "modelfiles"
CHARACTER_PROFILES_DIR = AI_DIR / "adult_chatbot_manga" / "characters"
VOICE_OUT_DIR = AI_DIR / "voice_out"
PIPER_MODEL_PATH = os.environ.get("PIPER_MODEL", str(AI_DIR / "piper" / "es_ES-mls_9972-low.onnx"))
PIPER_CONFIG_PATH = os.environ.get("PIPER_CONFIG", f"{PIPER_MODEL_PATH}.json")
PIPER_BIN = os.environ.get("PIPER_BIN", str(AI_DIR / "venv" / "bin" / "piper"))
XTTS_MODEL_NAME = os.environ.get("XTTS_MODEL", "tts_models/multilingual/multi-dataset/xtts_v2")
XTTS_PYTHON = os.environ.get("XTTS_PYTHON", str(AI_DIR / "venv_xtts311" / "bin" / "python"))

GAME_TTS_PERSONALITY_PRESETS = [
    {
        "id": "neutral_narrator",
        "name": "Neutral Narrator",
        "voice_id": "narrator",
        "speed": 1.0,
        "pitch": 1.0,
        "energy": 1.0,
        "emotion_tags": "neutral, clear",
        "pauses": "medium",
    },
    {
        "id": "hero_confident",
        "name": "Hero Confident",
        "voice_id": "hero",
        "speed": 1.08,
        "pitch": 1.03,
        "energy": 1.15,
        "emotion_tags": "confident, determined",
        "pauses": "short",
    },
    {
        "id": "villain_cold",
        "name": "Villain Cold",
        "voice_id": "villain",
        "speed": 0.92,
        "pitch": 0.95,
        "energy": 0.95,
        "emotion_tags": "cold, threatening",
        "pauses": "long",
    },
    {
        "id": "npc_friendly",
        "name": "NPC Friendly",
        "voice_id": "npc",
        "speed": 1.04,
        "pitch": 1.06,
        "energy": 1.08,
        "emotion_tags": "friendly, warm",
        "pauses": "medium",
    },
]

_xtts_model_cache = None

WAN_REQUIRED_NODES = [
    "WanVideoModelLoader",
    "LoadWanVideoT5TextEncoder",
    "WanVideoVAELoader",
    "WanVideoTextEncode",
    "WanVideoEmptyEmbeds",
    "WanVideoSampler",
    "WanVideoDecode",
    "VHS_VideoCombine",
]

SERVICES = [
    {"key": "comfy", "label": "ComfyUI", "port": COMFY_PORT},
    {"key": "openwebui", "label": "Open WebUI", "port": OW_PORT},
    {"key": "ollama", "label": "Ollama", "port": OLLAMA_PORT},
    {"key": "voice", "label": "Voice UI", "port": VOICE_PORT},
    {"key": "adultchatbot", "label": "adult_chatbot_manga", "port": ADULT_CHATBOT_PORT},
]

# --- PRESETS AnimateDiff SDXL -------------------------------------------------
VIDEO_MODEL_PRESETS = [
    {
        "id": "wai_nsfw",
        "name": "WAI NSFW SDXL",
        "checkpoint": "wai-nsfw-illustrious-sdxl.safetensors",
        "include_token": "wai_nsfw",
    },
    {
        "id": "realvis",
        "name": "RealVisXL",
        "checkpoint": "RealVisXL_V5.0.safetensors",
        "include_token": "realvis",
    },
    {
        "id": "cyberrealistic",
        "name": "CyberRealistic SDXL",
        "checkpoint": "cyberrealisticXL.safetensors",
        "include_token": "cyberrealistic",
    },
    {
        "id": "juggernaut",
        "name": "Juggernaut XL",
        "checkpoint": "juggernautXL.safetensors",
        "include_token": "juggernaut",
    },
    {
        "id": "dreamshaper_xl",
        "name": "DreamShaper XL",
        "checkpoint": "dreamshaperXL.safetensors",
        "include_token": "dreamshaper",
    },
]

VIDEO_SMOOTH_PROFILES = [
    {
        "id": "cinematic_stable",
        "name": "Cinemático Estable",
        "desc": "640x960, 24 frames, 8 fps",
        "width": 640,
        "height": 960,
        "frames": 24,
        "fps": 8,
        "steps": 20,
        "cfg": 7.0,
        "denoise": 0.7,
        "crf": 18,
        "pix_fmt": "yuv420p",
    },
    {
        "id": "fluid_dynamic",
        "name": "Fluido Dinámico",
        "desc": "640x960, 20 frames, 10 fps",
        "width": 640,
        "height": 960,
        "frames": 20,
        "fps": 10,
        "steps": 20,
        "cfg": 7.0,
        "denoise": 0.7,
        "crf": 18,
        "pix_fmt": "yuv420p",
    },
]

# --- PRESETS WAN2.1 -----------------------------------------------------------
WAN_MODEL_PRESETS = [
    {
        "id": "wan_1b",
        "name": "Wan2.1 T2V 1.3B (rápido)",
        "model": "Wan2_1-T2V-1_3B_bf16.safetensors",
        "text_encoder": "umt5-xxl-enc-bf16.safetensors",
        "vae": "Wan2_1_VAE_bf16.safetensors",
    },
    {
        "id": "wan_14b",
        "name": "Wan2.1 T2V 14B (calidad)",
        "model": "Wan2_1-T2V-14B_fp8_e4m3fn.safetensors",
        "text_encoder": "umt5-xxl-enc-bf16.safetensors",
        "vae": "Wan2_1_VAE_bf16.safetensors",
    },
]

WAN_VIDEO_PROFILES = [
    {
        "id": "portrait_fast",
        "name": "Portrait Fast (480x832)",
        "desc": "Formato vertical, rápido",
        "width": 480,
        "height": 832,
        "frames": 20,
        "fps": 8,
        "steps": 20,
        "cfg": 6.0,
        "shift": 5.0,
        "crf": 18,
        "pix_fmt": "yuv420p",
    },
    {
        "id": "portrait_quality",
        "name": "Portrait Quality (480x832)",
        "desc": "Formato vertical, más steps",
        "width": 480,
        "height": 832,
        "frames": 24,
        "fps": 8,
        "steps": 30,
        "cfg": 6.0,
        "shift": 5.0,
        "crf": 18,
        "pix_fmt": "yuv420p",
    },
    {
        "id": "landscape_quality",
        "name": "Landscape Quality (832x480)",
        "desc": "Formato apaisado, calidad alta",
        "width": 832,
        "height": 480,
        "frames": 24,
        "fps": 8,
        "steps": 30,
        "cfg": 6.0,
        "shift": 5.0,
        "crf": 18,
        "pix_fmt": "yuv420p",
    },
]

# --- HTML PRINCIPAL -----------------------------------------------------------
HTML = """
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><title>Centro de IA Local — Gestor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark;--bg:#06070d;--panel:#0d1220;--panel2:#090d18;--line:#3efc9a;--line2:#38a8ff;--text:#d5ffe6;--warn:#ff4f81}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(1200px 700px at 20% -10%,#152241 0%,#06070d 55%),radial-gradient(1000px 600px at 120% 120%,#101b32 0%,#06070d 60%);color:var(--text);margin:0;letter-spacing:.02em;position:relative}
body:before{content:"";position:fixed;inset:0;background:repeating-linear-gradient(to bottom,rgba(255,255,255,.03) 0 1px,transparent 1px 4px);pointer-events:none;mix-blend-mode:soft-light}
.wrap{max-width:1100px;margin:44px auto;padding:0 18px}
h1{font-size:30px;margin:0 0 12px;text-shadow:0 0 8px rgba(62,252,154,.45)}
.sub{opacity:.9;margin-bottom:26px;color:#b5d8ff}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.card,.tool-card{background:linear-gradient(160deg,var(--panel) 0%,var(--panel2) 100%);border:2px solid #1f7eaf;border-radius:6px;padding:14px;box-shadow:0 0 0 1px rgba(62,252,154,.18) inset,0 0 18px rgba(56,168,255,.12)}
.head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.name{font-weight:700;color:#bfffe0;text-transform:uppercase}
.url{font-size:13px;opacity:.92;color:#8bc7ff}
.status{font-size:12px;padding:4px 8px;border-radius:4px;border:1px solid}
.up{background:rgba(62,252,154,.14);color:#96ffcb;border-color:#3efc9a}
.down{background:rgba(255,79,129,.14);color:#ff9fbe;border-color:#ff4f81}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
a.btn{text-decoration:none;padding:10px 12px;border-radius:4px;background:linear-gradient(180deg,#10233d 0%,#0d1a2d 100%);border:1px solid #2b9cff;color:#d8eeff;font-size:14px;cursor:pointer;box-shadow:0 0 0 1px rgba(62,252,154,.14) inset}
a.btn:hover{background:linear-gradient(180deg,#15345f 0%,#10233d 100%);transform:translateY(-1px)}
.help{margin-top:24px;font-size:14px;opacity:.95}
code{background:#0f1c2f;padding:2px 6px;border-radius:4px;border:1px solid #2d7bc2;color:#b8f6d9}
pre{background:#050a14;border:1px solid #246eab;border-radius:6px;padding:14px;overflow:auto;color:#bdf2ff}
</style>
<script>
async function doAction(svc,action){
  try{await fetch(`/svc/${svc}/${action}`,{method:"POST"})}catch(e){alert("Error: "+e)}
}
async function pollStatus(){
  try{
    const r=await fetch("/api/status");if(!r.ok)return;
    const data=await r.json();
    for(const[key,up]of Object.entries(data)){
      document.querySelectorAll(`[data-svc="${key}"]`).forEach(el=>{
        el.textContent=up?"UP":"DOWN";el.className="status "+(up?"up":"down");
      });
    }
  }catch(e){}
}
setInterval(pollStatus,5000);
</script>
</head><body>
<div class="wrap">
<h1>🤖 Centro de IA Local — Gestor</h1>
<div class="sub">Arranca/para servicios y abre las UIs. Los badges se actualizan cada 5s.</div>
<div class="grid">
  <div class="card">
    <div class="head">
      <div><div class="name">🎨 ComfyUI (SDXL)</div><div class="url">http://localhost:{{comfy_port}}</div></div>
      <span class="status {{'up' if comfy_up else 'down'}}" data-svc="comfy">{{'UP' if comfy_up else 'DOWN'}}</span>
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
        <div class="url">http://localhost:{{ow_port}} &middot; Ollama: <span class="status {{'up' if ollama_up else 'down'}}" data-svc="ollama">{{'UP' if ollama_up else 'DOWN'}}</span></div>
      </div>
      <span class="status {{'up' if ow_up else 'down'}}" data-svc="openwebui">{{'UP' if ow_up else 'DOWN'}}</span>
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
      <div><div class="name">🗣️ Asistente de Voz</div><div class="url">http://localhost:{{voice_port}}</div></div>
      <span class="status {{'up' if voice_up else 'down'}}" data-svc="voice">{{'UP' if voice_up else 'DOWN'}}</span>
    </div>
    <div class="btns">
      <a class="btn" href="http://localhost:{{voice_port}}" target="_blank">Abrir UI</a>
      <a class="btn" href="javascript:doAction('voice','start')">Start</a>
      <a class="btn" href="javascript:doAction('voice','stop')">Stop</a>
      <a class="btn" href="javascript:doAction('voice','restart')">Restart</a>
    </div>
  </div>
    <div class="card">
        <div class="head">
            <div><div class="name">📚 adult_chatbot_manga</div><div class="url">http://localhost:{{adult_chatbot_port}}</div></div>
            <span class="status {{'up' if adultchatbot_up else 'down'}}" data-svc="adultchatbot">{{'UP' if adultchatbot_up else 'DOWN'}}</span>
        </div>
        <div class="btns">
            <a class="btn" href="http://localhost:{{adult_chatbot_port}}" target="_blank">Abrir App</a>
            <a class="btn" href="javascript:doAction('adultchatbot','start')">Start</a>
            <a class="btn" href="javascript:doAction('adultchatbot','stop')">Stop</a>
            <a class="btn" href="javascript:doAction('adultchatbot','restart')">Restart</a>
        </div>
    </div>
</div>
<div class="grid" style="margin-top:24px;">
  <div class="tool-card">
    <div class="name">🎬 Tool: AnimateDiff SDXL Vídeo</div>
    <div class="url" style="margin:4px 0 10px;opacity:.8">Genera vídeos cortos con AnimateDiff SDXL</div>
    <div class="btns"><a class="btn" href="/tools/video-scene">Abrir herramienta</a></div>
  </div>
  <div class="tool-card">
    <div class="name">🎞️ Tool: Wan2.1 Vídeo</div>
    <div class="url" style="margin:4px 0 10px;opacity:.8">Text-to-video con Wan2.1 (ComfyUI-WanVideoWrapper)</div>
    <div class="btns"><a class="btn" href="/tools/wan-video">Abrir herramienta</a></div>
  </div>
    <div class="tool-card">
        <div class="name">🖼️ Tool: Wan2.1 I2V Scene</div>
        <div class="url" style="margin:4px 0 10px;opacity:.8">Image-to-video para escenas estables (menos efecto carrusel)</div>
        <div class="btns"><a class="btn" href="/tools/wan-i2v">Abrir herramienta</a></div>
    </div>
    <div class="tool-card">
        <div class="name">🎮 Tool: Game TTS Personality</div>
        <div class="url" style="margin:4px 0 10px;opacity:.8">Piper (rápido) + XTTS v2 (personajes expresivos)</div>
        <div class="btns"><a class="btn" href="/tools/game-tts">Abrir herramienta</a></div>
    </div>
    <div class="tool-card">
        <div class="name">🧠 Tool: Ollama Custom Models</div>
        <div class="url" style="margin:4px 0 10px;opacity:.8">Lista, descarga y crea modelos custom con Modelfile</div>
        <div class="btns"><a class="btn" href="/tools/ollama-models">Abrir herramienta</a></div>
    </div>
</div>
<div class="help">
<h3>Guía rápida</h3>
<pre><code># ComfyUI
cd ~/ai/ComfyUI && source ~/ai/venv/bin/activate && python main.py

# Ollama
systemctl --user start ollama

# Open WebUI (Docker)
docker start {{ow_container}} || docker run -d --name {{ow_container}} \\
  -p {{ow_port}}:8080 --network host \\
  -e OLLAMA_BASE_URL=http://127.0.0.1:{{ollama_port}} \\
  -v openwebui-data:/app/backend/data \\
  --restart unless-stopped {{ow_image}}

# Voice UI
cd ~/ai && source ~/ai/venv/bin/activate && python {{voice_script}}</code></pre>
</div>
</div>
</body></html>
"""

# --- HTML ANIMATEDIFF VIDEO TOOL ----------------------------------------------
VIDEO_TOOL_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>AnimateDiff SDXL — Generar Vídeo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(900px 500px at 10% -10%,#1a2748 0%,#06070d 60%);color:#d5ffe6;margin:0}
.wrap{max-width:800px;margin:36px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px;text-shadow:0 0 8px rgba(62,252,154,.35)}
.back{font-size:14px;opacity:.9;margin-bottom:18px}.back a{color:#78c7ff;text-decoration:none}
label{display:block;font-size:13px;opacity:.95;margin:10px 0 3px;color:#9fd0ff}
input,textarea,select{width:100%;box-sizing:border-box;background:#081122;border:1px solid #2a8fd6;border-radius:4px;color:#d5ffe6;padding:9px 10px;font-size:16px;box-shadow:0 0 0 1px rgba(62,252,154,.12) inset}
input:focus,textarea:focus,select:focus{outline:none;border-color:#3efc9a;box-shadow:0 0 0 1px rgba(62,252,154,.4),0 0 12px rgba(62,252,154,.2)}
textarea{height:96px;resize:vertical}.row{display:flex;gap:10px}.row>div{flex:1}
button,a.btn{margin-top:8px;background:linear-gradient(180deg,#15345f 0%,#10233d 100%);border:1px solid #2ea8ff;color:#e5f4ff;padding:10px 18px;border-radius:4px;font-size:15px;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,a.btn:hover{background:linear-gradient(180deg,#1d4b88 0%,#15345f 100%)}
.result{margin-top:16px;background:#091227;border:1px solid #2b87cf;border-radius:4px;padding:12px;font-size:15px;white-space:pre-wrap}
.ok{color:#8effb8}.err{color:#ff9bbb}
.section{background:linear-gradient(160deg,#0b1326 0%,#09101f 100%);border:2px solid #1f79b5;border-radius:6px;padding:12px;margin-bottom:12px}
.section-title{font-size:13px;font-weight:700;opacity:.95;text-transform:uppercase;letter-spacing:.08em;color:#8ec9ff}
</style></head><body><div class="wrap">
<h1>🎬 AnimateDiff SDXL — Generar Vídeo</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>
<form id="vf" method="post" onsubmit="return handleVideoSubmit(event)">
  <div class="section"><div class="section-title">Modelo y perfil</div>
    <div class="row">
      <div><label>Modelo SDXL</label><select name="model_preset">
        {% for p in model_presets %}<option value="{{ p.id }}" {% if p.id==form.model_preset %}selected{% endif %}>{{ p.name }}</option>{% endfor %}
      </select></div>
      <div><label>Perfil de vídeo</label><select name="smooth_profile" onchange="applyProfile(this)">
        {% for p in smooth_profiles %}<option value="{{ p.id }}" {% if p.id==form.smooth_profile %}selected{% endif %}>{{ p.name }} — {{ p.desc }}</option>{% endfor %}
      </select></div>
    </div>
  </div>
  <div class="section"><div class="section-title">Prompt</div>
        <label>Perfil de personaje</label><select id="video_character_preset" name="character_preset" onchange="applyCharacterPrompt(this, 'vf')">
            <option value="">Manual (sin perfil)</option>
            {% for p in character_prompt_presets %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}
        </select>
    <label>Prompt positivo</label><textarea name="positive_prompt">{{ form.positive_prompt }}</textarea>
    <label>Prompt negativo</label><textarea name="negative_prompt" style="height:60px">{{ form.negative_prompt }}</textarea>
  </div>
  <div class="section"><div class="section-title">Parámetros</div>
    <div class="row">
      <div><label>Ancho</label><input name="width" type="number" min="256" max="1280" step="8" value="{{ form.width }}"></div>
      <div><label>Alto</label><input name="height" type="number" min="256" max="1280" step="8" value="{{ form.height }}"></div>
      <div><label>Frames</label><input name="frames" type="number" min="8" max="64" step="4" value="{{ form.frames }}"></div>
      <div><label>FPS</label><input name="fps" type="number" min="4" max="30" value="{{ form.fps }}"></div>
    </div>
    <div class="row">
      <div><label>Steps</label><input name="steps" type="number" min="10" max="50" value="{{ form.steps }}"></div>
      <div><label>CFG</label><input name="cfg" type="number" min="1" max="15" step="0.5" value="{{ form.cfg }}"></div>
      <div><label>Denoise</label><input name="denoise" type="number" min="0.1" max="1.0" step="0.01" value="{{ form.denoise }}"></div>
      <div><label>Seed (-1=random)</label><input name="seed" type="number" value="{{ form.seed }}"></div>
    </div>
    <div class="row">
      <div><label>CRF</label><input name="crf" type="number" min="14" max="28" value="{{ form.crf }}"></div>
      <div><label>Pixel format</label><select name="pix_fmt">
        <option value="yuv420p" {% if form.pix_fmt=='yuv420p' %}selected{% endif %}>yuv420p</option>
        <option value="yuv420p10le" {% if form.pix_fmt=='yuv420p10le' %}selected{% endif %}>yuv420p10le</option>
      </select></div>
    </div>
  </div>
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
        <button type="submit">🎬 Generar vídeo</button>
        <a class="btn" href="http://localhost:8188" target="_blank" rel="noopener noreferrer">📋 Abrir ComfyUI (cola)</a>
    </div>
</form>
{% if server_result %}
<div id="result" class="result {{ 'ok' if server_result_ok else 'err' }}">{{ server_result }}</div>
{% else %}
<div id="result" class="result" style="display:none"></div>
{% endif %}
</div>
<script>
const profiles={{smooth_profiles_json|safe}};
function applyProfile(sel){
  const p=profiles.find(x=>x.id===sel.value);if(!p)return;
  const f=document.getElementById('vf');
  ['width','height','frames','fps','steps','cfg','denoise','crf'].forEach(k=>{if(f[k]&&p[k]!==undefined)f[k].value=p[k];});
}
async function applyCharacterPrompt(sel, formId){
    const id=sel.value;
    const f=document.getElementById(formId);if(!f)return;
    const pos=f.querySelector('[name="positive_prompt"]');
    const neg=f.querySelector('[name="negative_prompt"]');
        const r=document.getElementById('result');
    if(!id){
        if(pos) pos.value='';
        if(neg) neg.value='';
                if(r){
                    r.style.display='block';
                    r.className='result ok';
                    r.textContent='Perfil manual: prompts limpiados.';
                }
        return;
    }
    try{
        const resp=await fetch('/tools/character-video-prompt/'+encodeURIComponent(id));
        const data=await resp.json();
        if(!data.ok)return;
        if(pos && data.positive_prompt) pos.value=data.positive_prompt;
        if(neg && data.negative_prompt) neg.value=data.negative_prompt;
                if(r){
                    r.style.display='block';
                    r.className='result ok';
                    r.textContent='Perfil cargado: '+(data.name||id)+'\\nPrompt+ y Prompt- actualizados.';
                }
    }catch(_err){
                if(r){
                    r.style.display='block';
                    r.className='result err';
                    r.textContent='Error cargando perfil '+id+'. Revisa /tmp/landing-trace.log';
                }
        // El fallback de backend al enviar mantiene funcionalidad incluso si falla la UI.
    }
}
async function handleVideoSubmit(e){
  e.preventDefault();const r=document.getElementById('result');
  r.style.display='block';r.className='result';r.textContent='Enviando a ComfyUI...';
  const fd=new FormData(e.target);
  try{
        const resp=await fetch('/tools/video-scene',{
            method:'POST',
            headers:{'X-Requested-With':'XMLHttpRequest'},
            body:new URLSearchParams(fd)
        });
    const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
        let msg=data.message||'';
    if(data.prompt_id)msg+='\\nPrompt ID: '+data.prompt_id;
    if(data.output_prefix)msg+='\\nOutput: '+data.output_prefix;
        if(data.workflow_mode)msg+='\\nWorkflow mode: '+data.workflow_mode;
        if(data.workflow_file)msg+='\\nWorkflow file: '+data.workflow_file;
        if(data.used_checkpoint)msg+='\\nCheckpoint: '+data.used_checkpoint;
        if(data.used_motion_model)msg+='\\nMotion model: '+data.used_motion_model;
        if(data.used_positive_prompt)msg+='\\nPrompt+: '+data.used_positive_prompt;
        if(data.ok && data.prompt_id)msg+='\\nComfyUI: http://localhost:8188 (abre Queue en la barra lateral)';
    r.textContent=msg;
    }catch(err){r.className='result err';r.textContent='Error: '+err;}
    return false;
}
</script></body></html>
"""

# --- HTML WAN2.1 VIDEO TOOL ---------------------------------------------------
WAN_TOOL_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Wan2.1 — Generar Vídeo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(950px 520px at 90% -20%,#1a2748 0%,#06070d 62%);color:#d5ffe6;margin:0}
.wrap{max-width:800px;margin:36px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px;text-shadow:0 0 8px rgba(62,252,154,.35)}
.back{font-size:14px;opacity:.9;margin-bottom:18px}.back a{color:#78c7ff;text-decoration:none}
label{display:block;font-size:13px;opacity:.95;margin:10px 0 3px;color:#9fd0ff}
input,textarea,select{width:100%;box-sizing:border-box;background:#081122;border:1px solid #2a8fd6;border-radius:4px;color:#d5ffe6;padding:9px 10px;font-size:16px;box-shadow:0 0 0 1px rgba(62,252,154,.12) inset}
input:focus,textarea:focus,select:focus{outline:none;border-color:#3efc9a;box-shadow:0 0 0 1px rgba(62,252,154,.4),0 0 12px rgba(62,252,154,.2)}
textarea{height:96px;resize:vertical}.row{display:flex;gap:10px}.row>div{flex:1}
button,a.btn{margin-top:6px;background:linear-gradient(180deg,#15345f 0%,#10233d 100%);border:1px solid #2ea8ff;color:#e5f4ff;padding:10px 18px;border-radius:4px;font-size:15px;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,a.btn:hover{background:linear-gradient(180deg,#1d4b88 0%,#15345f 100%)}
button.sec{background:linear-gradient(180deg,#2a2056 0%,#20193f 100%);border-color:#7c6bff}
.result{margin-top:16px;background:#091227;border:1px solid #2b87cf;border-radius:4px;padding:12px;font-size:15px;white-space:pre-wrap}
.ok{color:#8effb8}.err{color:#ff9bbb}
.section{background:linear-gradient(160deg,#0b1326 0%,#09101f 100%);border:2px solid #1f79b5;border-radius:6px;padding:12px;margin-bottom:12px}
.section-title{font-size:13px;font-weight:700;opacity:.95;text-transform:uppercase;letter-spacing:.08em;color:#8ec9ff}
.note{font-size:12px;opacity:.85;margin-top:4px;color:#95cfff}
</style></head><body><div class="wrap">
<h1>🎞️ Wan2.1 — Text to Video</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>
<div class="note" style="margin-bottom:16px">Requiere: ComfyUI-WanVideoWrapper + modelos en <code>diffusion_models/</code>, <code>text_encoders/</code> y <code>vae/</code></div>
<form id="wf" method="post" onsubmit="return handleWanSubmit(event)">
  <div class="section"><div class="section-title">Modelo y perfil</div>
    <div class="row">
      <div><label>Modelo</label><select name="model_preset">
        {% for p in model_presets %}<option value="{{ p.id }}" {% if p.id==form.model_preset %}selected{% endif %}>{{ p.name }}</option>{% endfor %}
      </select></div>
      <div><label>Perfil de vídeo</label><select name="video_profile" onchange="applyProfile(this)">
        {% for p in video_profiles %}<option value="{{ p.id }}" {% if p.id==form.video_profile %}selected{% endif %}>{{ p.name }} — {{ p.desc }}</option>{% endfor %}
      </select></div>
    </div>
  </div>
  <div class="section"><div class="section-title">Prompt</div>
        <label>Perfil de personaje</label><select id="wan_character_preset" name="character_preset" onchange="applyCharacterPrompt(this, 'wf')">
            <option value="">Manual (sin perfil)</option>
            {% for p in character_prompt_presets %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}
        </select>
    <label>Prompt positivo</label><textarea name="positive_prompt">{{ form.positive_prompt }}</textarea>
    <label>Prompt negativo</label><textarea name="negative_prompt" style="height:60px">{{ form.negative_prompt }}</textarea>
  </div>
  <div class="section"><div class="section-title">Parámetros</div>
    <div class="row">
      <div><label>Ancho</label><input name="width" type="number" min="256" max="1280" step="8" value="{{ form.width }}"></div>
      <div><label>Alto</label><input name="height" type="number" min="256" max="1280" step="8" value="{{ form.height }}"></div>
      <div><label>Frames</label><input name="frames" type="number" min="8" max="121" value="{{ form.frames }}"></div>
      <div><label>FPS</label><input name="fps" type="number" min="4" max="30" value="{{ form.fps }}"></div>
    </div>
    <div class="row">
      <div><label>Steps</label><input name="steps" type="number" min="10" max="50" value="{{ form.steps }}"></div>
      <div><label>CFG</label><input name="cfg" type="number" min="1" max="15" step="0.5" value="{{ form.cfg }}"></div>
      <div><label>Shift</label><input name="shift" type="number" min="1.0" max="20.0" step="0.5" value="{{ form.shift }}"></div>
      <div><label>Seed</label><input name="seed" type="number" value="{{ form.seed }}"></div>
    </div>
    <div class="row">
      <div><label>CRF</label><input name="crf" type="number" min="14" max="28" value="{{ form.crf }}"></div>
      <div><label>Pixel format</label><select name="pix_fmt">
        <option value="yuv420p" {% if form.pix_fmt=='yuv420p' %}selected{% endif %}>yuv420p</option>
        <option value="yuv420p10le" {% if form.pix_fmt=='yuv420p10le' %}selected{% endif %}>yuv420p10le</option>
      </select></div>
    </div>
  </div>
  <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
    <button type="submit">🎞️ Generar vídeo</button>
        <a class="btn" href="http://localhost:8188" target="_blank" rel="noopener noreferrer">📋 Abrir ComfyUI (cola)</a>
    <button type="button" class="sec" onclick="exportWf()">📤 Exportar workflow JSON</button>
  </div>
</form>
{% if server_result %}
<div id="result" class="result {{ 'ok' if server_result_ok else 'err' }}">{{ server_result }}</div>
{% else %}
<div id="result" class="result" style="display:none"></div>
{% endif %}
</div>
<script>
const profiles={{video_profiles_json|safe}};
function applyProfile(sel){
  const p=profiles.find(x=>x.id===sel.value);if(!p)return;
  const f=document.getElementById('wf');
  ['width','height','frames','fps','steps','cfg','shift','crf'].forEach(k=>{if(f[k]&&p[k]!==undefined)f[k].value=p[k];});
}
async function applyCharacterPrompt(sel, formId){
    const id=sel.value;
    const f=document.getElementById(formId);if(!f)return;
    const pos=f.querySelector('[name="positive_prompt"]');
    const neg=f.querySelector('[name="negative_prompt"]');
        const r=document.getElementById('result');
    if(!id){
        if(pos) pos.value='';
        if(neg) neg.value='';
                if(r){
                    r.style.display='block';
                    r.className='result ok';
                    r.textContent='Perfil manual: prompts limpiados.';
                }
        return;
    }
    try{
        const resp=await fetch('/tools/character-video-prompt/'+encodeURIComponent(id));
        const data=await resp.json();
        if(!data.ok)return;
        if(pos && data.positive_prompt) pos.value=data.positive_prompt;
        if(neg && data.negative_prompt) neg.value=data.negative_prompt;
                if(r){
                    r.style.display='block';
                    r.className='result ok';
                    r.textContent='Perfil cargado: '+(data.name||id)+'\\nPrompt+ y Prompt- actualizados.';
                }
    }catch(_err){
                if(r){
                    r.style.display='block';
                    r.className='result err';
                    r.textContent='Error cargando perfil '+id+'. Revisa /tmp/landing-trace.log';
                }
        // El fallback de backend al enviar mantiene funcionalidad incluso si falla la UI.
    }
}
async function handleWanSubmit(e){
  e.preventDefault();const r=document.getElementById('result');
  r.style.display='block';r.className='result';r.textContent='Enviando a ComfyUI...';
  const fd=new FormData(e.target);
  try{
        const resp=await fetch('/tools/wan-video',{
            method:'POST',
            headers:{'X-Requested-With':'XMLHttpRequest'},
            body:new URLSearchParams(fd)
        });
    const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
        let msg=data.message||'';
    if(data.prompt_id)msg+='\\nPrompt ID: '+data.prompt_id;
    if(data.output_prefix)msg+='\\nOutput: '+data.output_prefix;
        if(data.workflow_mode)msg+='\\nWorkflow mode: '+data.workflow_mode;
        if(data.workflow_file)msg+='\\nWorkflow file: '+data.workflow_file;
        if(data.used_model)msg+='\\nModel: '+data.used_model;
        if(data.used_text_encoder)msg+='\\nText encoder: '+data.used_text_encoder;
        if(data.used_vae)msg+='\\nVAE: '+data.used_vae;
        if(data.used_positive_prompt)msg+='\\nPrompt+: '+data.used_positive_prompt;
    if(data.ok)msg+='\\n→ ComfyUI: http://localhost:8188 (Queue en barra lateral)';
    r.textContent=msg;
    }catch(err){r.className='result err';r.textContent='Error: '+err;}
    return false;
}
async function exportWf(){
  const r=document.getElementById('result');r.style.display='block';r.className='result';r.textContent='Exportando...';
  const fd=new FormData(document.getElementById('wf'));
  try{
    const resp=await fetch('/tools/wan-video/export',{method:'POST',body:new URLSearchParams(fd)});
    const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
    r.textContent=data.message+(data.path?'\\n'+data.path:'');
  }catch(err){r.className='result err';r.textContent='Error: '+err;}
}
</script></body></html>
"""

# --- HTML WAN2.1 I2V TOOL ----------------------------------------------------
WAN_I2V_TOOL_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Wan2.1 I2V — Escena desde imagen</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(950px 520px at 90% -20%,#1a2748 0%,#06070d 62%);color:#d5ffe6;margin:0}
.wrap{max-width:860px;margin:36px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px;text-shadow:0 0 8px rgba(62,252,154,.35)}
.back{font-size:14px;opacity:.9;margin-bottom:18px}.back a{color:#78c7ff;text-decoration:none}
label{display:block;font-size:13px;opacity:.95;margin:10px 0 3px;color:#9fd0ff}
input,textarea,select{width:100%;box-sizing:border-box;background:#081122;border:1px solid #2a8fd6;border-radius:4px;color:#d5ffe6;padding:9px 10px;font-size:16px;box-shadow:0 0 0 1px rgba(62,252,154,.12) inset}
input:focus,textarea:focus,select:focus{outline:none;border-color:#3efc9a;box-shadow:0 0 0 1px rgba(62,252,154,.4),0 0 12px rgba(62,252,154,.2)}
textarea{height:96px;resize:vertical}.row{display:flex;gap:10px}.row>div{flex:1}
button,a.btn{margin-top:8px;background:linear-gradient(180deg,#15345f 0%,#10233d 100%);border:1px solid #2ea8ff;color:#e5f4ff;padding:10px 18px;border-radius:4px;font-size:15px;cursor:pointer;text-decoration:none;display:inline-block}
button:hover,a.btn:hover{background:linear-gradient(180deg,#1d4b88 0%,#15345f 100%)}
.result{margin-top:16px;background:#091227;border:1px solid #2b87cf;border-radius:4px;padding:12px;font-size:15px;white-space:pre-wrap}
.ok{color:#8effb8}.err{color:#ff9bbb}
.section{background:linear-gradient(160deg,#0b1326 0%,#09101f 100%);border:2px solid #1f79b5;border-radius:6px;padding:12px;margin-bottom:12px}
.section-title{font-size:13px;font-weight:700;opacity:.95;text-transform:uppercase;letter-spacing:.08em;color:#8ec9ff}
.note{font-size:12px;opacity:.85;margin-top:6px;color:#95cfff}
</style></head><body><div class="wrap">
<h1>🖼️ Wan2.1 I2V — Escena desde imagen</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>
<div class="note" style="margin-bottom:16px">Usa una imagen base estable en <code>ComfyUI/input</code> para reducir carrusel y flicker.</div>
<form id="i2vf" method="post" onsubmit="return handleI2VSubmit(event)">
    <div class="section"><div class="section-title">Imagen base y prompt</div>
        <label>Imágenes detectadas en ComfyUI/input</label>
        <div class="row">
            <div style="flex:3">
                <select id="image_name_select" onchange="syncImageName()">
                    {% if input_images|length == 0 %}
                    <option value="">(sin imágenes detectadas)</option>
                    {% else %}
                    {% for img in input_images %}<option value="{{ img }}" {% if img==form.image_name %}selected{% endif %}>{{ img }}</option>{% endfor %}
                    {% endif %}
                </select>
            </div>
            <div style="flex:1">
                <button type="button" onclick="refreshInputImages()">Actualizar lista</button>
            </div>
        </div>
        <label>Imagen base (nombre de archivo en ComfyUI/input)</label>
        <input name="image_name" placeholder="ej: akika_base.png" value="{{ form.image_name }}">
        <label>Prompt positivo</label><textarea name="positive_prompt">{{ form.positive_prompt }}</textarea>
        <label>Prompt negativo</label><textarea name="negative_prompt" style="height:60px">{{ form.negative_prompt }}</textarea>
    </div>
    <div class="section"><div class="section-title">Modelo y parámetros</div>
        <div class="row">
            <div><label>Modelo</label><select name="model_preset">
                {% for p in model_presets %}<option value="{{ p.id }}" {% if p.id==form.model_preset %}selected{% endif %}>{{ p.name }}</option>{% endfor %}
            </select></div>
            <div><label>Perfil de vídeo</label><select name="video_profile" onchange="applyProfile(this)">
                {% for p in video_profiles %}<option value="{{ p.id }}" {% if p.id==form.video_profile %}selected{% endif %}>{{ p.name }} — {{ p.desc }}</option>{% endfor %}
            </select></div>
        </div>
        <div class="row">
            <div><label>Frames</label><input name="frames" type="number" min="8" max="121" value="{{ form.frames }}"></div>
            <div><label>FPS</label><input name="fps" type="number" min="4" max="30" value="{{ form.fps }}"></div>
            <div><label>Steps</label><input name="steps" type="number" min="10" max="50" value="{{ form.steps }}"></div>
            <div><label>CFG</label><input name="cfg" type="number" min="1" max="15" step="0.5" value="{{ form.cfg }}"></div>
        </div>
        <div class="row">
            <div><label>Shift</label><input name="shift" type="number" min="1.0" max="20.0" step="0.5" value="{{ form.shift }}"></div>
            <div><label>Seed</label><input name="seed" type="number" value="{{ form.seed }}"></div>
            <div><label>CRF</label><input name="crf" type="number" min="14" max="28" value="{{ form.crf }}"></div>
            <div><label>Pixel format</label><select name="pix_fmt">
                <option value="yuv420p" {% if form.pix_fmt=='yuv420p' %}selected{% endif %}>yuv420p</option>
                <option value="yuv420p10le" {% if form.pix_fmt=='yuv420p10le' %}selected{% endif %}>yuv420p10le</option>
            </select></div>
        </div>
    </div>
    <div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
        <button type="submit">🎞️ Generar escena I2V</button>
        <a class="btn" href="http://localhost:8188" target="_blank" rel="noopener noreferrer">📋 Abrir ComfyUI (cola)</a>
    </div>
</form>
<div id="result" class="result" style="display:none"></div>
<script>
const profiles={{video_profiles_json|safe}};
function syncImageName(){
    const sel=document.getElementById('image_name_select');
    const f=document.getElementById('i2vf');
    if(!sel||!f||!f.image_name)return;
    if(sel.value)f.image_name.value=sel.value;
}
async function refreshInputImages(){
    const r=document.getElementById('result');
    const sel=document.getElementById('image_name_select');
    if(!sel)return;

    const previous=sel.value;
    if(r){
        r.style.display='block';
        r.className='result';
        r.textContent='Refrescando imágenes de ComfyUI/input...';
    }
    try{
        const resp=await fetch('/tools/wan-i2v/input-images');
        const data=await resp.json();
        sel.innerHTML='';
        const images=Array.isArray(data.images)?data.images:[];
        if(images.length===0){
            const opt=document.createElement('option');
            opt.value='';
            opt.textContent='(sin imágenes detectadas)';
            sel.appendChild(opt);
        }else{
            for(const img of images){
                const opt=document.createElement('option');
                opt.value=img;
                opt.textContent=img;
                sel.appendChild(opt);
            }
            const exists=images.includes(previous);
            sel.value=exists?previous:images[0];
        }
        syncImageName();
        if(r){
            r.className='result ok';
            r.textContent='Lista actualizada ('+images.length+' imágenes).';
        }
    }catch(err){
        if(r){
            r.className='result err';
            r.textContent='Error refrescando lista: '+err;
        }
    }
}
function applyProfile(sel){
    const p=profiles.find(x=>x.id===sel.value);if(!p)return;
    const f=document.getElementById('i2vf');
    ['frames','fps','steps','cfg','shift','crf'].forEach(k=>{if(f[k]&&p[k]!==undefined)f[k].value=p[k];});
}
async function handleI2VSubmit(e){
    e.preventDefault();const r=document.getElementById('result');
    r.style.display='block';r.className='result';r.textContent='Enviando I2V a ComfyUI...';
    const fd=new FormData(e.target);
    try{
        const resp=await fetch('/tools/wan-i2v',{method:'POST',headers:{'X-Requested-With':'XMLHttpRequest'},body:new URLSearchParams(fd)});
        const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
        let msg=data.message||'';
        if(data.prompt_id)msg+='\\nPrompt ID: '+data.prompt_id;
        if(data.output_prefix)msg+='\\nOutput: '+data.output_prefix;
        if(data.workflow_file)msg+='\\nWorkflow file: '+data.workflow_file;
        if(data.used_image)msg+='\\nImage: '+data.used_image;
        if(data.ok)msg+='\\n→ ComfyUI: http://localhost:8188 (Queue en barra lateral)';
        r.textContent=msg;
    }catch(err){r.className='result err';r.textContent='Error: '+err;}
    return false;
}
syncImageName();
</script></div></body></html>
"""

# --- HTML GAME TTS TOOL -------------------------------------------------------
GAME_TTS_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Game TTS Personality</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(980px 560px at 0% -20%,#10295a 0%,#06070d 62%);color:#d5ffe6;margin:0}
.wrap{max-width:920px;margin:36px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px;text-shadow:0 0 8px rgba(62,252,154,.35)}
.back{font-size:14px;opacity:.9;margin-bottom:18px}.back a{color:#78c7ff;text-decoration:none}
.section{background:linear-gradient(160deg,#0b1326 0%,#09101f 100%);border:2px solid #1f79b5;border-radius:6px;padding:12px;margin-bottom:12px}
.section-title{font-size:13px;font-weight:700;opacity:.95;text-transform:uppercase;letter-spacing:.08em;color:#8ec9ff;margin-bottom:8px}
label{display:block;font-size:13px;opacity:.95;margin:10px 0 3px;color:#9fd0ff}
input,textarea,select{width:100%;box-sizing:border-box;background:#081122;border:1px solid #2a8fd6;border-radius:4px;color:#d5ffe6;padding:9px 10px;font-size:16px;box-shadow:0 0 0 1px rgba(62,252,154,.12) inset}
input:focus,textarea:focus,select:focus{outline:none;border-color:#3efc9a;box-shadow:0 0 0 1px rgba(62,252,154,.4),0 0 12px rgba(62,252,154,.2)}
textarea{height:180px;resize:vertical}
.row{display:flex;gap:10px}.row>div{flex:1}
button{margin-top:10px;background:linear-gradient(180deg,#15345f 0%,#10233d 100%);border:1px solid #2ea8ff;color:#e5f4ff;padding:10px 18px;border-radius:4px;font-size:15px;cursor:pointer}
button:hover{background:linear-gradient(180deg,#1d4b88 0%,#15345f 100%)}
.result{margin-top:14px;background:#091227;border:1px solid #2b87cf;border-radius:4px;padding:12px;font-size:15px;white-space:pre-wrap}
.ok{color:#8effb8}.err{color:#ff9bbb}.note{font-size:12px;opacity:.85;margin-top:4px;color:#95cfff}
audio{width:100%;margin-top:10px}
.hint{font-size:12px;color:#9cc5ea;opacity:.9;margin-top:5px}
</style></head><body><div class="wrap">
<h1>🎮 Game TTS Personality</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>

<form id="tts-form" onsubmit="return generateGameTTS(event)">
    <div class="section"><div class="section-title">Motor y personaje</div>
        <div class="row">
            <div><label>Motor TTS</label><select name="engine" id="engine" onchange="applyEngineMode()">
                <option value="piper">Piper (rápido, local)</option>
                <option value="xtts">XTTS v2 (personajes expresivos)</option>
            </select></div>
            <div><label>Personaje</label><select name="character_id" id="character_id" onchange="applyCharacterMeta()">
                {% for c in characters %}<option value="{{ c.id }}" data-speaker="{{ c.speaker_wav }}">{{ c.name }}</option>{% endfor %}
            </select></div>
            <div><label>Idioma</label><select name="language" id="language">
                <option value="es">Español</option>
                <option value="en">English</option>
            </select></div>
        </div>
        <div class="row" id="piper-model-row">
            <div><label>Modelo Piper</label><select name="piper_model" id="piper_model">
                {% for m in piper_models %}<option value="{{ m.id }}" {% if m.id==form.piper_model %}selected{% endif %}>{{ m.name }} ({{ m.id }})</option>{% endfor %}
            </select></div>
            <div style="flex:2"><div class="hint" id="engine-hint"></div></div>
        </div>
        <div id="speaker-hint" class="hint"></div>
    </div>

    <div class="section"><div class="section-title">Preset de personalidad</div>
        <div class="row">
            <div><label>Preset</label><select name="personality_id" id="personality_id" onchange="applyPreset()">
                {% for p in personalities %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}
            </select></div>
            <div><label>voice_id</label><input type="text" name="voice_id" id="voice_id" readonly></div>
        </div>
        <div class="row">
            <div><label>speed</label><input type="number" name="speed" id="speed" step="0.01" min="0.2" max="2.0"></div>
            <div><label>pitch</label><input type="number" name="pitch" id="pitch" step="0.01" min="0.5" max="2.0"></div>
            <div><label>energy</label><input type="number" name="energy" id="energy" step="0.01" min="0.5" max="2.0"></div>
        </div>
        <div class="row">
            <div><label>emotion tags</label><input type="text" name="emotion_tags" id="emotion_tags"></div>
            <div><label>pausas</label><select name="pauses" id="pauses">
                <option value="short">short</option>
                <option value="medium">medium</option>
                <option value="long">long</option>
            </select></div>
        </div>
        <div class="note">Piper usa speed. XTTS usa speaker WAV + speed (si la versión lo soporta). El resto de parámetros se conservan en preset para tu pipeline de juego.</div>
    </div>

    <div class="section"><div class="section-title">Texto</div>
        <label>Texto de entrada</label>
        <textarea name="text" id="text" placeholder="Escribe aquí el diálogo del personaje..."></textarea>
        <button type="submit">🔊 Generar audio</button>
    </div>
</form>

<div id="result" class="result" style="display:none"></div>
<audio id="audio" controls style="display:none"></audio>
<div id="saved" class="hint" style="display:none"></div>

<script>
const personalities={{personalities_json|safe}};
const piperRecommendations={{piper_recommendations_json|safe}};
function applyEngineMode(){
    const engine=document.getElementById('engine').value;
    const pRow=document.getElementById('piper-model-row');
    const eHint=document.getElementById('engine-hint');
    const speakerHint=document.getElementById('speaker-hint');
    if(engine==='piper'){
        if(pRow) pRow.style.display='flex';
        if(eHint) eHint.textContent='Piper usa el modelo seleccionado arriba.';
    }else{
        if(pRow) pRow.style.display='none';
        if(eHint) eHint.textContent='XTTS ignora el modelo Piper y usa speaker WAV del personaje.';
    }
    if(speakerHint) speakerHint.style.display=(engine==='xtts')?'block':'none';
}
function applyPreset(){
    const id=document.getElementById('personality_id').value;
    const p=personalities.find(x=>x.id===id);if(!p)return;
    document.getElementById('voice_id').value=p.voice_id||'';
    document.getElementById('speed').value=p.speed||1.0;
    document.getElementById('pitch').value=p.pitch||1.0;
    document.getElementById('energy').value=p.energy||1.0;
    document.getElementById('emotion_tags').value=p.emotion_tags||'';
    document.getElementById('pauses').value=p.pauses||'medium';
}
function applyCharacterMeta(){
    const sel=document.getElementById('character_id');
    const opt=sel.options[sel.selectedIndex];
    const characterId=(opt&&opt.value)||'';
    const speaker=(opt&&opt.dataset&&opt.dataset.speaker)||'';
    const piperSel=document.getElementById('piper_model');
    const hint=document.getElementById('speaker-hint');
    const eHint=document.getElementById('engine-hint');

    if(piperSel && characterId && piperRecommendations[characterId]){
        const target=piperRecommendations[characterId];
        const hasOption=[...piperSel.options].some(o=>o.value===target);
        if(hasOption){
            piperSel.value=target;
            if(eHint && document.getElementById('engine').value==='piper'){
                eHint.textContent='Modelo recomendado para '+characterId+': '+target;
            }
        }
    }

    hint.textContent=speaker?('speaker WAV: '+speaker):'speaker WAV: no detectado (necesario para XTTS)';
}
async function generateGameTTS(e){
    e.preventDefault();
    const res=document.getElementById('result');
    const audio=document.getElementById('audio');
    const saved=document.getElementById('saved');
    res.style.display='block';res.className='result';res.textContent='Generando audio...';
    audio.style.display='none';saved.style.display='none';
    const fd=new FormData(document.getElementById('tts-form'));
    try{
        const resp=await fetch('/tools/game-tts/generate',{
            method:'POST',
            headers:{'X-Requested-With':'XMLHttpRequest'},
            body:new URLSearchParams(fd)
        });
        const data=await resp.json();
        res.className='result '+(data.ok?'ok':'err');
        res.textContent=data.message||'';
        if(data.ok&&data.audio_url){
            audio.src=data.audio_url+'?t='+Date.now();
            audio.style.display='block';
            saved.style.display='block';
            saved.textContent='Guardado en: '+(data.path||'');
        }
    }catch(err){
        res.className='result err';res.textContent='Error: '+err;
    }
    return false;
}
applyPreset();
applyCharacterMeta();
applyEngineMode();
</script>
</div></body></html>
"""

# --- HTML OLLAMA CUSTOM MODELS TOOL ------------------------------------------
OLLAMA_MODELS_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Ollama Custom Models</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:"VT323","Press Start 2P","Lucida Console",monospace;background:radial-gradient(900px 500px at 50% -10%,#1a2748 0%,#06070d 60%);color:#d5ffe6;margin:0}
.wrap{max-width:920px;margin:36px auto;padding:0 18px}
h1{font-size:28px;margin:0 0 8px;text-shadow:0 0 8px rgba(62,252,154,.35)}
.back{font-size:14px;opacity:.9;margin-bottom:18px}.back a{color:#78c7ff;text-decoration:none}
.section{background:linear-gradient(160deg,#0b1326 0%,#09101f 100%);border:2px solid #1f79b5;border-radius:6px;padding:12px;margin-bottom:12px}
.section-title{font-size:13px;font-weight:700;opacity:.95;text-transform:uppercase;letter-spacing:.08em;color:#8ec9ff;margin-bottom:8px}
label{display:block;font-size:13px;opacity:.95;margin:10px 0 3px;color:#9fd0ff}
input,textarea,select{width:100%;box-sizing:border-box;background:#081122;border:1px solid #2a8fd6;border-radius:4px;color:#d5ffe6;padding:9px 10px;font-size:16px;box-shadow:0 0 0 1px rgba(62,252,154,.12) inset}
input:focus,textarea:focus,select:focus{outline:none;border-color:#3efc9a;box-shadow:0 0 0 1px rgba(62,252,154,.4),0 0 12px rgba(62,252,154,.2)}
textarea{height:140px;resize:vertical}.row{display:flex;gap:10px}.row>div{flex:1}
button{margin-top:10px;background:linear-gradient(180deg,#15345f 0%,#10233d 100%);border:1px solid #2ea8ff;color:#e5f4ff;padding:10px 18px;border-radius:4px;font-size:15px;cursor:pointer}
button:hover{background:linear-gradient(180deg,#1d4b88 0%,#15345f 100%)}
.result{margin-top:14px;background:#091227;border:1px solid #2b87cf;border-radius:4px;padding:12px;font-size:15px;white-space:pre-wrap}
.ok{color:#8effb8}.err{color:#ff9bbb}
ul{margin:0;padding-left:18px}
</style></head><body><div class="wrap">
<h1>🧠 Ollama Custom Models</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>

<div class="section">
    <div class="section-title">Modelos locales</div>
    <button type="button" onclick="refreshModels()">Actualizar lista</button>
    <div id="models" class="result" style="margin-top:10px">Cargando...</div>
</div>

<div class="section">
    <div class="section-title">Descargar modelo base (pull)</div>
    <label>Modelo</label>
    <input id="pull_model" placeholder="ej: llama3.1:8b o qwen2.5:14b" />
    <button type="button" onclick="pullModel()">Descargar</button>
</div>

<div class="section">
    <div class="section-title">Crear modelo custom (modelfile)</div>
    <label>Preset de system prompt</label>
    <select id="prompt_preset" onchange="applyPromptPreset()">
        <option value="">Manual (sin preset)</option>
        {% for p in prompt_presets %}
        <option value="{{ p.id }}">{{ p.name }}{% if p.base_model %} (base: {{ p.base_model }}){% endif %}</option>
        {% endfor %}
    </select>
    <div class="row">
        <div>
            <label>Nombre del nuevo modelo</label>
            <input id="new_model" placeholder="ej: jonathan/qwen2.5-geospatial:latest" />
        </div>
        <div>
            <label>Modelo base</label>
            <input id="base_model" placeholder="ej: qwen2.5:14b" />
        </div>
    </div>
    <label>System prompt</label>
    <textarea id="system_prompt" placeholder="Eres un asistente experto en GIS...\nResponde conciso..."></textarea>
    <button type="button" onclick="createCustom()">Crear custom model</button>
</div>

<div id="result" class="result" style="display:none"></div>

</div>
<script>
const PROMPT_PRESETS={{prompt_presets_json}};

function show(msg, ok=true){
    const r=document.getElementById('result');
    r.style.display='block';
    r.className='result '+(ok?'ok':'err');
    r.textContent=msg;
}

function applyPromptPreset(){
    const id=document.getElementById('prompt_preset').value;
    if(!id)return;
    const preset=PROMPT_PRESETS.find(p=>p.id===id);
    if(!preset)return;
    if(preset.base_model) document.getElementById('base_model').value=preset.base_model;
    if(preset.system_prompt) document.getElementById('system_prompt').value=preset.system_prompt;
}

async function refreshModels(){
    const out=document.getElementById('models');
    out.textContent='Cargando modelos...';
    try{
        const resp=await fetch('/tools/ollama-models/list');
        const data=await resp.json();
        if(!data.ok){out.textContent='Error: '+(data.message||'');return;}
        if(!data.models || !data.models.length){out.textContent='No hay modelos locales todavía.';return;}
        out.innerHTML='<ul>'+data.models.map(m=>`<li>${m}</li>`).join('')+'</ul>';
    }catch(err){out.textContent='Error: '+err;}
}

async function pullModel(){
    const model=document.getElementById('pull_model').value.trim();
    if(!model){show('Indica un modelo para descargar.', false);return;}
    show('Descargando modelo en Ollama... puede tardar.');
    try{
        const resp=await fetch('/tools/ollama-models/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model})});
        const data=await resp.json();
        show(data.message||'OK', !!data.ok);
        if(data.ok) refreshModels();
    }catch(err){show('Error: '+err, false);}
}

async function createCustom(){
    const model=document.getElementById('new_model').value.trim();
    const base=document.getElementById('base_model').value.trim();
    const system=document.getElementById('system_prompt').value.trim();
    if(!model || !base){show('Completa nombre y modelo base.', false);return;}
    show('Creando modelo custom en Ollama...');
    try{
        const resp=await fetch('/tools/ollama-models/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:model,base_model:base,system_prompt:system})});
        const data=await resp.json();
        show(data.message||'OK', !!data.ok);
        if(data.ok) refreshModels();
    }catch(err){show('Error: '+err, false);}
}

refreshModels();
</script>
</body></html>
"""


# --- UTILIDADES ---------------------------------------------------------------
def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False


def check_all_status() -> dict:
    def _check(svc):
        return svc["key"], port_open(svc["port"])

    with ThreadPoolExecutor(max_workers=len(SERVICES)) as ex:
        return dict(ex.map(_check, SERVICES))


def run_bg(cmd: list[str], pidfile: Path, cwd: Path | None = None) -> int:
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    pidfile.write_text(str(proc.pid))
    return proc.pid


def kill_from_pidfile(pidfile: Path):
    if not pidfile.exists():
        return
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 15)
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
        subprocess.run(
            ["docker", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


def _wait_for_port(port: int, timeout: float = 30.0, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(interval)
    return False


def slugify_text(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "_", s).strip("_")
    return s[:max_len]


def clamp_step(val: int, lo: int, hi: int, step: int) -> int:
    val = max(lo, min(hi, val))
    if step > 1:
        val = round(val / step) * step
    return val


# --- MANEJO SERVICIOS ---------------------------------------------------------
RUN_DIR = AI_DIR / "run"
ensure_dir(RUN_DIR)
COMFY_PID = RUN_DIR / "comfyui.pid"
VOICE_PID = RUN_DIR / "voice.pid"
ADULT_CHATBOT_PID = RUN_DIR / "adult_chatbot_manga.pid"


def comfy_start():
    if port_open(COMFY_PORT):
        return "already"
    log.info("Arrancando ComfyUI...")
    return run_bg(COMFY_CMD, COMFY_PID, cwd=COMFY_DIR)


def comfy_stop():
    global _comfy_nodes_cache
    _comfy_nodes_cache = None
    kill_from_pidfile(COMFY_PID)


def comfy_restart(wait_timeout: float = 45.0) -> bool:
    comfy_stop()
    time.sleep(0.6)
    comfy_start()
    up = _wait_for_port(COMFY_PORT, timeout=wait_timeout)
    if up:
        log.info("ComfyUI UP tras restart")
    else:
        log.warning("ComfyUI no respondió tras restart")
    return up


def ensure_wan_runtime_ready() -> bool:
    global _comfy_nodes_cache
    if not WAN_WRAPPER_DIR.exists():
        log.warning("Wan wrapper no encontrado en %s", WAN_WRAPPER_DIR)
        return False
    if not port_open(COMFY_PORT):
        log.warning("ComfyUI no está activo; no se puede verificar Wan")
        return False

    _comfy_nodes_cache = None
    missing = check_comfy_nodes(WAN_REQUIRED_NODES)
    if not missing:
        log.info("Wan runtime OK (nodos cargados)")
        return True

    log.warning("Faltan nodos Wan al boot: %s", ", ".join(missing))
    log.info("Reiniciando ComfyUI para recargar custom nodes...")
    if not comfy_restart(wait_timeout=60.0):
        return False

    _comfy_nodes_cache = None
    missing_after = check_comfy_nodes(WAN_REQUIRED_NODES)
    if missing_after:
        log.warning(
            "Wan sigue incompleto tras restart: %s. Revisa dependencias/imports del wrapper.",
            ", ".join(missing_after),
        )
        return False

    log.info("Wan runtime OK tras restart")
    return True


def voice_start():
    if port_open(VOICE_PORT):
        return "already"
    if not VOICE_SCRIPT.exists():
        log.warning(f"Voice script no encontrado: {VOICE_SCRIPT}")
        return f"script_not_found:{VOICE_SCRIPT}"
    log.info("Arrancando Voice UI...")
    return run_bg(VOICE_CMD, VOICE_PID)


def voice_stop():
    kill_from_pidfile(VOICE_PID)


def adult_chatbot_start():
    if port_open(ADULT_CHATBOT_PORT):
        return "already"
    if not ADULT_CHATBOT_DIR.exists():
        log.warning("adult_chatbot_manga no encontrado: %s", ADULT_CHATBOT_DIR)
        return f"dir_not_found:{ADULT_CHATBOT_DIR}"
    log.info("Arrancando adult_chatbot_manga...")
    return run_bg(ADULT_CHATBOT_CMD, ADULT_CHATBOT_PID, cwd=ADULT_CHATBOT_DIR)


def adult_chatbot_stop():
    kill_from_pidfile(ADULT_CHATBOT_PID)


def ollama_start():
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
    r = subprocess.run(
        ["docker", "start", OW_CONTAINER],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if r.returncode == 0:
        return "started"
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        OW_CONTAINER,
        "-p",
        f"{OW_PORT}:8080",
        "--network",
        "host",
        "-e",
        f"OLLAMA_BASE_URL=http://127.0.0.1:{OLLAMA_PORT}",
        "-v",
        "openwebui-data:/app/backend/data",
        "--restart",
        "unless-stopped",
        OW_IMAGE,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return (
        "run_ok"
        if r.returncode == 0
        else f"run_fail:{r.stderr.decode(errors='ignore')}"
    )


def openwebui_stop():
    if not have_docker():
        return
    subprocess.run(
        ["docker", "stop", OW_CONTAINER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# --- AUTOINICIO ---------------------------------------------------------------
def autostart():
    log.info("=== autostart inicio ===")
    if not port_open(OLLAMA_PORT):
        log.info("Ollama DOWN — arrancando...")
        ollama_start()
        if _wait_for_port(OLLAMA_PORT, timeout=15):
            log.info("Ollama UP")
        else:
            log.warning("Ollama no respondió en 15s")
    if not port_open(OW_PORT):
        log.info("Open WebUI DOWN — arrancando...")
        openwebui_start()
        if _wait_for_port(OW_PORT, timeout=30):
            log.info("Open WebUI UP")
        else:
            log.warning("Open WebUI no respondió en 30s")
    if not port_open(COMFY_PORT):
        log.info("ComfyUI DOWN — arrancando...")
        comfy_start()
        if _wait_for_port(COMFY_PORT, timeout=30):
            log.info("ComfyUI UP")
        else:
            log.warning("ComfyUI no respondió en 30s")
    else:
        log.info("ComfyUI ya estaba UP")

    # Bootstrap Wan en el arranque de la landing: valida que los nodos estén cargados.
    ensure_wan_runtime_ready()

    if not port_open(VOICE_PORT):
        log.info("Voice UI DOWN — arrancando...")
        voice_start()
        if _wait_for_port(VOICE_PORT, timeout=30):
            log.info("Voice UI UP")
        else:
            log.warning("Voice UI no respondió en 30s")
    log.info("=== autostart fin ===")


# --- COMFYUI API --------------------------------------------------------------
_comfy_nodes_cache = None


def comfy_api_get(path: str) -> dict:
    url = f"http://127.0.0.1:{COMFY_PORT}{path}"
    with urlrequest.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def comfy_api_post(path: str, payload: dict) -> dict:
    url = f"http://127.0.0.1:{COMFY_PORT}{path}"
    data = json.dumps(payload).encode()
    req = urlrequest.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urlrequest.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def check_comfy_nodes(required):
    global _comfy_nodes_cache
    if _comfy_nodes_cache is None:
        try:
            obj_info = comfy_api_get("/object_info")
            _comfy_nodes_cache = set(obj_info.keys())
        except Exception as exc:
            log.warning(f"No se pudo consultar /object_info: {exc}")
            return []
    return [n for n in required if n not in _comfy_nodes_cache]


def get_comfy_object_info() -> dict:
    try:
        return comfy_api_get("/object_info")
    except Exception as exc:
        log.warning(f"No se pudo consultar object_info: {exc}")
        return {}


def get_node_input_options(obj_info: dict, node_class: str, input_name: str):
    node = obj_info.get(node_class, {})
    required = node.get("input", {}).get("required", {})
    cfg = required.get(input_name)
    if isinstance(cfg, list) and cfg and isinstance(cfg[0], list):
        return cfg[0]
    return []


def _ensure_ollama_up(timeout: float = 20.0) -> bool:
    if port_open(OLLAMA_PORT):
        return True
    ollama_start()
    return _wait_for_port(OLLAMA_PORT, timeout=timeout)


def ollama_api_get(path: str) -> dict:
    url = f"http://127.0.0.1:{OLLAMA_PORT}{path}"
    with urlrequest.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read())


def ollama_api_post(path: str, payload: dict, timeout: float = 600.0) -> dict:
    url = f"http://127.0.0.1:{OLLAMA_PORT}{path}"
    data = json.dumps(payload).encode()
    req = urlrequest.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore").strip()
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # Algunos endpoints pueden devolver NDJSON/stream; nos quedamos con la última línea JSON.
        last_json = {}
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                last_json = json.loads(line)
            except Exception:
                continue
        return last_json


def ollama_list_models():
    if not _ensure_ollama_up():
        return {"ok": False, "message": "Ollama no está disponible."}
    try:
        data = ollama_api_get("/api/tags")
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return {"ok": True, "models": sorted(models)}
    except Exception as exc:
        return {"ok": False, "message": f"Error listando modelos: {exc}"}


def ollama_pull_model(model_name: str):
    if not _ensure_ollama_up():
        return {"ok": False, "message": "Ollama no está disponible."}
    if not model_name:
        return {"ok": False, "message": "Falta el nombre del modelo."}
    try:
        ollama_api_post(
            "/api/pull", {"name": model_name, "stream": False}, timeout=1800.0
        )
        return {"ok": True, "message": f"Modelo descargado: {model_name}"}
    except Exception as exc:
        return {"ok": False, "message": f"Error en pull: {exc}"}


def ollama_create_custom_model(model_name: str, base_model: str, system_prompt: str):
    if not _ensure_ollama_up():
        return {"ok": False, "message": "Ollama no está disponible."}
    if not model_name or not base_model:
        return {"ok": False, "message": "model_name y base_model son obligatorios."}
    modelfile = f"FROM {base_model}\n"
    if system_prompt:
        escaped = system_prompt.replace('"""', '\\"\\"\\"')
        modelfile += f'SYSTEM """{escaped}"""\n'
    try:
        ollama_api_post(
            "/api/create",
            {"name": model_name, "modelfile": modelfile, "stream": False},
            timeout=1800.0,
        )
        return {"ok": True, "message": f"Modelo custom creado: {model_name}"}
    except Exception as exc:
        return {"ok": False, "message": f"Error creando modelo custom: {exc}"}


def _parse_modelfile_preset(path: Path):
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None

    base_model = ""
    m_from = re.search(r"^\s*FROM\s+(.+?)\s*$", raw, flags=re.MULTILINE)
    if m_from:
        base_model = m_from.group(1).strip()

    system_prompt = ""
    m_system = re.search(r"SYSTEM\s+\"\"\"(.*?)\"\"\"", raw, flags=re.DOTALL)
    if m_system:
        system_prompt = m_system.group(1).strip()

    if not system_prompt:
        return None

    return {
        "id": path.name,
        "name": path.name.replace("-", " ").title(),
        "base_model": base_model,
        "system_prompt": system_prompt,
    }


def load_ollama_prompt_presets():
    # Evitamos cargar presets con contenido explícito no apto para uso general del panel.
    allowed_files = [
        "security-auditor",
        "python-expert",
        "devops-expert",
        "voice-assistant",
    ]
    presets = []
    for fname in allowed_files:
        p = OLLAMA_MODELFILES_DIR / fname
        if not p.exists() or not p.is_file():
            continue
        parsed = _parse_modelfile_preset(p)
        if parsed:
            presets.append(parsed)
    return presets


def _extract_character_name(raw: str, fallback: str) -> str:
    m = re.search(r"^#\s*Character\s+AI\s+Prompt\s*:\s*(.+?)\s*$", raw, flags=re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return fallback.replace("_", " ").replace("-", " ").title()


def load_character_prompt_presets():
    presets = []
    root = CHARACTER_PROFILES_DIR
    if not root.exists() or not root.is_dir():
        return presets

    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        profile_md = p / "profile.md"
        stable_prompt = p / "stable_diffusion_prompt.txt"

        raw = ""
        if profile_md.exists() and profile_md.is_file():
            try:
                raw = profile_md.read_text(encoding="utf-8").strip()
            except Exception:
                raw = ""

        # Fallback por si profile.md está vacío o ausente.
        if not raw and stable_prompt.exists() and stable_prompt.is_file():
            try:
                raw = stable_prompt.read_text(encoding="utf-8").strip()
            except Exception:
                raw = ""

        if not raw:
            continue

        presets.append(
            {
                "id": p.name,
                "name": _extract_character_name(raw, p.name),
                "system_prompt": raw,
            }
        )

    return presets


def load_character_video_prompt_presets():
    presets = []
    root = CHARACTER_PROFILES_DIR
    if not root.exists() or not root.is_dir():
        return presets

    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue

        profile_md = p / "profile.md"
        stable_prompt = p / "stable_diffusion_prompt.txt"

        prompt_text = ""
        if stable_prompt.exists() and stable_prompt.is_file():
            try:
                prompt_text = stable_prompt.read_text(encoding="utf-8").strip()
            except Exception:
                prompt_text = ""

        if not prompt_text and profile_md.exists() and profile_md.is_file():
            try:
                prompt_text = profile_md.read_text(encoding="utf-8").strip()
            except Exception:
                prompt_text = ""

        if not prompt_text:
            continue

        name_source = ""
        if profile_md.exists() and profile_md.is_file():
            try:
                name_source = profile_md.read_text(encoding="utf-8")
            except Exception:
                name_source = ""

        positive_prompt = prompt_text
        negative_prompt = ""

        m_pos = re.search(
            r"POSITIVE\s+PROMPT\s*:\s*[-=\s]*\n(.*?)(?:\n\s*NEGATIVE\s+PROMPT(?:\s*\([^)]*\))?\s*:|\Z)",
            prompt_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_pos:
            positive_prompt = m_pos.group(1).strip()

        m_neg = re.search(
            r"NEGATIVE\s+PROMPT(?:\s*\([^)]*\))?\s*:\s*[-=\s]*\n(.*)$",
            prompt_text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if m_neg:
            negative_prompt = m_neg.group(1).strip()

        presets.append(
            {
                "id": p.name,
                "name": _extract_character_name(name_source or prompt_text, p.name),
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
            }
        )

    return presets


def get_character_video_prompt_preset(preset_id: str):
    if not preset_id:
        return None
    for p in load_character_video_prompt_presets():
        if p.get("id") == preset_id:
            return p
    return None


def _find_character_reference_wav(char_dir: Path) -> str:
    if not char_dir.exists() or not char_dir.is_dir():
        return ""
    candidates = [
        char_dir / "voice.wav",
        char_dir / "reference.wav",
        char_dir / "sample.wav",
    ]
    for p in candidates:
        if p.exists() and p.is_file():
            return str(p)
    for p in sorted(char_dir.glob("*.wav")):
        if p.is_file():
            return str(p)
    return ""


def load_game_tts_character_presets():
    presets = []
    root = CHARACTER_PROFILES_DIR
    if root.exists() and root.is_dir():
        for p in sorted(root.iterdir()):
            if not p.is_dir():
                continue
            presets.append(
                {
                    "id": p.name,
                    "name": p.name.replace("_", " ").replace("-", " ").title(),
                    "speaker_wav": _find_character_reference_wav(p),
                }
            )
    if not presets:
        presets = [
            {"id": "hero", "name": "Hero", "speaker_wav": ""},
            {"id": "villain", "name": "Villain", "speaker_wav": ""},
            {"id": "narrator", "name": "Narrator", "speaker_wav": ""},
        ]
    return presets


def list_piper_models():
    models = []
    piper_dir = AI_DIR / "piper"
    if not piper_dir.exists() or not piper_dir.is_dir():
        return models

    for p in sorted(piper_dir.glob("*.onnx")):
        if not p.is_file():
            continue
        model_id = p.name
        models.append(
            {
                "id": model_id,
                "name": p.stem.replace("_", " "),
                "path": str(p),
                "config_path": str(Path(f"{p}.json")),
            }
        )
    return models


def get_piper_model_by_id(model_id: str):
    if not model_id:
        return None
    for m in list_piper_models():
        if m.get("id") == model_id:
            return m
    return None


def get_game_tts_piper_recommendations():
    # Character -> preferred model ids ordered by priority.
    preferred = {
        "akika": ["en_GB-cori-high.onnx", "en_US-ljspeech-high.onnx"],
        "kaede": ["en_GB-alba-medium.onnx", "en_US-amy-medium.onnx"],
        "kuro": ["en_GB-jenny_dioco-medium.onnx", "en_GB-cori-high.onnx"],
        "hinata": ["en_US-amy-medium.onnx", "en_GB-alba-medium.onnx"],
    }

    available = {m.get("id") for m in list_piper_models()}
    resolved = {}
    for character_id, candidates in preferred.items():
        chosen = ""
        for c in candidates:
            if c in available:
                chosen = c
                break
        if chosen:
            resolved[character_id] = chosen
    return resolved


def get_game_tts_personality(preset_id: str):
    for preset in GAME_TTS_PERSONALITY_PRESETS:
        if preset.get("id") == preset_id:
            return preset
    return GAME_TTS_PERSONALITY_PRESETS[0]


def _styled_tts_text(text: str, pauses: str = "medium") -> str:
    t = (text or "").strip()
    if not t:
        return ""
    if pauses == "long":
        t = re.sub(r",\s*", ", ... ", t)
        t = re.sub(r"\.\s*", ". ... ", t)
    elif pauses == "short":
        t = re.sub(r",\s*", ", ", t)
        t = re.sub(r"\.\s*", ". ", t)
    return t


def _game_tts_filename(character_id: str, personality_id: str, text: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    text_slug = slugify_text(text, max_len=24) or "line"
    base = f"game_tts_{character_id}_{personality_id}_{ts}_{text_slug}.wav"
    return slugify_text(base.replace(".wav", ""), max_len=110) + ".wav"


def _get_xtts_model():
    global _xtts_model_cache
    if _xtts_model_cache is not None:
        return _xtts_model_cache
    try:
        tts_module = importlib.import_module("TTS.api")
        TTS = getattr(tts_module, "TTS")
    except Exception as exc:
        raise RuntimeError("XTTS no disponible. Instala con: pip install TTS") from exc

    model = TTS(XTTS_MODEL_NAME)
    try:
        import torch

        if torch.cuda.is_available():
            model = model.to("cuda")
    except Exception:
        pass

    _xtts_model_cache = model
    return _xtts_model_cache


def _run_xtts_external(
    speaker_wav: str, language: str, text: str, out_path: Path, speed: float
) -> dict[str, Any]:
    py = Path(XTTS_PYTHON)
    if not py.exists():
        return {
            "ok": False,
            "message": (
                "XTTS no disponible en runtime actual y no existe XTTS_PYTHON. "
                "Configura XTTS_PYTHON o usa Piper."
            ),
        }

    script = r'''
import sys
from TTS.api import TTS

speaker_wav = sys.argv[1]
language = sys.argv[2]
text = sys.argv[3]
out_path = sys.argv[4]
speed = float(sys.argv[5])
model_name = sys.argv[6]

tts = TTS(model_name)
kwargs = {
    "text": text,
    "speaker_wav": speaker_wav,
    "language": language,
    "file_path": out_path,
}
if "speed" in tts.tts_to_file.__code__.co_varnames:
    kwargs["speed"] = speed
tts.tts_to_file(**kwargs)
'''

    proc = subprocess.run(
        [
            str(py),
            "-c",
            script,
            speaker_wav,
            language,
            text,
            str(out_path),
            f"{speed:.3f}",
            XTTS_MODEL_NAME,
        ],
        text=True,
        capture_output=True,
        env={**os.environ, "COQUI_TOS_AGREED": "1"},
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return {"ok": False, "message": f"Error XTTS externo: {err or 'fallo desconocido'}"}
    return {"ok": True}


def generate_game_tts(
    engine: str,
    character: dict,
    personality: dict,
    text: str,
    language: str,
    piper_model_path: str = "",
) -> dict[str, Any]:
    ensure_dir(VOICE_OUT_DIR)

    style_text = _styled_tts_text(text, pauses=personality.get("pauses", "medium"))
    out_name = _game_tts_filename(
        character.get("id", "character"), personality.get("id", "preset"), text
    )
    out_path = VOICE_OUT_DIR / out_name

    speed = float(personality.get("speed", 1.0) or 1.0)

    if engine == "piper":
        piper_bin = Path(PIPER_BIN)
        if not piper_bin.exists():
            return {
                "ok": False,
                "message": (
                    "Piper CLI no encontrado en ruta esperada. "
                    f"Configura PIPER_BIN (actual: {PIPER_BIN})"
                ),
            }

        model_path = Path((piper_model_path or "").strip() or PIPER_MODEL_PATH)
        if not model_path.exists():
            return {
                "ok": False,
                "message": f"Modelo Piper no encontrado: {model_path}",
            }
        cmd = [str(piper_bin), "--model", str(model_path), "--output_file", str(out_path)]
        cfg_path = Path(f"{model_path}.json")
        if not cfg_path.exists() and model_path == Path(PIPER_MODEL_PATH):
            cfg_path = Path(PIPER_CONFIG_PATH)
        if cfg_path.exists():
            cmd.extend(["--config", str(cfg_path)])

        length_scale = 1.0 / max(0.2, speed)
        cmd.extend(["--length_scale", f"{length_scale:.3f}"])

        proc = subprocess.run(
            cmd,
            input=style_text,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return {
                "ok": False,
                "message": f"Error Piper: {err or 'fallo desconocido'}",
            }

    elif engine == "xtts":
        speaker_wav = (character.get("speaker_wav") or "").strip()
        if not speaker_wav or not Path(speaker_wav).exists():
            return {
                "ok": False,
                "message": (
                    "XTTS necesita una referencia de voz WAV por personaje. "
                    "Añade voice.wav en la carpeta del personaje."
                ),
            }

        try:
            xtts = _get_xtts_model()
            kwargs = {
                "text": style_text,
                "speaker_wav": speaker_wav,
                "language": language,
                "file_path": str(out_path),
            }
            sig = inspect.signature(xtts.tts_to_file)
            if "speed" in sig.parameters:
                kwargs["speed"] = speed
            xtts.tts_to_file(**kwargs)
        except Exception as exc:
            log.warning("XTTS en proceso actual no disponible: %s. Probando XTTS_PYTHON...", exc)
            ext = _run_xtts_external(
                speaker_wav=speaker_wav,
                language=language,
                text=style_text,
                out_path=out_path,
                speed=speed,
            )
            if not ext.get("ok"):
                return ext
    else:
        return {"ok": False, "message": f"Motor no soportado: {engine}"}

    if not out_path.exists():
        return {"ok": False, "message": "No se generó el audio de salida."}

    return {
        "ok": True,
        "path": str(out_path),
        "filename": out_name,
        "audio_url": f"/tools/game-tts/audio/{out_name}",
        "engine": engine,
        "piper_model": model_path.name if engine == "piper" else "",
    }


# --- WORKFLOWS ----------------------------------------------------------------
def patch_api_workflow(
    workflow,
    positive,
    negative,
    checkpoint,
    width,
    height,
    frames,
    fps,
    steps,
    cfg,
    denoise,
    crf,
    pix_fmt,
    seed,
    output_prefix,
    wan_model=None,
    shift=5.0,
    text_encoder=None,
    vae=None,
):
    wf = json.loads(json.dumps(workflow))
    ct_map = {}
    for nid, node in wf.items():
        if isinstance(node, dict):
            ct = node.get("class_type", "")
            ct_map.setdefault(ct, []).append(nid)

    def patch_node(ct, updates):
        for nid in ct_map.get(ct, []):
            wf[nid]["inputs"].update(updates)

    if checkpoint:
        patch_node("CheckpointLoaderSimple", {"ckpt_name": checkpoint})

    for nid in ct_map.get("KSampler", []) + ct_map.get("KSamplerAdvanced", []):
        node = wf[nid]
        p_ref = node["inputs"].get("positive")
        n_ref = node["inputs"].get("negative")
        if isinstance(p_ref, list) and len(p_ref) == 2:
            pos_nid = str(p_ref[0])
            if pos_nid in wf and wf[pos_nid].get("class_type") == "CLIPTextEncode":
                wf[pos_nid]["inputs"]["text"] = positive
        if isinstance(n_ref, list) and len(n_ref) == 2:
            neg_nid = str(n_ref[0])
            if neg_nid in wf and wf[neg_nid].get("class_type") == "CLIPTextEncode":
                wf[neg_nid]["inputs"]["text"] = negative
        node["inputs"].update(
            {"steps": steps, "cfg": cfg, "seed": seed, "denoise": denoise}
        )

    patch_node(
        "EmptyLatentImage", {"width": width, "height": height, "batch_size": frames}
    )
    for ct in ("ADE_AnimateDiffLoaderWithContext", "ADE_AnimateDiffLoaderGen1"):
        patch_node(ct, {"context_length": frames})
    patch_node(
        "VHS_VideoCombine",
        {
            "frame_rate": fps,
            "crf": crf,
            "pix_fmt": pix_fmt,
            "filename_prefix": output_prefix,
        },
    )

    if wan_model:
        patch_node("WanVideoModelLoader", {"model": wan_model})
    patch_node(
        "WanVideoSampler", {"shift": shift, "steps": steps, "cfg": cfg, "seed": seed}
    )
    if text_encoder:
        patch_node("LoadWanVideoT5TextEncoder", {"model_name": text_encoder})
    if vae:
        patch_node("WanVideoVAELoader", {"model_name": vae})
    patch_node(
        "WanVideoTextEncode", {"positive_prompt": positive, "negative_prompt": negative}
    )
    patch_node(
        "WanVideoEmptyEmbeds", {"width": width, "height": height, "num_frames": frames}
    )

    return wf


# --- VIDEO SDXL ---------------------------------------------------------------
def get_video_preset(preset_id):
    for p in VIDEO_MODEL_PRESETS:
        if p["id"] == preset_id:
            return p
    return VIDEO_MODEL_PRESETS[0]


def get_smooth_profile(profile_id):
    for p in VIDEO_SMOOTH_PROFILES:
        if p["id"] == profile_id:
            return p
    return VIDEO_SMOOTH_PROFILES[0]


def find_checkpoint(include_token):
    ckpt_dir = COMFY_DIR / "models" / "checkpoints"
    if not ckpt_dir.exists():
        return None
    token_lower = include_token.lower()
    for f in ckpt_dir.iterdir():
        if token_lower in f.name.lower():
            return f.name
    return None


def resolve_checkpoint_name(obj_info: dict, preset: dict) -> str:
    ckpt_options = get_node_input_options(
        obj_info, "CheckpointLoaderSimple", "ckpt_name"
    )
    if not ckpt_options:
        return preset["checkpoint"]

    wanted = preset.get("checkpoint", "")
    if wanted in ckpt_options:
        return wanted
    wanted_lower = wanted.lower()
    for ck in ckpt_options:
        if ck.lower() == wanted_lower:
            return ck

    include_token = preset.get("include_token", "").lower()
    if include_token:
        for ck in ckpt_options:
            if include_token in ck.lower():
                return ck

    return ckpt_options[0]


def resolve_animatediff_motion(obj_info: dict, checkpoint_name: str = ""):
    node_name = "ADE_AnimateDiffLoaderWithContext"
    if node_name not in obj_info:
        node_name = "ADE_AnimateDiffLoaderGen1"
    model_options = get_node_input_options(obj_info, node_name, "model_name")
    beta_options = get_node_input_options(obj_info, node_name, "beta_schedule")

    model_name = ""
    if model_options:
        ckpt_lower = checkpoint_name.lower()

        # Si el checkpoint es SDXL, forzamos motion model SDXL.
        if "sdxl" in ckpt_lower or "xl" in ckpt_lower:
            for preferred in ("mm_sdxl_v10_beta.ckpt", "mm_sdxl_v10_beta.safetensors"):
                if preferred in model_options:
                    model_name = preferred
                    break
            if not model_name:
                for m in model_options:
                    if "sdxl" in m.lower():
                        model_name = m
                        break

        if not model_name:
            model_name = model_options[0]

    beta_schedule = "autoselect"
    if beta_options and beta_schedule not in beta_options:
        beta_schedule = beta_options[0]

    return model_name, beta_schedule


def default_video_form():
    profile = VIDEO_SMOOTH_PROFILES[0]
    return {
        "model_preset": VIDEO_MODEL_PRESETS[0]["id"],
        "smooth_profile": profile["id"],
        "positive_prompt": "",
        "negative_prompt": "worst quality, low quality, lowres, blurry, deformed, watermark",
        "width": profile["width"],
        "height": profile["height"],
        "frames": profile["frames"],
        "fps": profile["fps"],
        "steps": profile["steps"],
        "cfg": profile["cfg"],
        "denoise": profile["denoise"],
        "crf": profile["crf"],
        "pix_fmt": profile["pix_fmt"],
        "seed": random.randint(0, 2**31),
    }


def build_video_prompt(
    checkpoint,
    motion_model,
    beta_schedule,
    positive,
    negative,
    width,
    height,
    frames,
    fps,
    steps,
    cfg,
    denoise,
    crf,
    pix_fmt,
    seed,
    output_prefix,
):
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": frames},
        },
        "5": {
            "class_type": "ADE_AnimateDiffLoaderWithContext",
            "inputs": {
                "model": ["1", 0],
                "model_name": motion_model,
                "beta_schedule": beta_schedule,
            },
        },
        "6": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["5", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "karras",
                "denoise": denoise,
            },
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["6", 0], "vae": ["1", 2]},
        },
        "8": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["7", 0],
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": output_prefix,
                "format": "video/h264-mp4",
                "pix_fmt": pix_fmt,
                "crf": crf,
                "save_metadata": True,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def build_video_prompt_evolved(
    checkpoint,
    motion_model,
    beta_schedule,
    positive,
    negative,
    width,
    height,
    frames,
    fps,
    steps,
    cfg,
    denoise,
    crf,
    pix_fmt,
    seed,
    output_prefix,
):
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": frames},
        },
        "5": {
            "class_type": "ADE_LoadAnimateDiffModel",
            "inputs": {"model_name": motion_model, "ad_settings": None},
        },
        "6": {
            "class_type": "ADE_ApplyAnimateDiffModelSimple",
            "inputs": {
                "motion_model": ["5", 0],
                "motion_lora": None,
                "scale_multival": None,
                "effect_multival": None,
                "ad_keyframes": None,
                "per_block": None,
            },
        },
        "7": {
            "class_type": "ADE_UseEvolvedSampling",
            "inputs": {
                "model": ["1", 0],
                "m_models": ["6", 0],
                "context_options": None,
                "sample_settings": None,
                "beta_schedule": beta_schedule,
            },
        },
        "8": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["7", 0],
                "positive": ["2", 0],
                "negative": ["3", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": denoise,
            },
        },
        "9": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["8", 0], "vae": ["1", 2]},
        },
        "10": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["9", 0],
                "audio": None,
                "meta_batch": None,
                "vae": None,
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": output_prefix,
                "format": "video/h264-mp4",
                "pix_fmt": pix_fmt,
                "crf": crf,
                "save_metadata": True,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def submit_video_scene(form_data):
    log.info(
        "video-scene submit: character_preset=%s positive_len=%s negative_len=%s",
        form_data.get("character_preset", ""),
        len((form_data.get("positive_prompt", "") or "").strip()),
        len((form_data.get("negative_prompt", "") or "").strip()),
    )
    if not port_open(COMFY_PORT):
        comfy_start()
        for _ in range(20):
            if port_open(COMFY_PORT):
                break
            time.sleep(0.5)
    if not port_open(COMFY_PORT):
        return {"ok": False, "message": "ComfyUI no está disponible."}

    preset = get_video_preset(form_data.get("model_preset", "wai_nsfw"))
    profile = get_smooth_profile(form_data.get("smooth_profile", "cinematic_stable"))

    width = clamp_step(int(form_data.get("width", profile["width"])), 256, 1280, 8)
    height = clamp_step(int(form_data.get("height", profile["height"])), 256, 1280, 8)
    frames = clamp_step(int(form_data.get("frames", profile["frames"])), 8, 64, 4)
    fps = clamp_step(int(form_data.get("fps", profile["fps"])), 4, 30, 1)
    steps = clamp_step(int(form_data.get("steps", profile["steps"])), 10, 50, 1)
    cfg = max(1.0, min(15.0, float(form_data.get("cfg", profile["cfg"]))))
    denoise = max(0.1, min(1.0, float(form_data.get("denoise", profile["denoise"]))))
    crf = clamp_step(int(form_data.get("crf", profile["crf"])), 14, 28, 1)
    pix_fmt = form_data.get("pix_fmt", "yuv420p")
    seed_raw = int(form_data.get("seed", -1))
    seed = random.randint(0, 2**31) if seed_raw < 0 else seed_raw
    character_preset_id = form_data.get("character_preset", "").strip()
    positive = form_data.get("positive_prompt", "").strip()
    negative = form_data.get("negative_prompt", "").strip()

    if character_preset_id:
        cp = get_character_video_prompt_preset(character_preset_id)
        if cp:
            if not positive:
                positive = (cp.get("positive_prompt") or "").strip()
            if not negative:
                negative = (cp.get("negative_prompt") or "").strip()
            log.info(
                "video-scene fallback applied: character_preset=%s positive_len=%s negative_len=%s",
                character_preset_id,
                len(positive),
                len(negative),
            )

    if not positive:
        return {"ok": False, "message": "El prompt positivo no puede estar vacío."}

    obj_info = get_comfy_object_info()
    checkpoint = resolve_checkpoint_name(obj_info, preset)
    motion_model, beta_schedule = resolve_animatediff_motion(obj_info, checkpoint)
    if not motion_model:
        return {
            "ok": False,
            "message": "No hay motion model de AnimateDiff cargado en ComfyUI (ADE model_name vacío).",
        }
    if ("sdxl" in checkpoint.lower() or "xl" in checkpoint.lower()) and (
        "sdxl" not in motion_model.lower()
    ):
        return {
            "ok": False,
            "message": (
                "Checkpoint SDXL detectado pero no hay motion model SDXL compatible en AnimateDiff. "
                "Instala/carga mm_sdxl_v10_beta (.ckpt o .safetensors) y reinicia ComfyUI."
            ),
        }
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_prefix = f"video_output/{timestamp}_{slugify_text(positive)[:48]}"

    workflow_file = None
    prompt = None
    workflow_variant = "legacy"

    has_evolved = all(
        n in obj_info
        for n in (
            "ADE_LoadAnimateDiffModel",
            "ADE_ApplyAnimateDiffModelSimple",
            "ADE_UseEvolvedSampling",
        )
    )
    if USE_EXTERNAL_WORKFLOW_FILES:
        for fname in (f"{preset['id']}_video_api.json", "animatediff_video_api.json"):
            p = WORKFLOWS_DIR / fname
            if p.exists():
                try:
                    api_wf = json.loads(p.read_text(encoding="utf-8"))
                    prompt = patch_api_workflow(
                        api_wf,
                        positive,
                        negative,
                        checkpoint,
                        width,
                        height,
                        frames,
                        fps,
                        steps,
                        cfg,
                        denoise,
                        crf,
                        pix_fmt,
                        seed,
                        output_prefix,
                    )
                    workflow_file = fname
                    break
                except Exception:
                    continue

    if prompt is None:
        if has_evolved:
            prompt = build_video_prompt_evolved(
                checkpoint=checkpoint,
                motion_model=motion_model,
                beta_schedule=beta_schedule,
                positive=positive,
                negative=negative,
                width=width,
                height=height,
                frames=frames,
                fps=fps,
                steps=steps,
                cfg=cfg,
                denoise=denoise,
                crf=crf,
                pix_fmt=pix_fmt,
                seed=seed,
                output_prefix=output_prefix,
            )
            workflow_variant = "evolved"
        else:
            prompt = build_video_prompt(
                checkpoint=checkpoint,
                motion_model=motion_model,
                beta_schedule=beta_schedule,
                positive=positive,
                negative=negative,
                width=width,
                height=height,
                frames=frames,
                fps=fps,
                steps=steps,
                cfg=cfg,
                denoise=denoise,
                crf=crf,
                pix_fmt=pix_fmt,
                seed=seed,
                output_prefix=output_prefix,
            )

    try:
        response = comfy_api_post("/prompt", {"prompt": prompt})
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            err_body = json.loads(raw)
            err = err_body.get("error", {})
            msg = err.get("message", exc.reason)
            detail = err.get("details", "")
            node_errors = err_body.get("node_errors", {})
            if node_errors:
                node_msgs = []
                for nid, v in node_errors.items():
                    cls = v.get("class_type", nid)
                    errs = v.get("errors", [])
                    if errs:
                        first = errs[0]
                        node_msgs.append(
                            f"{cls}: {first.get('details') or first.get('message')}"
                        )
                if node_msgs:
                    msg = " ; ".join(node_msgs[:3])
            full = f"HTTP {exc.code}: {msg}"
            if detail and detail not in full:
                full += f" ({detail})"
        except Exception:
            full = f"HTTP {exc.code}: {raw or exc.reason}"
        return {"ok": False, "message": full}
    except Exception as exc:
        return {"ok": False, "message": f"Error enviando a ComfyUI: {exc}"}

    prompt_id = response.get("prompt_id")
    if not prompt_id:
        return {"ok": False, "message": f"ComfyUI no aceptó el prompt: {response}"}
    return {
        "ok": True,
        "message": "Vídeo encolado en ComfyUI.",
        "prompt_id": prompt_id,
        "output_prefix": output_prefix,
        "workflow_mode": "external" if workflow_file else workflow_variant,
        "workflow_file": workflow_file,
        "used_checkpoint": checkpoint,
        "used_motion_model": motion_model,
        "used_denoise": denoise,
        "used_positive_prompt": positive,
    }


# --- WAN2.1 -------------------------------------------------------------------
def get_wan_preset(preset_id):
    for p in WAN_MODEL_PRESETS:
        if p["id"] == preset_id:
            return p
    return WAN_MODEL_PRESETS[0]


def get_wan_profile(profile_id):
    for p in WAN_VIDEO_PROFILES:
        if p["id"] == profile_id:
            return p
    return WAN_VIDEO_PROFILES[0]


def _resolve_comfy_option(obj_info: dict, node: str, key: str, wanted: str) -> str:
    options = get_node_input_options(obj_info, node, key)
    if not options:
        return wanted
    if wanted in options:
        return wanted
    wanted_lower = wanted.lower()
    for opt in options:
        if opt.lower() == wanted_lower:
            return opt
    return options[0]


def resolve_wan_model_name(obj_info: dict, preset: dict) -> str:
    options = get_node_input_options(obj_info, "WanVideoModelLoader", "model")
    wanted = preset.get("model", "")
    if not options:
        return wanted

    # Preferimos modelo T2V 1.3B base (no Lumen/Fun) para evitar mismatch de canales.
    for opt in options:
        low = opt.lower()
        if "t2v" in low and "1_3b" in low and "lumen" not in low and "fun/" not in low:
            return opt

    if wanted in options:
        return wanted
    wanted_lower = wanted.lower()
    for opt in options:
        if opt.lower() == wanted_lower:
            return opt

    for opt in options:
        low = opt.lower()
        if "lumen" not in low and "fun/" not in low:
            return opt

    return options[0]


def resolve_wan_i2v_model_name(obj_info: dict, preferred: str = "") -> str:
    options = get_node_input_options(obj_info, "WanVideoModelLoader", "model")
    if not options:
        return preferred

    if preferred:
        for opt in options:
            if opt == preferred and "i2v" in opt.lower():
                return opt

    i2v_options = [opt for opt in options if "i2v" in opt.lower()]
    if i2v_options:
        preferred_low = preferred.lower()
        # Respect preset scale whenever possible: 14B preset -> I2V 14B, 1.3B preset -> I2V 1.3B.
        if "14b" in preferred_low:
            for opt in i2v_options:
                if "14b" in opt.lower():
                    return opt
        if "1_3b" in preferred_low or "1.3b" in preferred_low:
            for opt in i2v_options:
                low = opt.lower()
                if "1_3b" in low or "1.3b" in low:
                    return opt

        # Prefer non-Lumen/Fun variants when available for a predictable baseline.
        for opt in i2v_options:
            low = opt.lower()
            if "lumen" not in low and "fun/" not in low:
                return opt
        return i2v_options[0]

    return ""


def default_wan_form():
    profile = WAN_VIDEO_PROFILES[0]
    return {
        "model_preset": WAN_MODEL_PRESETS[0]["id"],
        "video_profile": profile["id"],
        "positive_prompt": "",
        "negative_prompt": "worst quality, low quality, lowres, blurry, deformed, watermark",
        "width": profile["width"],
        "height": profile["height"],
        "frames": profile["frames"],
        "fps": profile["fps"],
        "steps": profile["steps"],
        "cfg": profile["cfg"],
        "shift": profile["shift"],
        "crf": profile["crf"],
        "pix_fmt": profile["pix_fmt"],
        "seed": random.randint(0, 2**31),
    }


def default_wan_i2v_form():
    f = default_wan_form()
    imgs = list_comfy_input_images()
    f["image_name"] = imgs[0] if imgs else ""
    return f


def list_comfy_input_images():
    input_dir = COMFY_DIR / "input"
    if not input_dir.exists() or not input_dir.is_dir():
        return []

    exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    files = []
    for p in sorted(input_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in exts:
            continue
        rel = p.relative_to(input_dir).as_posix()
        if rel.startswith("."):
            continue
        files.append(rel)
    return files


def _patch_workflow_image_input(prompt: dict, image_name: str) -> bool:
    patched = False
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        if ct in ("LoadImage", "LoadImageMask", "VHS_LoadImagePath"):
            for k in ("image", "filename", "path"):
                if k in inputs:
                    inputs[k] = image_name
                    patched = True

    return patched


def submit_wan_i2v_scene(form_data):
    if not port_open(COMFY_PORT):
        comfy_start()
        for _ in range(20):
            if port_open(COMFY_PORT):
                break
            time.sleep(0.5)
    if not port_open(COMFY_PORT):
        return {"ok": False, "message": "ComfyUI no está disponible."}

    image_name = (form_data.get("image_name", "") or "").strip()
    if not image_name:
        return {
            "ok": False,
            "message": "Indica image_name (archivo en ComfyUI/input), por ejemplo: akika_base.png",
        }

    preset = get_wan_preset(form_data.get("model_preset", "wan_1b"))
    profile = get_wan_profile(form_data.get("video_profile", "portrait_fast"))
    width = clamp_step(int(form_data.get("width", profile["width"])), 256, 1280, 8)
    height = clamp_step(int(form_data.get("height", profile["height"])), 256, 1280, 8)
    frames = clamp_step(int(form_data.get("frames", profile["frames"])), 8, 121, 1)
    fps = clamp_step(int(form_data.get("fps", profile["fps"])), 4, 30, 1)
    steps = clamp_step(int(form_data.get("steps", profile["steps"])), 10, 50, 1)
    cfg = max(1.0, min(15.0, float(form_data.get("cfg", profile["cfg"]))))
    shift = max(1.0, min(20.0, float(form_data.get("shift", profile["shift"]))))
    crf = clamp_step(int(form_data.get("crf", profile["crf"])), 14, 28, 1)
    pix_fmt = form_data.get("pix_fmt", "yuv420p")
    seed_raw = int(form_data.get("seed", -1))
    seed = random.randint(0, 2**31) if seed_raw < 0 else seed_raw
    positive = (form_data.get("positive_prompt", "") or "").strip()
    negative = (form_data.get("negative_prompt", "") or "").strip()

    if not positive:
        return {"ok": False, "message": "El prompt positivo no puede estar vacío."}

    obj_info = get_comfy_object_info()
    wan_model = resolve_wan_i2v_model_name(obj_info, preset.get("model", ""))
    if not wan_model:
        available = get_node_input_options(obj_info, "WanVideoModelLoader", "model")
        return {
            "ok": False,
            "message": (
                "No hay modelos I2V instalados en WanVideoModelLoader. "
                "Ahora mismo solo se detectan modelos T2V. "
                "Instala un checkpoint Wan I2V y reinicia ComfyUI. "
                f"Modelos detectados: {', '.join(available[:6]) if available else '(ninguno)'}"
            ),
        }
    text_encoder = _resolve_comfy_option(
        obj_info,
        "LoadWanVideoT5TextEncoder",
        "model_name",
        preset["text_encoder"],
    )
    vae = _resolve_comfy_option(
        obj_info,
        "WanVideoVAELoader",
        "model_name",
        preset["vae"],
    )

    workflow_file = None
    for fname in ("wan_i2v_api.json", "wan_i2v.json"):
        p = WORKFLOWS_DIR / fname
        if p.exists():
            workflow_file = p
            break

    if workflow_file is None:
        return {
            "ok": False,
            "message": (
                "No existe workflow API I2V. Exporta uno desde ComfyUI como "
                "wan_i2v_api.json en ComfyUI/workflows/."
            ),
        }

    try:
        api_wf = json.loads(workflow_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "message": f"Error leyendo {workflow_file.name}: {exc}"}

    output_prefix = f"wan_i2v/{time.strftime('%Y%m%d_%H%M%S')}_{slugify_text(positive)[:42]}"

    prompt = patch_api_workflow(
        api_wf,
        positive,
        negative,
        checkpoint="",
        width=width,
        height=height,
        frames=frames,
        fps=fps,
        steps=steps,
        cfg=cfg,
        denoise=1.0,
        crf=crf,
        pix_fmt=pix_fmt,
        seed=seed,
        output_prefix=output_prefix,
        wan_model=wan_model,
        shift=shift,
        text_encoder=text_encoder,
        vae=vae,
    )

    if not _patch_workflow_image_input(prompt, image_name):
        return {
            "ok": False,
            "message": (
                f"El workflow {workflow_file.name} no tiene nodo de imagen compatible "
                "(LoadImage/LoadImageMask/VHS_LoadImagePath)."
            ),
        }

    try:
        response = comfy_api_post("/prompt", {"prompt": prompt})
    except Exception as exc:
        return {"ok": False, "message": f"Error enviando a ComfyUI: {exc}"}

    prompt_id = response.get("prompt_id")
    if not prompt_id:
        return {"ok": False, "message": f"ComfyUI no aceptó el prompt: {response}"}

    return {
        "ok": True,
        "message": "Escena Wan I2V encolada en ComfyUI.",
        "prompt_id": prompt_id,
        "output_prefix": output_prefix,
        "workflow_file": workflow_file.name,
        "used_image": image_name,
        "used_model": wan_model,
        "used_positive_prompt": positive,
    }


def build_wan_prompt(
    wan_model,
    text_encoder,
    vae,
    positive,
    negative,
    width,
    height,
    frames,
    fps,
    steps,
    cfg,
    crf,
    pix_fmt,
    seed,
    shift,
    output_prefix,
):
    """Workflow built-in para Wan2.1 T2V usando ComfyUI-WanVideoWrapper (kijai).
    Nodos verificados contra nodes_model_loading.py + nodes.py + nodes_sampler.py.
    Paths: diffusion_models/ | text_encoders/ | vae/
    """
    return {
        "1": {
            "class_type": "WanVideoModelLoader",
            "inputs": {
                "model": wan_model,
                "base_precision": "bf16",
                "quantization": "disabled",
                "load_device": "offload_device",
            },
        },
        "2": {
            "class_type": "LoadWanVideoT5TextEncoder",
            "inputs": {
                "model_name": text_encoder,
                "precision": "bf16",
                "load_device": "offload_device",
                "quantization": "disabled",
            },
        },
        "3": {
            "class_type": "WanVideoVAELoader",
            "inputs": {
                "model_name": vae,
                "precision": "bf16",
            },
        },
        "4": {
            "class_type": "WanVideoTextEncode",
            "inputs": {
                "positive_prompt": positive,
                "negative_prompt": negative,
                "t5": ["2", 0],
                "force_offload": True,
            },
        },
        "5": {
            "class_type": "WanVideoEmptyEmbeds",
            "inputs": {
                "width": width,
                "height": height,
                "num_frames": frames,
            },
        },
        "6": {
            "class_type": "WanVideoSampler",
            "inputs": {
                "model": ["1", 0],
                "image_embeds": ["5", 0],
                "text_embeds": ["4", 0],
                "steps": steps,
                "cfg": cfg,
                "shift": shift,
                "seed": seed,
                "scheduler": "unipc",
                "riflex_freq_index": 0,
                "force_offload": True,
            },
        },
        "7": {
            "class_type": "WanVideoDecode",
            "inputs": {
                "vae": ["3", 0],
                "samples": ["6", 0],
                "enable_vae_tiling": True,
                "tile_x": 272,
                "tile_y": 272,
                "tile_stride_x": 144,
                "tile_stride_y": 128,
            },
        },
        "8": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "images": ["7", 0],
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": output_prefix,
                "format": "video/h264-mp4",
                "pix_fmt": pix_fmt,
                "crf": crf,
                "save_metadata": True,
                "trim_to_audio": False,
                "pingpong": False,
                "save_output": True,
            },
        },
    }


def submit_wan_scene(form_data):
    log.info(
        "wan-video submit: character_preset=%s positive_len=%s negative_len=%s",
        form_data.get("character_preset", ""),
        len((form_data.get("positive_prompt", "") or "").strip()),
        len((form_data.get("negative_prompt", "") or "").strip()),
    )
    if not port_open(COMFY_PORT):
        comfy_start()
        for _ in range(20):
            if port_open(COMFY_PORT):
                break
            time.sleep(0.5)
    if not port_open(COMFY_PORT):
        return {"ok": False, "message": "ComfyUI no está disponible."}

    preset = get_wan_preset(form_data.get("model_preset", "wan_1b"))
    width = clamp_step(int(form_data["width"]), 256, 1280, 8)
    height = clamp_step(int(form_data["height"]), 256, 1280, 8)
    frames = clamp_step(int(form_data["frames"]), 8, 121, 1)
    fps = clamp_step(int(form_data["fps"]), 4, 30, 1)
    steps = clamp_step(int(form_data["steps"]), 10, 50, 1)
    cfg = max(1.0, min(10.0, float(form_data["cfg"])))
    shift = max(1.0, min(20.0, float(form_data.get("shift", "5.0"))))
    crf = clamp_step(int(form_data["crf"]), 14, 26, 1)
    pix_fmt = (
        form_data["pix_fmt"]
        if form_data["pix_fmt"] in ("yuv420p", "yuv420p10le")
        else "yuv420p"
    )
    seed = max(0, int(form_data["seed"]))
    character_preset_id = form_data.get("character_preset", "").strip()
    positive = form_data["positive_prompt"].strip()
    negative = form_data["negative_prompt"].strip()

    if character_preset_id:
        cp = get_character_video_prompt_preset(character_preset_id)
        if cp:
            if not positive:
                positive = (cp.get("positive_prompt") or "").strip()
            if not negative:
                negative = (cp.get("negative_prompt") or "").strip()
            log.info(
                "wan-video fallback applied: character_preset=%s positive_len=%s negative_len=%s",
                character_preset_id,
                len(positive),
                len(negative),
            )

    if not positive:
        return {"ok": False, "message": "El prompt positivo no puede estar vacío."}

    # Pre-flight: verificar nodos instalados
    required_wan = [
        "WanVideoModelLoader",
        "LoadWanVideoT5TextEncoder",
        "WanVideoVAELoader",
        "WanVideoTextEncode",
        "WanVideoEmptyEmbeds",
        "WanVideoSampler",
        "WanVideoDecode",
        "VHS_VideoCombine",
    ]
    missing = check_comfy_nodes(required_wan)
    if missing:
        return {
            "ok": False,
            "message": (
                f"Nodos no encontrados en ComfyUI: {', '.join(missing)}. "
                "Instala ComfyUI-WanVideoWrapper (github.com/kijai/ComfyUI-WanVideoWrapper) "
                "y reinicia ComfyUI."
            ),
        }

    obj_info = get_comfy_object_info()
    wan_model = resolve_wan_model_name(obj_info, preset)
    text_encoder = _resolve_comfy_option(
        obj_info,
        "LoadWanVideoT5TextEncoder",
        "model_name",
        preset["text_encoder"],
    )
    vae = _resolve_comfy_option(
        obj_info,
        "WanVideoVAELoader",
        "model_name",
        preset["vae"],
    )

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_prefix = f"wan_output/{timestamp}_{slugify_text(positive)[:48]}"

    workflow_file = None
    prompt = None
    if USE_EXTERNAL_WORKFLOW_FILES:
        for name in ("wan_txt2vid_api.json", "wan_video_api.json"):
            p = WORKFLOWS_DIR / name
            if p.exists():
                try:
                    api_wf = json.loads(p.read_text(encoding="utf-8"))
                    prompt = patch_api_workflow(
                        api_wf,
                        positive,
                        negative,
                        "",
                        width,
                        height,
                        frames,
                        fps,
                        steps,
                        cfg,
                        1.0,
                        crf,
                        pix_fmt,
                        seed,
                        output_prefix,
                        wan_model=wan_model,
                        shift=shift,
                        text_encoder=text_encoder,
                        vae=vae,
                    )
                    workflow_file = name
                    break
                except Exception:
                    continue

    if prompt is None:
        prompt = build_wan_prompt(
            wan_model=wan_model,
            text_encoder=text_encoder,
            vae=vae,
            positive=positive,
            negative=negative,
            width=width,
            height=height,
            frames=frames,
            fps=fps,
            steps=steps,
            cfg=cfg,
            crf=crf,
            pix_fmt=pix_fmt,
            seed=seed,
            shift=shift,
            output_prefix=output_prefix,
        )

    try:
        response = comfy_api_post("/prompt", {"prompt": prompt})
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            err_body = json.loads(raw)
            err = err_body.get("error", {})
            node_errors = err_body.get("node_errors", {})
            msg = err.get("message", exc.reason)
            detail = err.get("details", "")
            if node_errors:
                missing_nodes = [
                    v.get("class_type", nid)
                    for nid, v in node_errors.items()
                    if "does not exist" in str(v.get("errors", ""))
                ]
                if missing_nodes:
                    msg = (
                        f"Nodos no encontrados: {', '.join(missing_nodes)}. "
                        "Instala el custom node y reinicia ComfyUI."
                    )
            full = f"HTTP {exc.code}: {msg}"
            if detail and detail not in msg:
                full += f" ({detail})"
        except Exception:
            full = f"HTTP {exc.code}: {raw or exc.reason}"
        return {"ok": False, "message": full}
    except Exception as exc:
        return {"ok": False, "message": f"Error enviando a ComfyUI: {exc}"}

    prompt_id = response.get("prompt_id")
    if not prompt_id:
        return {"ok": False, "message": f"ComfyUI no aceptó el prompt: {response}"}

    return {
        "ok": True,
        "message": "Escena Wan2.1 encolada en ComfyUI.",
        "prompt_id": prompt_id,
        "output_prefix": output_prefix,
        "workflow_mode": "external" if workflow_file else "built-in",
        "workflow_file": workflow_file,
        "used_model": wan_model,
        "used_text_encoder": text_encoder,
        "used_vae": vae,
        "used_positive_prompt": positive,
    }


def export_wan_workflow(form_data):
    preset = get_wan_preset(form_data.get("model_preset", "wan_1b"))
    profile = get_wan_profile(form_data.get("video_profile", "portrait_fast"))
    output_path = WORKFLOWS_DIR / "wan_txt2vid_api.json"
    try:
        ensure_dir(WORKFLOWS_DIR)
        workflow = build_wan_prompt(
            wan_model=preset["model"],
            text_encoder=preset["text_encoder"],
            vae=preset["vae"],
            positive="YOUR POSITIVE PROMPT HERE",
            negative="worst quality, low quality, lowres, blurry, deformed, watermark",
            width=profile["width"],
            height=profile["height"],
            frames=profile["frames"],
            fps=profile["fps"],
            steps=profile["steps"],
            cfg=profile["cfg"],
            crf=profile["crf"],
            pix_fmt=profile["pix_fmt"],
            seed=42,
            shift=profile["shift"],
            output_prefix="wan_output/exported",
        )
        output_path.write_text(
            json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return {"ok": True, "path": str(output_path), "message": "Workflow exportado."}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


def default_game_tts_form():
    preset = GAME_TTS_PERSONALITY_PRESETS[0]
    chars = load_game_tts_character_presets()
    piper_models = list_piper_models()
    default_piper = Path(PIPER_MODEL_PATH).name
    if piper_models and not any(m.get("id") == default_piper for m in piper_models):
        default_piper = piper_models[0]["id"]
    return {
        "engine": "piper",
        "piper_model": default_piper,
        "character_id": chars[0]["id"] if chars else "hero",
        "language": "es",
        "personality_id": preset["id"],
        "voice_id": preset["voice_id"],
        "speed": preset["speed"],
        "pitch": preset["pitch"],
        "energy": preset["energy"],
        "emotion_tags": preset["emotion_tags"],
        "pauses": preset["pauses"],
        "text": "",
    }


def submit_game_tts(form_data):
    text = (form_data.get("text", "") or "").strip()
    if not text:
        return {"ok": False, "message": "Escribe un texto para generar audio."}

    engine = (form_data.get("engine", "piper") or "piper").strip().lower()
    language = (form_data.get("language", "es") or "es").strip().lower()
    character_id = (form_data.get("character_id", "") or "").strip()
    personality_id = (form_data.get("personality_id", "") or "").strip()
    piper_model_id = (form_data.get("piper_model", "") or "").strip()

    characters = load_game_tts_character_presets()
    character = next((c for c in characters if c.get("id") == character_id), None)
    if character is None:
        character = characters[0] if characters else {"id": "hero", "name": "Hero", "speaker_wav": ""}

    personality = dict(get_game_tts_personality(personality_id))
    for key in ("voice_id", "emotion_tags", "pauses"):
        if form_data.get(key) is not None:
            personality[key] = str(form_data.get(key, "")).strip()
    for key in ("speed", "pitch", "energy"):
        if form_data.get(key) is not None:
            try:
                personality[key] = float(form_data.get(key))
            except Exception:
                pass

    piper_model_path = ""
    if engine == "piper":
        selected_model = get_piper_model_by_id(piper_model_id)
        if selected_model is None:
            piper_models = list_piper_models()
            if not piper_models:
                return {"ok": False, "message": "No hay modelos Piper disponibles en ~/ai/piper."}
            selected_model = piper_models[0]
        piper_model_path = selected_model.get("path", "")

    result: dict[str, Any] = generate_game_tts(
        engine=engine,
        character=character,
        personality=personality,
        text=text,
        language=language,
        piper_model_path=piper_model_path,
    )
    if not result.get("ok"):
        return result

    result["message"] = (
        f"Audio generado con {engine.upper()} para {character.get('name', character.get('id', 'character'))}.\n"
        f"Preset: {personality.get('id', 'custom')} | voice_id: {personality.get('voice_id', '')}\n"
        f"speed={personality.get('speed', 1.0)} pitch={personality.get('pitch', 1.0)} energy={personality.get('energy', 1.0)}\n"
        f"emotion_tags={personality.get('emotion_tags', '')} pauses={personality.get('pauses', 'medium')}"
    )
    result["personality"] = personality
    result["character"] = character
    if engine == "piper":
        result["piper_model"] = Path(piper_model_path).name if piper_model_path else ""
    return result


# --- FLASK APP ----------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    status = check_all_status()
    return render_template_string(
        HTML,
        comfy_port=COMFY_PORT,
        ow_port=OW_PORT,
        ollama_port=OLLAMA_PORT,
        voice_port=VOICE_PORT,
        adult_chatbot_port=ADULT_CHATBOT_PORT,
        comfy_up=status.get("comfy", False),
        ow_up=status.get("openwebui", False),
        ollama_up=status.get("ollama", False),
        voice_up=status.get("voice", False),
        adultchatbot_up=status.get("adultchatbot", False),
        ow_container=OW_CONTAINER,
        ow_image=OW_IMAGE,
        voice_script=VOICE_SCRIPT.name,
    )


@app.route("/api/status")
def api_status():
    return jsonify(check_all_status())


@app.route("/tools/video-scene", methods=["GET", "POST"])
def video_scene():
    character_presets = load_character_video_prompt_presets()
    if request.method == "POST":
        result = submit_video_scene(request.form.to_dict())
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(result)
        form = default_video_form()
        form.update(request.form.to_dict())
        return render_template_string(
            VIDEO_TOOL_HTML,
            form=form,
            model_presets=VIDEO_MODEL_PRESETS,
            smooth_profiles=VIDEO_SMOOTH_PROFILES,
            smooth_profiles_json=json.dumps(VIDEO_SMOOTH_PROFILES),
            character_prompt_presets=character_presets,
            character_prompt_presets_json=json.dumps(
                character_presets, ensure_ascii=False
            ),
            server_result=json.dumps(result, ensure_ascii=False, indent=2),
            server_result_ok=bool(result.get("ok")),
        )
    form = default_video_form()
    return render_template_string(
        VIDEO_TOOL_HTML,
        form=form,
        model_presets=VIDEO_MODEL_PRESETS,
        smooth_profiles=VIDEO_SMOOTH_PROFILES,
        smooth_profiles_json=json.dumps(VIDEO_SMOOTH_PROFILES),
        character_prompt_presets=character_presets,
        character_prompt_presets_json=json.dumps(character_presets, ensure_ascii=False),
        server_result=None,
        server_result_ok=False,
    )


@app.route("/tools/wan-video", methods=["GET", "POST"])
def wan_video():
    character_presets = load_character_video_prompt_presets()
    if request.method == "POST":
        result = submit_wan_scene(request.form.to_dict())
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify(result)
        form = default_wan_form()
        form.update(request.form.to_dict())
        return render_template_string(
            WAN_TOOL_HTML,
            form=form,
            model_presets=WAN_MODEL_PRESETS,
            video_profiles=WAN_VIDEO_PROFILES,
            video_profiles_json=json.dumps(WAN_VIDEO_PROFILES),
            character_prompt_presets=character_presets,
            character_prompt_presets_json=json.dumps(
                character_presets, ensure_ascii=False
            ),
            server_result=json.dumps(result, ensure_ascii=False, indent=2),
            server_result_ok=bool(result.get("ok")),
        )
    form = default_wan_form()
    return render_template_string(
        WAN_TOOL_HTML,
        form=form,
        model_presets=WAN_MODEL_PRESETS,
        video_profiles=WAN_VIDEO_PROFILES,
        video_profiles_json=json.dumps(WAN_VIDEO_PROFILES),
        character_prompt_presets=character_presets,
        character_prompt_presets_json=json.dumps(character_presets, ensure_ascii=False),
        server_result=None,
        server_result_ok=False,
    )


@app.route("/tools/wan-video/export", methods=["POST"])
def wan_video_export():
    return jsonify(export_wan_workflow(request.form.to_dict()))


@app.route("/tools/wan-i2v", methods=["GET", "POST"])
def wan_i2v_tool():
    if request.method == "POST":
        return jsonify(submit_wan_i2v_scene(request.form.to_dict()))

    form = default_wan_i2v_form()
    input_images = list_comfy_input_images()
    return render_template_string(
        WAN_I2V_TOOL_HTML,
        form=form,
        input_images=input_images,
        model_presets=WAN_MODEL_PRESETS,
        video_profiles=WAN_VIDEO_PROFILES,
        video_profiles_json=json.dumps(WAN_VIDEO_PROFILES),
    )


@app.route("/tools/wan-i2v/input-images", methods=["GET"])
def wan_i2v_input_images():
    images = list_comfy_input_images()
    return jsonify({"ok": True, "images": images})


@app.route("/tools/character-video-prompt/<preset_id>", methods=["GET"])
def character_video_prompt(preset_id):
    preset = get_character_video_prompt_preset(preset_id)
    if not preset:
        log.warning("character-video-prompt not found: %s", preset_id)
        return jsonify({"ok": False, "message": "Perfil no encontrado."}), 404
    log.info(
        "character-video-prompt loaded: %s positive_len=%s negative_len=%s",
        preset_id,
        len((preset.get("positive_prompt") or "").strip()),
        len((preset.get("negative_prompt") or "").strip()),
    )
    return jsonify(
        {
            "ok": True,
            "id": preset.get("id", ""),
            "name": preset.get("name", ""),
            "positive_prompt": preset.get("positive_prompt", ""),
            "negative_prompt": preset.get("negative_prompt", ""),
        }
    )


@app.route("/tools/game-tts", methods=["GET"])
def game_tts_tool():
    form = default_game_tts_form()
    characters = load_game_tts_character_presets()
    piper_models = list_piper_models()
    piper_recommendations = get_game_tts_piper_recommendations()
    return render_template_string(
        GAME_TTS_HTML,
        form=form,
        characters=characters,
        piper_models=piper_models,
        piper_recommendations_json=json.dumps(piper_recommendations, ensure_ascii=False),
        personalities=GAME_TTS_PERSONALITY_PRESETS,
        personalities_json=json.dumps(GAME_TTS_PERSONALITY_PRESETS, ensure_ascii=False),
    )


@app.route("/tools/game-tts/generate", methods=["POST"])
def game_tts_generate():
    result = submit_game_tts(request.form.to_dict())
    return jsonify(result)


@app.route("/tools/game-tts/audio/<path:filename>", methods=["GET"])
def game_tts_audio(filename):
    safe_name = Path(filename).name
    return send_from_directory(VOICE_OUT_DIR, safe_name, as_attachment=False)


@app.route("/tools/ollama-models", methods=["GET"])
def ollama_models_tool():
    presets = load_ollama_prompt_presets()
    return render_template_string(
        OLLAMA_MODELS_HTML,
        prompt_presets=presets,
        prompt_presets_json=json.dumps(presets, ensure_ascii=False),
    )


@app.route("/tools/ollama-models/list", methods=["GET"])
def ollama_models_list():
    return jsonify(ollama_list_models())


@app.route("/tools/ollama-models/pull", methods=["POST"])
def ollama_models_pull():
    body = request.get_json(silent=True) or {}
    model_name = str(body.get("model", "")).strip()
    return jsonify(ollama_pull_model(model_name))


@app.route("/tools/ollama-models/create", methods=["POST"])
def ollama_models_create():
    body = request.get_json(silent=True) or {}
    model_name = str(body.get("model_name", "")).strip()
    base_model = str(body.get("base_model", "")).strip()
    system_prompt = str(body.get("system_prompt", ""))
    return jsonify(ollama_create_custom_model(model_name, base_model, system_prompt))


@app.post("/svc/comfy/<action>")
def svc_comfy(action):
    if action == "start":
        comfy_start()
    elif action == "stop":
        comfy_stop()
    elif action == "restart":
        comfy_stop()
        time.sleep(0.3)
        comfy_start()
    return ("", 204)


@app.post("/svc/voice/<action>")
def svc_voice(action):
    if action == "start":
        voice_start()
    elif action == "stop":
        voice_stop()
    elif action == "restart":
        voice_stop()
        time.sleep(0.3)
        voice_start()
    return ("", 204)


@app.post("/svc/ollama/<action>")
def svc_ollama(action):
    if action == "start":
        ollama_start()
    return ("", 204)


@app.post("/svc/openwebui/<action>")
def svc_openwebui(action):
    if action == "start":
        openwebui_start()
    elif action == "stop":
        openwebui_stop()
    return ("", 204)


@app.post("/svc/adultchatbot/<action>")
def svc_adultchatbot(action):
    if action == "start":
        adult_chatbot_start()
    elif action == "stop":
        adult_chatbot_stop()
    elif action == "restart":
        adult_chatbot_stop()
        time.sleep(0.3)
        adult_chatbot_start()
    return ("", 204)


if __name__ == "__main__":
    log.info("Landing host=%s debug=%s", LANDING_HOST, LANDING_DEBUG)
    log.info("Python runtime para servicios: %s", VENV_PYTHON)
    log.info("Voice script seleccionado: %s", VOICE_SCRIPT)
    t = threading.Thread(target=autostart, daemon=True)
    t.start()
    app.run(host=LANDING_HOST, port=5000, debug=LANDING_DEBUG, use_reloader=False)
