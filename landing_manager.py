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
import logging
import os
import random
import re
import socket
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import request as urlrequest, error as urlerror
from flask import Flask, render_template_string, request, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# --- RUTAS Y PUERTOS ----------------------------------------------------------
HOME = Path.home()
AI_DIR = HOME / "ai"

COMFY_DIR = AI_DIR / "ComfyUI"
COMFY_CMD = f"cd {COMFY_DIR} && {AI_DIR}/venv/bin/python main.py"
COMFY_PORT = 8188
WORKFLOWS_DIR = COMFY_DIR / "workflows"

OW_CONTAINER = "open-webui"
OW_IMAGE = "ghcr.io/open-webui/open-webui:latest"
OW_PORT = 8080
OLLAMA_PORT = 11434

VOICE_SCRIPT = AI_DIR / "voice_assistant_ui.py"
VOICE_CMD = f"{AI_DIR}/venv/bin/python {VOICE_SCRIPT}"
VOICE_PORT = 7862
WAN_WRAPPER_DIR = COMFY_DIR / "custom_nodes" / "ComfyUI-WanVideoWrapper"
OLLAMA_MODELFILES_DIR = AI_DIR / "modelfiles"

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
    {"key": "comfy",     "label": "ComfyUI",    "port": COMFY_PORT},
    {"key": "openwebui", "label": "Open WebUI", "port": OW_PORT},
    {"key": "ollama",    "label": "Ollama",      "port": OLLAMA_PORT},
    {"key": "voice",     "label": "Voice UI",    "port": VOICE_PORT},
]

# --- PRESETS AnimateDiff SDXL -------------------------------------------------
VIDEO_MODEL_PRESETS = [
    {"id": "wai_nsfw",      "name": "WAI NSFW SDXL",        "checkpoint": "wai-nsfw-illustrious-sdxl.safetensors", "include_token": "wai_nsfw"},
    {"id": "realvis",       "name": "RealVisXL",             "checkpoint": "RealVisXL_V5.0.safetensors",            "include_token": "realvis"},
    {"id": "cyberrealistic","name": "CyberRealistic SDXL",   "checkpoint": "cyberrealisticXL.safetensors",          "include_token": "cyberrealistic"},
    {"id": "juggernaut",    "name": "Juggernaut XL",         "checkpoint": "juggernautXL.safetensors",              "include_token": "juggernaut"},
    {"id": "dreamshaper_xl","name": "DreamShaper XL",        "checkpoint": "dreamshaperXL.safetensors",             "include_token": "dreamshaper"},
]

VIDEO_SMOOTH_PROFILES = [
    {
        "id": "cinematic_stable", "name": "Cinemático Estable",
        "desc": "640x960, 24 frames, 8 fps", "width": 640, "height": 960,
        "frames": 24, "fps": 8, "steps": 20, "cfg": 7.0, "denoise": 1.0,
        "crf": 18, "pix_fmt": "yuv420p",
    },
    {
        "id": "fluid_dynamic", "name": "Fluido Dinámico",
        "desc": "640x960, 20 frames, 10 fps", "width": 640, "height": 960,
        "frames": 20, "fps": 10, "steps": 20, "cfg": 7.0, "denoise": 1.0,
        "crf": 18, "pix_fmt": "yuv420p",
    },
]

# --- PRESETS WAN2.1 -----------------------------------------------------------
WAN_MODEL_PRESETS = [
    {
        "id": "wan_1b", "name": "Wan2.1 T2V 1.3B (rápido)",
        "model": "Fun/Lumen/Wan2_1_Lumen-T2V-1.3B-V1.0_bf16.safetensors",
        "text_encoder": "umt5-xxl-enc-bf16.safetensors",
        "vae": "Wan2_1_VAE_bf16.safetensors",
    },
    {
        "id": "wan_14b", "name": "Wan2.1 T2V 14B (calidad)",
        "model": "Wan2_1-T2V-14B_fp8_e4m3fn.safetensors",
        "text_encoder": "umt5-xxl-enc-bf16.safetensors",
        "vae": "Wan2_1_VAE_bf16.safetensors",
    },
]

WAN_VIDEO_PROFILES = [
    {
        "id": "portrait_fast", "name": "Portrait Fast (480x832)",
        "desc": "Formato vertical, rápido", "width": 480, "height": 832,
        "frames": 20, "fps": 8, "steps": 20, "cfg": 6.0, "shift": 5.0,
        "crf": 18, "pix_fmt": "yuv420p",
    },
    {
        "id": "portrait_quality", "name": "Portrait Quality (480x832)",
        "desc": "Formato vertical, más steps", "width": 480, "height": 832,
        "frames": 24, "fps": 8, "steps": 30, "cfg": 6.0, "shift": 5.0,
        "crf": 18, "pix_fmt": "yuv420p",
    },
    {
        "id": "landscape_quality", "name": "Landscape Quality (832x480)",
        "desc": "Formato apaisado, calidad alta", "width": 832, "height": 480,
        "frames": 24, "fps": 8, "steps": 30, "cfg": 6.0, "shift": 5.0,
        "crf": 18, "pix_fmt": "yuv420p",
    },
]

# --- HTML PRINCIPAL -----------------------------------------------------------
HTML = """
<!doctype html>
<html lang="es"><head>
<meta charset="utf-8"><title>Centro de IA Local — Gestor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}
body{font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,"Helvetica Neue",Arial;background:#0f1115;color:#e5ecf5;margin:0}
.wrap{max-width:1060px;margin:48px auto;padding:0 20px}
h1{font-size:28px;margin:0 0 10px}.sub{opacity:.82;margin-bottom:28px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}
.card{background:#131826;border:1px solid #222a3c;border-radius:14px;padding:16px}
.head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.name{font-weight:600}.url{font-size:13px;opacity:.8}
.status{font-size:12px;padding:4px 8px;border-radius:999px}
.up{background:#13341f;color:#8ae6a2;border:1px solid #1f5e33}
.down{background:#3a1e1e;color:#f2a6a6;border:1px solid #6b3030}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
a.btn{text-decoration:none;padding:10px 12px;border-radius:10px;background:#1a2132;border:1px solid #2a3144;color:#e5ecf5;font-size:14px;cursor:pointer}
a.btn:hover{background:#202944}
.help{margin-top:28px;font-size:14px;opacity:.9}
code{background:#1a2132;padding:2px 6px;border-radius:6px;border:1px solid #2a3144}
pre{background:#0b0f18;border:1px solid #222a3c;border-radius:10px;padding:14px;overflow:auto}
.tool-card{background:#0e1420;border:1px solid #1a2a4a;border-radius:14px;padding:16px;margin-top:0}
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
:root{color-scheme:dark}body{font-family:ui-sans-serif,system-ui,Arial;background:#0f1115;color:#e5ecf5;margin:0}
.wrap{max-width:780px;margin:40px auto;padding:0 20px}h1{font-size:24px;margin:0 0 6px}
.back{font-size:13px;opacity:.7;margin-bottom:20px}.back a{color:#8ab4f8;text-decoration:none}
label{display:block;font-size:13px;opacity:.8;margin:12px 0 3px}
input,textarea,select{width:100%;box-sizing:border-box;background:#131826;border:1px solid #2a3144;border-radius:8px;color:#e5ecf5;padding:8px 10px;font-size:14px}
textarea{height:90px;resize:vertical}.row{display:flex;gap:12px}.row>div{flex:1}
button{margin-top:18px;background:#1e3a6e;border:1px solid #2a5098;color:#e5ecf5;padding:10px 22px;border-radius:10px;font-size:15px;cursor:pointer}
button:hover{background:#264880}
.result{margin-top:20px;background:#131826;border:1px solid #2a3144;border-radius:10px;padding:14px;font-size:14px;white-space:pre-wrap}
.ok{color:#8ae6a2}.err{color:#f2a6a6}
.section{background:#0e1420;border:1px solid #1a2a4a;border-radius:12px;padding:14px;margin-bottom:14px}
.section-title{font-size:13px;font-weight:600;opacity:.6;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
</style></head><body><div class="wrap">
<h1>🎬 AnimateDiff SDXL — Generar Vídeo</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>
<form id="vf" onsubmit="submit(event)">
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
  <button type="submit">🎬 Generar vídeo</button>
</form>
<div id="result" class="result" style="display:none"></div>
</div>
<script>
const profiles={{smooth_profiles_json}};
function applyProfile(sel){
  const p=profiles.find(x=>x.id===sel.value);if(!p)return;
  const f=document.getElementById('vf');
  ['width','height','frames','fps','steps','cfg','denoise','crf'].forEach(k=>{if(f[k]&&p[k]!==undefined)f[k].value=p[k];});
}
async function submit(e){
  e.preventDefault();const r=document.getElementById('result');
  r.style.display='block';r.className='result';r.textContent='Enviando a ComfyUI...';
  const fd=new FormData(e.target);
  try{
    const resp=await fetch('/tools/video-scene',{method:'POST',body:new URLSearchParams(fd)});
    const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
    let msg=data.message||'';
    if(data.prompt_id)msg+='\\nPrompt ID: '+data.prompt_id;
    if(data.output_prefix)msg+='\\nOutput: '+data.output_prefix;
    if(data.workflow_file)msg+='\\nWorkflow: '+data.workflow_file;else msg+='\\n(workflow built-in)';
    r.textContent=msg;
  }catch(err){r.className='result err';r.textContent='Error: '+err;}
}
</script></body></html>
"""

# --- HTML WAN2.1 VIDEO TOOL ---------------------------------------------------
WAN_TOOL_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Wan2.1 — Generar Vídeo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}body{font-family:ui-sans-serif,system-ui,Arial;background:#0f1115;color:#e5ecf5;margin:0}
.wrap{max-width:780px;margin:40px auto;padding:0 20px}h1{font-size:24px;margin:0 0 6px}
.back{font-size:13px;opacity:.7;margin-bottom:20px}.back a{color:#8ab4f8;text-decoration:none}
label{display:block;font-size:13px;opacity:.8;margin:12px 0 3px}
input,textarea,select{width:100%;box-sizing:border-box;background:#131826;border:1px solid #2a3144;border-radius:8px;color:#e5ecf5;padding:8px 10px;font-size:14px}
textarea{height:90px;resize:vertical}.row{display:flex;gap:12px}.row>div{flex:1}
button{margin-top:6px;background:#1e3a6e;border:1px solid #2a5098;color:#e5ecf5;padding:10px 22px;border-radius:10px;font-size:15px;cursor:pointer}
button:hover{background:#264880}button.sec{background:#1a2540;border-color:#2a3560;margin-left:10px}
.result{margin-top:20px;background:#131826;border:1px solid #2a3144;border-radius:10px;padding:14px;font-size:14px;white-space:pre-wrap}
.ok{color:#8ae6a2}.err{color:#f2a6a6}
.section{background:#0e1420;border:1px solid #1a2a4a;border-radius:12px;padding:14px;margin-bottom:14px}
.section-title{font-size:13px;font-weight:600;opacity:.6;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
.note{font-size:12px;opacity:.6;margin-top:4px}
</style></head><body><div class="wrap">
<h1>🎞️ Wan2.1 — Text to Video</h1>
<div class="back"><a href="/">← Volver al gestor</a></div>
<div class="note" style="margin-bottom:16px">Requiere: ComfyUI-WanVideoWrapper + modelos en <code>diffusion_models/</code>, <code>text_encoders/</code> y <code>vae/</code></div>
<form id="wf" onsubmit="submit(event)">
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
    <button type="button" class="sec" onclick="exportWf()">📤 Exportar workflow JSON</button>
  </div>
</form>
<div id="result" class="result" style="display:none"></div>
</div>
<script>
const profiles={{video_profiles_json}};
function applyProfile(sel){
  const p=profiles.find(x=>x.id===sel.value);if(!p)return;
  const f=document.getElementById('wf');
  ['width','height','frames','fps','steps','cfg','shift','crf'].forEach(k=>{if(f[k]&&p[k]!==undefined)f[k].value=p[k];});
}
async function submit(e){
  e.preventDefault();const r=document.getElementById('result');
  r.style.display='block';r.className='result';r.textContent='Enviando a ComfyUI...';
  const fd=new FormData(e.target);
  try{
    const resp=await fetch('/tools/wan-video',{method:'POST',body:new URLSearchParams(fd)});
    const data=await resp.json();r.className='result '+(data.ok?'ok':'err');
    let msg=data.message||'';
    if(data.prompt_id)msg+='\\nPrompt ID: '+data.prompt_id;
    if(data.output_prefix)msg+='\\nOutput: '+data.output_prefix;
    if(data.workflow_file)msg+='\\nWorkflow: '+data.workflow_file;
    else if(data.ok)msg+='\\n(workflow built-in — usa Exportar para personalizar)';
    if(data.ok)msg+='\\n→ http://localhost:8188/queue';
    r.textContent=msg;
  }catch(err){r.className='result err';r.textContent='Error: '+err;}
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

# --- HTML OLLAMA CUSTOM MODELS TOOL ------------------------------------------
OLLAMA_MODELS_HTML = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><title>Ollama Custom Models</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{color-scheme:dark}body{font-family:ui-sans-serif,system-ui,Arial;background:#0f1115;color:#e5ecf5;margin:0}
.wrap{max-width:900px;margin:40px auto;padding:0 20px}h1{font-size:24px;margin:0 0 6px}
.back{font-size:13px;opacity:.7;margin-bottom:20px}.back a{color:#8ab4f8;text-decoration:none}
.section{background:#0e1420;border:1px solid #1a2a4a;border-radius:12px;padding:14px;margin-bottom:14px}
.section-title{font-size:13px;font-weight:600;opacity:.6;text-transform:uppercase;letter-spacing:.06em;margin-bottom:10px}
label{display:block;font-size:13px;opacity:.8;margin:12px 0 3px}
input,textarea{width:100%;box-sizing:border-box;background:#131826;border:1px solid #2a3144;border-radius:8px;color:#e5ecf5;padding:8px 10px;font-size:14px}
textarea{height:140px;resize:vertical}.row{display:flex;gap:12px}.row>div{flex:1}
button{margin-top:12px;background:#1e3a6e;border:1px solid #2a5098;color:#e5ecf5;padding:10px 22px;border-radius:10px;font-size:15px;cursor:pointer}
button:hover{background:#264880}button.sec{background:#1a2540;border-color:#2a3560;margin-left:10px}
.result{margin-top:16px;background:#131826;border:1px solid #2a3144;border-radius:10px;padding:14px;font-size:14px;white-space:pre-wrap}
.ok{color:#8ae6a2}.err{color:#f2a6a6}
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


def run_bg(cmd: str, pidfile: Path) -> int:
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
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
        subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
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


def comfy_start():
    if port_open(COMFY_PORT):
        return "already"
    log.info("Arrancando ComfyUI...")
    return run_bg(COMFY_CMD, COMFY_PID)


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
    r = subprocess.run(["docker", "start", OW_CONTAINER], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode == 0:
        return "started"
    cmd = [
        "docker", "run", "-d", "--name", OW_CONTAINER,
        "-p", f"{OW_PORT}:8080", "--network", "host",
        "-e", f"OLLAMA_BASE_URL=http://127.0.0.1:{OLLAMA_PORT}",
        "-v", "openwebui-data:/app/backend/data",
        "--restart", "unless-stopped",
        OW_IMAGE,
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return "run_ok" if r.returncode == 0 else f"run_fail:{r.stderr.decode(errors='ignore')}"


def openwebui_stop():
    if not have_docker():
        return
    subprocess.run(["docker", "stop", OW_CONTAINER], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"})
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
    req = urlrequest.Request(url, data=data, headers={"Content-Type": "application/json"})
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
        ollama_api_post("/api/pull", {"name": model_name, "stream": False}, timeout=1800.0)
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
        modelfile += f"SYSTEM \"\"\"{escaped}\"\"\"\n"
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


# --- WORKFLOWS ----------------------------------------------------------------
def patch_api_workflow(workflow, positive, negative, checkpoint,
                       width, height, frames, fps, steps, cfg, denoise,
                       crf, pix_fmt, seed, output_prefix,
                       wan_model=None, shift=5.0, text_encoder=None, vae=None):
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
        node["inputs"].update({"steps": steps, "cfg": cfg, "seed": seed, "denoise": denoise})

    patch_node("EmptyLatentImage", {"width": width, "height": height, "batch_size": 1})
    for ct in ("ADE_AnimateDiffLoaderWithContext", "ADE_AnimateDiffLoaderGen1"):
        patch_node(ct, {"context_length": frames})
    patch_node("VHS_VideoCombine", {
        "frame_rate": fps, "crf": crf, "pix_fmt": pix_fmt,
        "filename_prefix": output_prefix,
    })

    if wan_model:
        patch_node("WanVideoModelLoader", {"model": wan_model})
    patch_node("WanVideoSampler", {"shift": shift, "steps": steps, "cfg": cfg, "seed": seed})
    if text_encoder:
        patch_node("LoadWanVideoT5TextEncoder", {"model_name": text_encoder})
    if vae:
        patch_node("WanVideoVAELoader", {"model_name": vae})
    patch_node("WanVideoTextEncode", {"positive_prompt": positive, "negative_prompt": negative})
    patch_node("WanVideoEmptyEmbeds", {"width": width, "height": height, "num_frames": frames})

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


def default_video_form():
    profile = VIDEO_SMOOTH_PROFILES[0]
    return {
        "model_preset": VIDEO_MODEL_PRESETS[0]["id"],
        "smooth_profile": profile["id"],
        "positive_prompt": "",
        "negative_prompt": "worst quality, low quality, lowres, blurry, deformed, watermark",
        "width": profile["width"], "height": profile["height"],
        "frames": profile["frames"], "fps": profile["fps"],
        "steps": profile["steps"], "cfg": profile["cfg"],
        "denoise": profile["denoise"], "crf": profile["crf"],
        "pix_fmt": profile["pix_fmt"], "seed": random.randint(0, 2**31),
    }


def build_video_prompt(checkpoint, positive, negative, width, height, frames, fps,
                       steps, cfg, denoise, crf, pix_fmt, seed, output_prefix):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "ADE_AnimateDiffLoaderWithContext", "inputs": {
            "model": ["1", 0], "context_length": frames,
            "context_stride": 1, "context_overlap": 4, "closed_loop": False,
        }},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["5", 0], "positive": ["2", 0], "negative": ["3", 0],
            "latent_image": ["4", 0], "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "euler_a", "scheduler": "karras", "denoise": denoise,
        }},
        "7": {"class_type": "VAEDecode", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["7", 0], "frame_rate": fps, "loop_count": 0,
            "filename_prefix": output_prefix, "format": "video/h264-mp4",
            "pix_fmt": pix_fmt, "crf": crf, "save_metadata": True,
            "trim_to_audio": False, "pingpong": False, "save_output": True,
        }},
    }


def submit_video_scene(form_data):
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
    positive = form_data.get("positive_prompt", "").strip()
    negative = form_data.get("negative_prompt", "").strip()

    if not positive:
        return {"ok": False, "message": "El prompt positivo no puede estar vacío."}

    checkpoint = find_checkpoint(preset["include_token"]) or preset["checkpoint"]
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_prefix = f"video_output/{timestamp}_{slugify_text(positive)[:48]}"

    workflow_file = None
    prompt = None
    for fname in (f"{preset['id']}_video_api.json", "animatediff_video_api.json"):
        p = WORKFLOWS_DIR / fname
        if p.exists():
            try:
                api_wf = json.loads(p.read_text(encoding="utf-8"))
                prompt = patch_api_workflow(
                    api_wf, positive, negative, checkpoint,
                    width, height, frames, fps, steps, cfg, denoise,
                    crf, pix_fmt, seed, output_prefix,
                )
                workflow_file = fname
                break
            except Exception:
                continue

    if prompt is None:
        prompt = build_video_prompt(checkpoint, positive, negative, width, height,
                                    frames, fps, steps, cfg, denoise, crf, pix_fmt,
                                    seed, output_prefix)

    try:
        response = comfy_api_post("/prompt", {"prompt": prompt})
    except urlerror.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore")
        try:
            err_body = json.loads(raw)
            msg = err_body.get("error", {}).get("message", exc.reason)
            node_errors = err_body.get("node_errors", {})
            if node_errors:
                missing = [v.get("class_type", nid) for nid, v in node_errors.items()
                           if "does not exist" in str(v.get("errors", ""))]
                if missing:
                    msg = f"Nodos no encontrados: {', '.join(missing)}."
            full = f"HTTP {exc.code}: {msg}"
        except Exception:
            full = f"HTTP {exc.code}: {raw or exc.reason}"
        return {"ok": False, "message": full}
    except Exception as exc:
        return {"ok": False, "message": f"Error enviando a ComfyUI: {exc}"}

    prompt_id = response.get("prompt_id")
    if not prompt_id:
        return {"ok": False, "message": f"ComfyUI no aceptó el prompt: {response}"}
    return {"ok": True, "message": "Vídeo encolado en ComfyUI.", "prompt_id": prompt_id,
            "output_prefix": output_prefix, "workflow_file": workflow_file}


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


def default_wan_form():
    profile = WAN_VIDEO_PROFILES[0]
    return {
        "model_preset": WAN_MODEL_PRESETS[0]["id"],
        "video_profile": profile["id"],
        "positive_prompt": "",
        "negative_prompt": "worst quality, low quality, lowres, blurry, deformed, watermark",
        "width": profile["width"], "height": profile["height"],
        "frames": profile["frames"], "fps": profile["fps"],
        "steps": profile["steps"], "cfg": profile["cfg"],
        "shift": profile["shift"], "crf": profile["crf"],
        "pix_fmt": profile["pix_fmt"], "seed": random.randint(0, 2**31),
    }


def build_wan_prompt(wan_model, text_encoder, vae, positive, negative,
                     width, height, frames, fps, steps, cfg, crf, pix_fmt,
                     seed, shift, output_prefix):
    """Workflow built-in para Wan2.1 T2V usando ComfyUI-WanVideoWrapper (kijai).
    Nodos verificados contra nodes_model_loading.py + nodes.py + nodes_sampler.py.
    Paths: diffusion_models/ | text_encoders/ | vae/
    """
    return {
        "1": {"class_type": "WanVideoModelLoader", "inputs": {
            "model": wan_model, "base_precision": "bf16",
            "quantization": "disabled", "load_device": "offload_device",
        }},
        "2": {"class_type": "LoadWanVideoT5TextEncoder", "inputs": {
            "model_name": text_encoder, "precision": "bf16",
            "load_device": "offload_device", "quantization": "disabled",
        }},
        "3": {"class_type": "WanVideoVAELoader", "inputs": {
            "model_name": vae, "precision": "bf16",
        }},
        "4": {"class_type": "WanVideoTextEncode", "inputs": {
            "positive_prompt": positive, "negative_prompt": negative,
            "t5": ["2", 0], "force_offload": True,
        }},
        "5": {"class_type": "WanVideoEmptyEmbeds", "inputs": {
            "width": width, "height": height, "num_frames": frames,
        }},
        "6": {"class_type": "WanVideoSampler", "inputs": {
            "model": ["1", 0], "image_embeds": ["5", 0], "text_embeds": ["4", 0],
            "steps": steps, "cfg": cfg, "shift": shift, "seed": seed,
            "scheduler": "unipc", "riflex_freq_index": 0, "force_offload": True,
        }},
        "7": {"class_type": "WanVideoDecode", "inputs": {
            "vae": ["3", 0], "samples": ["6", 0],
            "enable_vae_tiling": True,
            "tile_x": 272, "tile_y": 272, "tile_stride_x": 144, "tile_stride_y": 128,
        }},
        "8": {"class_type": "VHS_VideoCombine", "inputs": {
            "images": ["7", 0], "frame_rate": fps, "loop_count": 0,
            "filename_prefix": output_prefix, "format": "video/h264-mp4",
            "pix_fmt": pix_fmt, "crf": crf, "save_metadata": True,
            "trim_to_audio": False, "pingpong": False, "save_output": True,
        }},
    }


def submit_wan_scene(form_data):
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
    pix_fmt = form_data["pix_fmt"] if form_data["pix_fmt"] in ("yuv420p", "yuv420p10le") else "yuv420p"
    seed = max(0, int(form_data["seed"]))
    positive = form_data["positive_prompt"].strip()
    negative = form_data["negative_prompt"].strip()

    if not positive:
        return {"ok": False, "message": "El prompt positivo no puede estar vacío."}

    # Pre-flight: verificar nodos instalados
    required_wan = [
        "WanVideoModelLoader", "LoadWanVideoT5TextEncoder", "WanVideoVAELoader",
        "WanVideoTextEncode", "WanVideoEmptyEmbeds", "WanVideoSampler",
        "WanVideoDecode", "VHS_VideoCombine",
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

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_prefix = f"wan_output/{timestamp}_{slugify_text(positive)[:48]}"

    workflow_file = None
    prompt = None
    for name in ("wan_txt2vid_api.json", "wan_video_api.json"):
        p = WORKFLOWS_DIR / name
        if p.exists():
            try:
                api_wf = json.loads(p.read_text(encoding="utf-8"))
                prompt = patch_api_workflow(
                    api_wf, positive, negative, "",
                    width, height, frames, fps, steps, cfg, 1.0,
                    crf, pix_fmt, seed, output_prefix,
                    wan_model=preset["model"], shift=shift,
                    text_encoder=preset["text_encoder"], vae=preset["vae"],
                )
                workflow_file = name
                break
            except Exception:
                continue

    if prompt is None:
        prompt = build_wan_prompt(
            wan_model=preset["model"], text_encoder=preset["text_encoder"],
            vae=preset["vae"], positive=positive, negative=negative,
            width=width, height=height, frames=frames, fps=fps,
            steps=steps, cfg=cfg, crf=crf, pix_fmt=pix_fmt,
            seed=seed, shift=shift, output_prefix=output_prefix,
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
                    v.get("class_type", nid) for nid, v in node_errors.items()
                    if "does not exist" in str(v.get("errors", ""))
                ]
                if missing_nodes:
                    msg = (f"Nodos no encontrados: {', '.join(missing_nodes)}. "
                           "Instala el custom node y reinicia ComfyUI.")
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
        "ok": True, "message": "Escena Wan2.1 encolada en ComfyUI.",
        "prompt_id": prompt_id, "output_prefix": output_prefix,
        "workflow_file": workflow_file,
    }


def export_wan_workflow(form_data):
    preset = get_wan_preset(form_data.get("model_preset", "wan_1b"))
    profile = get_wan_profile(form_data.get("video_profile", "portrait_fast"))
    output_path = WORKFLOWS_DIR / "wan_txt2vid_api.json"
    try:
        ensure_dir(WORKFLOWS_DIR)
        workflow = build_wan_prompt(
            wan_model=preset["model"], text_encoder=preset["text_encoder"],
            vae=preset["vae"], positive="YOUR POSITIVE PROMPT HERE",
            negative="worst quality, low quality, lowres, blurry, deformed, watermark",
            width=profile["width"], height=profile["height"],
            frames=profile["frames"], fps=profile["fps"],
            steps=profile["steps"], cfg=profile["cfg"],
            crf=profile["crf"], pix_fmt=profile["pix_fmt"],
            seed=42, shift=profile["shift"], output_prefix="wan_output/exported",
        )
        output_path.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "path": str(output_path), "message": "Workflow exportado."}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# --- FLASK APP ----------------------------------------------------------------
app = Flask(__name__)


@app.route("/")
def index():
    status = check_all_status()
    return render_template_string(HTML,
        comfy_port=COMFY_PORT, ow_port=OW_PORT,
        ollama_port=OLLAMA_PORT, voice_port=VOICE_PORT,
        comfy_up=status.get("comfy", False),
        ow_up=status.get("openwebui", False),
        ollama_up=status.get("ollama", False),
        voice_up=status.get("voice", False),
        ow_container=OW_CONTAINER, ow_image=OW_IMAGE,
        voice_script=VOICE_SCRIPT.name,
    )


@app.route("/api/status")
def api_status():
    return jsonify(check_all_status())


@app.route("/tools/video-scene", methods=["GET", "POST"])
def video_scene():
    if request.method == "POST":
        return jsonify(submit_video_scene(request.form.to_dict()))
    form = default_video_form()
    return render_template_string(VIDEO_TOOL_HTML,
        form=form, model_presets=VIDEO_MODEL_PRESETS,
        smooth_profiles=VIDEO_SMOOTH_PROFILES,
        smooth_profiles_json=json.dumps(VIDEO_SMOOTH_PROFILES),
    )


@app.route("/tools/wan-video", methods=["GET", "POST"])
def wan_video():
    if request.method == "POST":
        return jsonify(submit_wan_scene(request.form.to_dict()))
    form = default_wan_form()
    return render_template_string(WAN_TOOL_HTML,
        form=form, model_presets=WAN_MODEL_PRESETS,
        video_profiles=WAN_VIDEO_PROFILES,
        video_profiles_json=json.dumps(WAN_VIDEO_PROFILES),
    )


@app.route("/tools/wan-video/export", methods=["POST"])
def wan_video_export():
    return jsonify(export_wan_workflow(request.form.to_dict()))


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
    if action == "start": comfy_start()
    elif action == "stop": comfy_stop()
    elif action == "restart": comfy_stop(); time.sleep(0.3); comfy_start()
    return ("", 204)


@app.post("/svc/voice/<action>")
def svc_voice(action):
    if action == "start": voice_start()
    elif action == "stop": voice_stop()
    elif action == "restart": voice_stop(); time.sleep(0.3); voice_start()
    return ("", 204)


@app.post("/svc/ollama/<action>")
def svc_ollama(action):
    if action == "start": ollama_start()
    return ("", 204)


@app.post("/svc/openwebui/<action>")
def svc_openwebui(action):
    if action == "start": openwebui_start()
    elif action == "stop": openwebui_stop()
    return ("", 204)


if __name__ == "__main__":
    t = threading.Thread(target=autostart, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=True)
