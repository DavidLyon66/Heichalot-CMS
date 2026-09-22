#!/usr/bin/env python3
"""
characterif.py - Heichalot two-node Tailcat bootstrap/link prototype.

v0.3a idea (v0.2 transport preserved; display/API entry-points added):

  NODE A:
      python3 tools/characterif.py start

      - starts the local Flask API
      - starts `tailcat --json serve <api-port>`
      - obtains A's Tailcat address
      - gives a tiny JSON identity document to `croc send --text`
      - prints croc's human-manageable pairing code
      - waits as a server

  NODE B:
      python3 tools/characterif.py join <croc-code>

      - starts its own Flask API/Tailcat listener
      - receives A's identity JSON through croc
      - stores A locally
      - connects to A over Tailcat
      - POSTs B's own identity to A's /api/peer/register
      - stores the two-way relationship
      - remains running as a server

After pairing, both machines are peers: each is both a Tailcat server and client.

v0.3a also reserves/implements simple display-facing API entry-points for AI identity,
standard representation, location manifest, and recent chat. These are deliberately
minimal so their internals can be replaced later without changing the URLs.

This is an internal prototype. The Flask API binds to loopback by default.
Do not expose it directly to an untrusted network without authentication.
"""

from __future__ import annotations

import argparse
import atexit
import configparser
import getpass
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import pyaml
from datetime import datetime, timezone
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any, Dict, Optional, List
from urllib import error, request

import tailcat

try:
    from flask import Flask, jsonify, request as flask_request, send_file, render_template_string
except ImportError:
    Flask = None
    jsonify = None
    flask_request = None
    send_file = None
    render_template_string = None


APP_NAME = "characterif"
PROTOCOL = "characterif/1"
API_VERSION = 1
DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_TIMEOUT = 15

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("CHARACTERIF_CONFIG", BASE_DIR / "characterif.conf")).expanduser()

# Shared Heichalot-CMS platform paths live in src/config.py.
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import character_data_dir, platform_data_dir

STATE_DIR = Path.home() / ".config" / APP_NAME
REGISTRY_CACHE = STATE_DIR / "nodes.json"
SESSION_LOG = STATE_DIR / "session.json"
LOCATION_MANIFEST = BASE_DIR / "location-manifest.json"

# Small in-memory display feed. This is deliberately not a durable queue.
# It only gives the visual client something to poll until a later event/stream layer exists.
RECENT_CHAT_LIMIT = 100
RECENT_CHAT: List[Dict[str, Any]] = []
RECENT_CHAT_LOCK = threading.Lock()

# Ambiguous default portrait used when a character is configured without an image.
DEFAULT_PORTRAIT_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">
  <circle cx="48" cy="34" r="16" fill="#94a3b8"/>
  <path d="M16 90c4-24 16-34 32-34s28 10 32 34" fill="#94a3b8"/>
</svg>
"""

CHILDREN = []
CURRENT_TAILCAT_ADDRESS: Optional[str] = None
CURRENT_CROC_CODE: Optional[str] = None
WAN_PAIRING_LOCK = threading.Lock()


# Volatile character connection status shared between local processes.
# CharacterIF is the intended writer; UIs and CMS processes are readers.
PRESENCE_SHM_NAME = "heichalot_characterif_presence_v1"
PRESENCE_SHM_SIZE = 64 * 1024
PRESENCE_HEADER_SIZE = 16
PRESENCE_WRITE_LOCK = threading.Lock()
PRESENCE_SHM_OWNER: Optional[shared_memory.SharedMemory] = None


MOBILE_LANDING_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CharacterIF</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
</head>
<body class="min-h-screen bg-base-200">
  <main class="min-h-screen flex items-center justify-center p-4">
    <section class="card w-full max-w-md bg-base-100 shadow-xl border border-base-300">
      <div class="card-body gap-5">
        <div>
          <h1 class="text-3xl font-bold">CharacterIF</h1>
          <p class="text-base-content/60 mt-1">Mobile LAN interface</p>
        </div>

        <div class="alert alert-info">
          <span>Connected to <strong>{{ node }}</strong> on your local network.</span>
        </div>

        <div class="rounded-box bg-base-200 p-4">
          <div class="text-xs uppercase tracking-wide text-base-content/50">Local web interface</div>
          <div class="font-mono text-sm break-all mt-1">{{ public_url }}</div>
        </div>

        <div class="form-control gap-2">
          <label class="label cursor-pointer justify-start gap-3">
            <input type="radio" name="connection" value="lan" class="radio radio-primary" checked>
            <span class="label-text">Wifi (local LAN)</span>
          </label>
          <label class="label cursor-pointer justify-start gap-3">
            <input type="radio" name="connection" value="wan" class="radio radio-primary">
            <span class="label-text">Mobile Internet (WAN)</span>
          </label>
        </div>

        <div class="card-actions grid grid-cols-2 gap-3 mt-2">
          <button id="continue-button" class="btn btn-primary">Continue</button>
          <button class="btn btn-ghost" onclick="window.close(); history.back();">Quit</button>
        </div>

        <script>
          document.getElementById('continue-button').addEventListener('click', () => {
            const mode = document.querySelector('input[name="connection"]:checked').value;
            if (mode === 'lan') {
              window.location.href = {{ url_for('mobile_home')|tojson }};
              return;
            }

            const remoteUrl = 'https://heichalot.tech/cms/mobile';
            const button = document.getElementById('continue-button');
            button.disabled = true;
            button.textContent = 'Getting Tailcat address…';

            fetch('/api/mobile/wan-pairing', {method: 'POST'})
              .then(async response => {
                const data = await response.json();
                if (!response.ok || !data.ok) {
                  throw new Error(data.error || `HTTP ${response.status}`);
                }
                const proceed = confirm(`Proceed with Tailcat address '${data.tailcat_address}' ?`);
                if (proceed) {
                  // The fragment is kept in the browser and is not sent to
                  // heichalot.tech as part of the HTTP request.
                  window.location.href = remoteUrl + '#tailcat=' + encodeURIComponent(data.tailcat_address);
                }
              })
              .catch(error => alert(`Could not get Tailcat address: ${error.message}`))
              .finally(() => {
                button.disabled = false;
                button.textContent = 'Continue';
              });
          });
        </script>
      </div>
    </section>
  </main>
</body>
</html>
"""


MOBILE_HOME_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CharacterIF - Home</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
  <style>
    html, body { height: 100%; }
    body { overscroll-behavior: none; }
    .safe-bottom { padding-bottom: calc(5.25rem + env(safe-area-inset-bottom)); }
  </style>
</head>
<body class="min-h-full bg-base-200">
  <div class="min-h-full max-w-xl mx-auto bg-base-100 shadow-xl safe-bottom">
    <header class="navbar min-h-16 border-b border-base-300 px-3 sticky top-0 z-20 bg-base-100">
      <div class="flex-1 min-w-0">
        <div>
          <div class="font-bold text-lg leading-tight">CharacterIF</div>
          <div class="text-xs text-base-content/50 truncate">{{ node }}</div>
        </div>
      </div>
      <div class="badge badge-success badge-sm">LAN</div>
    </header>

    <main class="p-4 space-y-5">
      <section>
        <div class="flex items-center justify-between mb-3">
          <div>
            <h1 class="text-xl font-semibold">Characters</h1>
            <p class="text-sm text-base-content/50">Available on this CharacterIF node</p>
          </div>
        </div>

        <div id="characters" class="flex gap-3 overflow-x-auto pb-2 snap-x snap-mandatory">
          <div class="skeleton h-28 w-24 shrink-0"></div>
          <div class="skeleton h-28 w-24 shrink-0"></div>
          <div class="skeleton h-28 w-24 shrink-0"></div>
        </div>
      </section>

      <section class="card bg-base-200 border border-base-300">
        <div class="card-body p-4">
          <h2 class="card-title text-base">Remote viewing</h2>
          <p class="text-sm text-base-content/60">Open the discussion page and use the existing CharacterIF responder.</p>
          <div class="card-actions justify-end mt-2">
            <a class="btn btn-primary btn-sm" href="{{ url_for('mobile_remote_view') }}">Open discussion</a>
          </div>
        </div>
      </section>
    </main>
  </div>

  <nav class="dock border-t border-base-300 bg-base-100 z-30">
    <a class="dock-active" href="{{ url_for('mobile_home') }}" aria-label="Home">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="currentColor" stroke-linejoin="miter" stroke-linecap="butt"><polyline points="1 11 12 2 23 11" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="2"></polyline><path d="m5,13v7c0,1.105.895,2,2,2h10c1.105,0,2-.895,2-2v-7" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></path><line x1="12" y1="22" x2="12" y2="18" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></line></g></svg>
      <span class="dock-label">Home</span>
    </a>
    <a href="{{ url_for('mobile_messages') }}" aria-label="Messages">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="currentColor" stroke-linejoin="miter" stroke-linecap="butt"><polyline points="3 14 9 14 9 17 15 17 15 14 21 14" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="2"></polyline><rect x="3" y="3" width="18" height="18" rx="2" ry="2" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></rect></g></svg>
      <span class="dock-label">Messages</span>
    </a>
    <a href="{{ url_for('mobile_settings') }}" aria-label="Settings">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="currentColor" stroke-linejoin="miter" stroke-linecap="butt"><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></circle><path d="m22,13.25v-2.5l-2.318-.966c-.167-.581-.395-1.135-.682-1.654l.954-2.318-1.768-1.768-2.318.954c-.518-.287-1.073-.515-1.654-.682l-.966-2.318h-2.5l-.966,2.318c-.581.167-1.135.395-1.654.682l-2.318-.954-1.768,1.768.954,2.318c-.287.518-.515,1.073-.682,1.654l-2.318.966v2.5l2.318.966c.167.581.395,1.135.682,1.654l-.954,2.318,1.768,1.768,2.318-.954c.518.287,1.073.515,1.654.682l.966,2.318h2.5l.966-2.318c.581-.167,1.135-.395,1.654-.682l2.318.954,1.768-1.768-.954-2.318c.287-.518.515-1.073.682-1.654l2.318-.966Z" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></path></g></svg>
      <span class="dock-label">Settings</span>
    </a>
  </nav>

<script>
const characterStrip = document.getElementById('characters');

function initials(name) {
  return (name || '?').split(/\s+/).map(part => part[0]).join('').slice(0, 2).toUpperCase();
}

async function loadCharacters() {
  try {
    const response = await fetch('/api/characters');
    const data = await response.json();
    characterStrip.innerHTML = '';

    if (!data.ok || !Array.isArray(data.characters) || data.characters.length === 0) {
      characterStrip.innerHTML = '<div class="text-sm text-base-content/50 py-6">No characters configured.</div>';
      return;
    }

    data.characters.forEach(character => {
      const card = document.createElement('a');
      card.className = 'card bg-base-200 border border-base-300 w-28 shrink-0 snap-start hover:bg-base-300 transition-colors';
      card.href = `{{ url_for('mobile_remote_view') }}?character=${encodeURIComponent(character.name)}`;

      const body = document.createElement('div');
      body.className = 'card-body items-center p-3 gap-2';

      const avatar = document.createElement('div');
      avatar.className = 'avatar placeholder';

      const circle = document.createElement('div');
      circle.className = 'bg-neutral text-neutral-content w-14 rounded-full overflow-hidden';

      const fallback = document.createElement('span');
      fallback.className = 'text-sm';
      fallback.textContent = initials(character.name);
      circle.appendChild(fallback);

      if (character.portrait) {
        const img = document.createElement('img');
        img.src = character.portrait;
        img.alt = character.name;
        img.className = 'w-full h-full object-cover';
        img.onerror = () => img.remove();
        circle.appendChild(img);
      }

      avatar.appendChild(circle);

      const name = document.createElement('div');
      name.className = 'font-medium text-sm text-center truncate w-full';
      name.textContent = character.name;

      const state = document.createElement('div');
      state.className = 'text-[11px] text-base-content/45';
      state.textContent = character.local === false ? 'remote' : 'local';

      body.appendChild(avatar);
      body.appendChild(name);
      body.appendChild(state);
      card.appendChild(body);
      characterStrip.appendChild(card);
    });
  } catch (error) {
    characterStrip.innerHTML = '<div class="text-sm text-error py-6">Unable to load characters.</div>';
  }
}

loadCharacters();
</script>
</body>
</html>
"""


MOBILE_REMOTE_VIEW_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CharacterIF - Remote View</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
  <style>
    html, body { height: 100%; }
    body { overscroll-behavior: none; }
    #messages { min-height: 0; }
    .rv-shell { padding-bottom: calc(4.5rem + env(safe-area-inset-bottom)); }
    #target-fab {
      bottom: calc(5rem + env(safe-area-inset-bottom));
      right: max(1rem, calc((100vw - 36rem) / 2 + 1rem));
      z-index: 40;
    }
  </style>
</head>
<body class="h-full bg-base-200">
  <div class="h-full max-w-xl mx-auto bg-base-100 flex flex-col shadow-xl rv-shell">
    <header class="navbar min-h-16 border-b border-base-300 px-3 shrink-0">
      <div class="flex-1 min-w-0">
        <div>
          <div class="font-bold text-lg leading-tight">Remote View</div>
          <div class="text-xs text-base-content/50 truncate">{{ node }} · discussion</div>
        </div>
      </div>
      <div class="badge badge-success badge-sm">LAN</div>
    </header>

    <main id="messages" class="flex-1 overflow-y-auto p-3 space-y-2">
      <div class="text-center text-sm text-base-content/50 py-8" id="empty-state">
        Choose a character and start the discussion.
      </div>
    </main>

    <div id="status" class="hidden px-3 py-2 text-sm border-t border-base-300 bg-base-200"></div>

    <form id="composer" class="p-3 border-t border-base-300 shrink-0 bg-base-100">
      <textarea id="message" class="textarea textarea-bordered w-full min-h-12 max-h-32 resize-none" rows="1" placeholder="Message…"></textarea>
    </form>
  </div>

  <div id="target-fab" class="fab fab-flower">
    <div id="target-fab-trigger" tabindex="0" role="button" class="btn btn-lg btn-circle btn-secondary tooltip tooltip-left" data-tip="Choose target" aria-label="Choose target">
      <span id="target-fab-trigger-icon" class="inline-flex size-8 items-center justify-center rounded-full overflow-hidden">
        <svg class="size-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/></svg>
      </span>
    </div>
  </div>

  <nav class="dock border-t border-base-300 bg-base-100 z-30">
    <button type="button" id="back-button" aria-label="Back">
      <span class="text-xl">←</span>
      <span class="dock-label">Back</span>
    </button>
    <button type="button" id="dock-target" aria-label="Current target">
      <span id="dock-target-icon" class="inline-flex size-7 items-center justify-center rounded-full bg-base-300 overflow-hidden">
        <svg class="size-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/></svg>
      </span>
      <span id="dock-target-label" class="dock-label">Everyone</span>
    </button>
    <button type="button" id="dock-finish" aria-label="Finish session">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="M5 12.5 9.2 17 19 7"></path>
      </svg>
      <span class="dock-label">Finish</span>
    </button>
  </nav>

<script>
const messages = document.getElementById('messages');
const emptyState = document.getElementById('empty-state');
const composer = document.getElementById('composer');
const messageInput = document.getElementById('message');
const finishButton = document.getElementById('dock-finish');
const transcript = [];
const statusBox = document.getElementById('status');
const requestedCharacter = new URLSearchParams(window.location.search).get('character');
const dockTargetIcon = document.getElementById('dock-target-icon');
const dockTargetLabel = document.getElementById('dock-target-label');
const targetFab = document.getElementById('target-fab');
const targetFabTrigger = document.getElementById('target-fab-trigger');
const targetFabTriggerIcon = document.getElementById('target-fab-trigger-icon');
let characters = [];
let currentTarget = requestedCharacter || 'all';

document.getElementById('back-button').addEventListener('click', () => {
  if (history.length > 1) history.back();
  else window.location.href = `{{ url_for('mobile_home') }}`;
});

function targetIconInto(container, target, sizeClass='w-full h-full') {
  container.innerHTML = '';
  if (target === 'all') {
    container.innerHTML = '<svg class="size-5" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="5" r="2"/><circle cx="12" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><circle cx="19" cy="19" r="2"/></svg>';
    return;
  }
  const img = document.createElement('img');
  img.src = `/api/character/${encodeURIComponent(target)}/portrait`;
  img.alt = target;
  img.className = `${sizeClass} object-cover`;
  img.onerror = () => {
    container.innerHTML = '';
    container.textContent = target.slice(0, 1).toUpperCase();
  };
  container.appendChild(img);
}

function updateTargetDisplay() {
  const label = currentTarget === 'all' ? 'Everyone' : currentTarget;
  dockTargetLabel.textContent = label;
  targetFabTrigger.dataset.tip = label;
  targetFabTrigger.setAttribute('aria-label', `Current target: ${label}. Choose target`);
  targetIconInto(dockTargetIcon, currentTarget);
  targetIconInto(targetFabTriggerIcon, currentTarget);
}

function chooseTarget(target) {
  currentTarget = target;
  updateTargetDisplay();
  targetFabTrigger.blur();
  messageInput.focus();
}

function makeTargetButton(target, label) {
  const wrapper = document.createElement('div');
  wrapper.className = 'tooltip tooltip-left target-action';
  wrapper.dataset.tip = label;

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'btn btn-lg btn-circle target-choice';
  button.setAttribute('aria-label', label);

  const icon = document.createElement('span');
  icon.className = 'inline-flex size-8 items-center justify-center rounded-full overflow-hidden';
  targetIconInto(icon, target);
  button.appendChild(icon);
  button.addEventListener('click', () => chooseTarget(target));
  wrapper.appendChild(button);
  return wrapper;
}

function buildTargetFab() {
  targetFab.querySelectorAll('.target-action').forEach(item => item.remove());
  const targets = [{target: 'all', label: 'Everyone'}, ...characters.map(c => ({target: c.name, label: c.name}))];
  targetFab.classList.toggle('fab-flower', targets.length <= 4);
  targets.forEach(item => targetFab.appendChild(makeTargetButton(item.target, item.label)));
  if (currentTarget !== 'all' && !characters.some(c => c.name === currentTarget)) currentTarget = 'all';
  updateTargetDisplay();
}

function setStatus(text, kind='info') {
  if (!text) {
    statusBox.classList.add('hidden');
    statusBox.textContent = '';
    return;
  }
  statusBox.textContent = text;
  statusBox.classList.remove('hidden');
  statusBox.classList.toggle('text-error', kind === 'error');
  statusBox.classList.toggle('text-base-content/70', kind !== 'error');
}

function addMessage(who, text, mine=false) {
  if (emptyState) emptyState.remove();
  const row = document.createElement('div');
  row.className = `chat ${mine ? 'chat-end' : 'chat-start'}`;

  const header = document.createElement('div');
  header.className = 'chat-header text-xs text-base-content/50 mb-1';
  header.textContent = who;

  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${mine ? 'chat-bubble-primary' : ''} whitespace-pre-wrap`;
  bubble.textContent = text;

  row.appendChild(header);
  row.appendChild(bubble);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
  transcript.push({
    who,
    text,
    mine,
    time: new Date().toISOString()
  });
}

async function loadCharacters() {
  try {
    const response = await fetch('/api/characters');
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.characters) || data.characters.length === 0) {
      characters = [];
      targetFab.querySelectorAll('.target-action').forEach(item => item.remove());
      dockTargetLabel.textContent = 'No characters';
      setStatus('No CharacterIF characters are configured.', 'error');
      return;
    }
    characters = data.characters;
    buildTargetFab();
  } catch (error) {
    characters = [];
    targetFab.querySelectorAll('.target-action').forEach(item => item.remove());
    dockTargetLabel.textContent = 'Unavailable';
    setStatus('Could not load CharacterIF characters.', 'error');
  }
}

composer.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = messageInput.value.trim();
  if (!text || characters.length === 0) return;

  const targets = currentTarget === 'all' ? characters.map(c => c.name) : [currentTarget];
  addMessage('You', text, true);
  messageInput.value = '';
  document.querySelectorAll('.target-choice').forEach(button => button.disabled = true);
  setStatus(currentTarget === 'all' ? 'Everyone is working…' : `${currentTarget} is working…`);

  try {
    for (const character of targets) {
      const response = await fetch(`/api/character/${encodeURIComponent(character)}/respond`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text})
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        throw new Error(`${character}: ${data.error || `HTTP ${response.status}`}`);
      }
      addMessage(data.character || character, data.response || '');
    }
    setStatus('');
  } catch (error) {
    addMessage('System', `Message failed: ${error.message}`);
    setStatus('Connection or character response failed.', 'error');
  } finally {
    document.querySelectorAll('.target-choice').forEach(button => button.disabled = false);
    messageInput.focus();
  }
});

finishButton.addEventListener('click', async () => {
  finishButton.disabled = true;
  setStatus('Saving session…');
  try {
    const response = await fetch('/api/session/finish', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        page: 'remote-view',
        target: currentTarget,
        messages: transcript
      })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    setStatus(`Session saved to ${data.path || 'session.json'}.`);
  } catch (error) {
    setStatus(`Could not save session: ${error.message}`, 'error');
  } finally {
    finishButton.disabled = false;
  }
});

document.getElementById('dock-target').addEventListener('click', () => targetFabTrigger.focus());

messageInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

loadCharacters();
</script>
</body>
</html>
"""


MOBILE_MESSAGES_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CharacterIF - Messages</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
</head>
<body class="min-h-screen bg-base-200">
  <div class="min-h-screen max-w-xl mx-auto bg-base-100 pb-20">
    <header class="navbar border-b border-base-300 px-3">
      <div class="flex-1"><div><div class="font-bold text-lg">Messages</div><div class="text-xs text-base-content/50">{{ node }} · people / IM</div></div></div>
      <div class="badge badge-ghost badge-sm">placeholder</div>
    </header>
    <main class="p-4 space-y-4">
      <div class="alert"><span>This page is intentionally basic for now. It will become the direct person-to-person messaging link to the desktop node.</span></div>
      <div class="chat chat-start"><div class="chat-header text-xs text-base-content/50">Desktop</div><div class="chat-bubble">Messages will appear here.</div></div>
      <div class="join w-full pt-4"><input class="input input-bordered join-item flex-1" placeholder="Message…" disabled><button class="btn btn-primary join-item" disabled>Send</button></div>
    </main>
  </div>
  <nav class="dock border-t border-base-300 bg-base-100 z-30">
    <a href="{{ url_for('mobile_home') }}" aria-label="Home">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="currentColor" stroke-linejoin="miter" stroke-linecap="butt"><polyline points="1 11 12 2 23 11" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="2"></polyline><path d="m5,13v7c0,1.105.895,2,2,2h10c1.105,0,2-.895,2-2v-7" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></path><line x1="12" y1="22" x2="12" y2="18" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></line></g></svg><span class="dock-label">Home</span></a>
    <a class="dock-active" href="{{ url_for('mobile_messages') }}" aria-label="Messages">
      <svg class="size-[1.2em]" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="currentColor" stroke-linejoin="miter" stroke-linecap="butt"><polyline points="3 14 9 14 9 17 15 17 15 14 21 14" fill="none" stroke="currentColor" stroke-miterlimit="10" stroke-width="2"></polyline><rect x="3" y="3" width="18" height="18" rx="2" ry="2" fill="none" stroke="currentColor" stroke-linecap="square" stroke-miterlimit="10" stroke-width="2"></rect></g></svg><span class="dock-label">Messages</span></a>
    <a href="{{ url_for('mobile_settings') }}" aria-label="Settings"><span class="text-xl">⚙</span><span class="dock-label">Settings</span></a>
  </nav>
</body>
</html>
"""


MOBILE_SETTINGS_TEMPLATE = r"""
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>CharacterIF - Settings</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
</head>
<body class="min-h-screen bg-base-200">
  <div class="min-h-screen max-w-xl mx-auto bg-base-100 pb-20">
    <header class="navbar border-b border-base-300 px-3"><div><div class="font-bold text-lg">Settings</div><div class="text-xs text-base-content/50">{{ node }}</div></div></header>
    <main class="p-4"><div class="card bg-base-200 border border-base-300"><div class="card-body"><h2 class="card-title">Settings</h2><p class="text-base-content/60">Placeholder for mobile settings. Nothing here is wired yet.</p></div></div></main>
  </div>
  <nav class="dock border-t border-base-300 bg-base-100 z-30">
    <a href="{{ url_for('mobile_home') }}"><span class="text-xl">⌂</span><span class="dock-label">Home</span></a>
    <a href="{{ url_for('mobile_messages') }}"><span class="text-xl">▣</span><span class="dock-label">Messages</span></a>
    <a class="dock-active" href="{{ url_for('mobile_settings') }}"><span class="text-xl">⚙</span><span class="dock-label">Settings</span></a>
  </nav>
</body>
</html>
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    return cfg


def cfg_get(cfg: configparser.ConfigParser, section: str, option: str, fallback=None):
    try:
        return cfg.get(section, option)
    except (configparser.NoSectionError, configparser.NoOptionError):
        return fallback


def local_node_name(cfg: configparser.ConfigParser) -> str:
    name = cfg_get(cfg, "characterif", "node")
    if name:
        return name.strip()

    for section, option in (
        ("node", "name"),
        ("heichalot", "node"),
        ("server", "node"),
    ):
        name = cfg_get(cfg, section, option)
        if name:
            return name.strip()

    return socket.gethostname().split(".")[0]


def local_user_account_name(cfg: configparser.ConfigParser) -> str:
    """Resolve the human user account name with optional alias."""
    alias = cfg_get(cfg, "characterif", "local_user_account_name")
    if alias:
        return alias.strip()
    return getpass.getuser()


def local_ai_name(cfg: configparser.ConfigParser) -> str:
    """Human/AI identity used in simple chat envelopes."""
    name = cfg_get(cfg, "characterif", "local_user_account_name")
    if name:
        return name.strip()
    return local_node_name(cfg)


def character_section(cfg: configparser.ConfigParser, name: Optional[str] = None) -> str:
    """Return the config section for a character on this node."""
    return f"character-{name or local_ai_name(cfg)}"


def character_cfg_get(cfg: configparser.ConfigParser, option: str, fallback=None, name: Optional[str] = None):
    """Read a character-specific setting from [character-<ai_name>]."""
    return cfg_get(cfg, character_section(cfg, name), option, fallback)


def _character_bool(cfg: configparser.ConfigParser, name: str, option: str, fallback: bool = False) -> bool:
    value = character_cfg_get(cfg, option, name=name)
    if value is None:
        return fallback
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def character_document(cfg: configparser.ConfigParser, name: str) -> Optional[Dict[str, Any]]:
    """Return one configured character, or None if it does not exist."""
    section = character_section(cfg, name)
    if not cfg.has_section(section):
        return None

    configured_name = character_cfg_get(cfg, "name", name, name=name).strip()
    character_type = character_cfg_get(cfg, "type", name=name)
    if character_type is None:
        character_type = ""
    character_type = character_type.strip().lower()
    character_type = "ai" if character_type == "ai" else "human"
    data_dir = character_cfg_get(cfg, "data_dir", "", name=name).strip()

    return {
        "name": configured_name,
        "character_type": character_type,
        "node": local_node_name(cfg),
        "state": "available",
        "portrait": f"/api/character/{configured_name}/portrait",
        "data_dir": data_dir or None,
        "available_remotely": _character_bool(cfg, name, "available_remotely"),
        "exists_remotely": _character_bool(cfg, name, "exists_remotely"),
    }


def character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return all characters configured in [character-<name>] sections."""
    result = []
    for section in cfg.sections():
        if not section.startswith("character-"):
            continue
        name = section[len("character-"):]
        doc = character_document(cfg, name)
        if doc is not None:
            result.append(doc)
    return result


def remote_character_data_dir(name: str, node: str) -> Path:
    """Return the local cache directory for a character learned from another node."""
    def slug(value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._").lower()
        if not cleaned:
            raise ValueError("character/node name does not contain a usable directory name")
        return cleaned

    return platform_data_dir() / f"character-{slug(name)}@{slug(node)}"


def cached_remote_character_documents() -> List[Dict[str, Any]]:
    """Load cached remote character metadata from the platform data directory."""
    result = []
    root = platform_data_dir()
    if not root.is_dir():
        return result

    for data_dir in sorted(root.glob("character-*@*")):
        json_path = data_dir / "character.json"
        conf_path = data_dir / "character.conf"
        if not json_path.is_file() or not conf_path.is_file():
            continue
        try:
            doc = json.loads(json_path.read_text(encoding="utf-8"))
            meta = configparser.ConfigParser()
            meta.read(conf_path, encoding="utf-8")
            if not isinstance(doc, dict):
                continue
            doc = dict(doc)
            doc["local"] = meta.getboolean("address", "local", fallback=False)
            doc["source_node"] = meta.get("address", "node", fallback="") or None
            doc["data_dir"] = str(data_dir.resolve())
            result.append(doc)
        except Exception:
            continue
    return result


def all_character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return local characters followed by locally cached remote characters."""
    local = []
    for doc in character_documents(cfg):
        item = dict(doc)
        item["local"] = True
        local.append(item)
    return local + cached_remote_character_documents()


def character_key(name: str, node: str) -> str:
    """Return the canonical distributed character identity."""
    return f"{name}@{node}"


def load_characters() -> Dict[str, Dict[str, Any]]:
    """Return all characters known to this installation, keyed by name@node."""
    cfg = load_config()
    result: Dict[str, Dict[str, Any]] = {}

    for character in all_character_documents(cfg):
        name = str(character.get("name") or "").strip()
        node = str(character.get("source_node") or character.get("node") or "").strip()
        if not name or not node:
            continue

        key = character_key(name, node)
        result[key] = {
            "name": name,
            "character_type": character.get("character_type"),
            "node": node,
            "local": bool(character.get("local")),
            "portrait": character.get("portrait"),
            "data_dir": character.get("data_dir"),
            "available_remotely": bool(character.get("available_remotely")),
            "exists_remotely": bool(character.get("exists_remotely")),
        }

    return result


def _presence_open_for_write() -> shared_memory.SharedMemory:
    """Create or attach to the local shared-memory presence block."""
    global PRESENCE_SHM_OWNER

    if PRESENCE_SHM_OWNER is not None:
        return PRESENCE_SHM_OWNER

    try:
        shm = shared_memory.SharedMemory(
            name=PRESENCE_SHM_NAME,
            create=True,
            size=PRESENCE_SHM_SIZE,
        )
        shm.buf[:] = b"\0" * PRESENCE_SHM_SIZE
    except FileExistsError:
        shm = shared_memory.SharedMemory(name=PRESENCE_SHM_NAME, create=False)

    PRESENCE_SHM_OWNER = shm
    return shm


def _presence_read_from(shm: shared_memory.SharedMemory) -> Dict[str, Dict[str, Any]]:
    """Read one consistent JSON snapshot from the shared-memory block."""
    for _ in range(5):
        sequence_before = int.from_bytes(shm.buf[0:8], "little")
        if sequence_before & 1:
            time.sleep(0)
            continue

        payload_length = int.from_bytes(shm.buf[8:16], "little")
        if payload_length == 0:
            return {}
        if payload_length > len(shm.buf) - PRESENCE_HEADER_SIZE:
            return {}

        payload = bytes(
            shm.buf[
                PRESENCE_HEADER_SIZE:
                PRESENCE_HEADER_SIZE + payload_length
            ]
        )

        sequence_after = int.from_bytes(shm.buf[0:8], "little")
        if sequence_before != sequence_after or (sequence_after & 1):
            time.sleep(0)
            continue

        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

        return value if isinstance(value, dict) else {}

    return {}


def character_statuses() -> Dict[str, Dict[str, Any]]:
    """
    Return the complete last-known character connection-status snapshot.

    This is the cheap reader intended for UIs. If CharacterIF has not created
    the shared-memory block yet, an empty dictionary is returned.
    """
    if PRESENCE_SHM_OWNER is not None:
        return _presence_read_from(PRESENCE_SHM_OWNER)

    try:
        shm = shared_memory.SharedMemory(name=PRESENCE_SHM_NAME, create=False)
    except FileNotFoundError:
        return {}

    try:
        return _presence_read_from(shm)
    finally:
        shm.close()


def _write_character_statuses(statuses: Dict[str, Dict[str, Any]]) -> None:
    """Replace the complete shared-memory status snapshot."""
    payload = json.dumps(
        statuses,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    if len(payload) > PRESENCE_SHM_SIZE - PRESENCE_HEADER_SIZE:
        raise RuntimeError("character status shared-memory block is full")

    with PRESENCE_WRITE_LOCK:
        shm = _presence_open_for_write()
        sequence = int.from_bytes(shm.buf[0:8], "little")
        if sequence & 1:
            sequence += 1

        # Odd sequence = write in progress. Even sequence = stable snapshot.
        shm.buf[0:8] = (sequence + 1).to_bytes(8, "little")
        shm.buf[PRESENCE_HEADER_SIZE:PRESENCE_HEADER_SIZE + len(payload)] = payload
        shm.buf[8:16] = len(payload).to_bytes(8, "little")
        shm.buf[0:8] = (sequence + 2).to_bytes(8, "little")


def set_character_status(name: str, node: str, status: str) -> Dict[str, Any]:
    """Set one character's last-known connection status."""
    status = status.strip().lower()
    if status not in {"online", "offline"}:
        raise ValueError("status must be 'online' or 'offline'")

    name = name.strip()
    node = node.strip()
    if not name or not node:
        raise ValueError("character name and node are required")

    key = character_key(name, node)

    with PRESENCE_WRITE_LOCK:
        # Read while holding the writer lock, then write the replacement
        # snapshot without re-entering the same lock.
        if PRESENCE_SHM_OWNER is not None:
            statuses = _presence_read_from(PRESENCE_SHM_OWNER)
        else:
            try:
                existing = shared_memory.SharedMemory(
                    name=PRESENCE_SHM_NAME,
                    create=False,
                )
            except FileNotFoundError:
                statuses = {}
            else:
                try:
                    statuses = _presence_read_from(existing)
                finally:
                    existing.close()

        statuses[key] = {
            "name": name,
            "node": node,
            "status": status,
        }

        payload = json.dumps(
            statuses,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(payload) > PRESENCE_SHM_SIZE - PRESENCE_HEADER_SIZE:
            raise RuntimeError("character status shared-memory block is full")

        shm = _presence_open_for_write()
        sequence = int.from_bytes(shm.buf[0:8], "little")
        if sequence & 1:
            sequence += 1
        shm.buf[0:8] = (sequence + 1).to_bytes(8, "little")
        shm.buf[PRESENCE_HEADER_SIZE:PRESENCE_HEADER_SIZE + len(payload)] = payload
        shm.buf[8:16] = len(payload).to_bytes(8, "little")
        shm.buf[0:8] = (sequence + 2).to_bytes(8, "little")

    return dict(statuses[key])


def get_character_status(name: str, node: str) -> Optional[Dict[str, Any]]:
    """Return one character's last-known status, or None if it has no entry."""
    return character_statuses().get(character_key(name.strip(), node.strip()))


def online_characters() -> Dict[str, Dict[str, Any]]:
    """Return only characters whose last-known status is online."""
    return {
        key: value
        for key, value in character_statuses().items()
        if value.get("status") == "online"
    }



def remotely_available_character_documents(cfg: configparser.ConfigParser) -> List[Dict[str, Any]]:
    """Return only local characters that this node explicitly advertises remotely."""
    result = []
    for doc in character_documents(cfg):
        if doc.get("available_remotely"):
            item = dict(doc)
            item["local"] = False
            item["exists_remotely"] = True
            result.append(item)
    return result


def cache_remote_characters(peer: Dict[str, Any], payload: Dict[str, Any]) -> List[Path]:
    """Persist character metadata learned from one remote CharacterIF server."""
    node = str(peer.get("node") or "").strip()
    if not node:
        raise RuntimeError("remote peer has no node name")

    characters = payload.get("characters")
    if not isinstance(characters, list):
        raise RuntimeError("remote server did not return a character list")

    written = []
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "").strip()
        if not name:
            continue

        data_dir = remote_character_data_dir(name, node)
        data_dir.mkdir(parents=True, exist_ok=True)

        (data_dir / "character.json").write_text(
            json.dumps(character, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        meta = configparser.ConfigParser()
        meta["address"] = {
            "node": node,
            "local": "false",
            "api_port": str(peer.get("api_port", DEFAULT_PORT)),
            "tailcat_address": str(peer.get("address") or ""),
            "updated": utcnow(),
        }
        with (data_dir / "character.conf").open("w", encoding="utf-8") as handle:
            meta.write(handle)
        written.append(data_dir)

    return written


def fetch_remote_characters(peer: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the public character index from one Tailcat peer."""
    return tailcat.get_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/",
        timeout=15,
    )


def sync_remote_characters(peer: Dict[str, Any]) -> List[Path]:
    payload = fetch_remote_characters(peer)
    if not payload.get("ok", True):
        raise RuntimeError("remote character index returned an error: " + json.dumps(payload))
    return cache_remote_characters(peer, payload)


def _delayed_sync_remote_characters(peer: Dict[str, Any]) -> None:
    """Best-effort reverse sync after a newly joined peer has started its Flask server."""
    last_error = None
    for _ in range(8):
        time.sleep(1.0)
        try:
            written = sync_remote_characters(peer)
            print(f"\nCached {len(written)} remote character(s) from {peer.get('node')}")
            return
        except Exception as exc:
            last_error = exc
    print(f"\nRemote character sync from {peer.get('node')} deferred: {last_error}")


def character_private_config_path(cfg: configparser.ConfigParser, name: str) -> Optional[Path]:
    """Return the private character.conf path for a local character."""
    data_dir = character_cfg_get(cfg, "data_dir", "", name=name)
    if not data_dir:
        return None
    return Path(data_dir).expanduser() / "character.conf"


def load_character_private_config(cfg: configparser.ConfigParser, name: str) -> configparser.ConfigParser:
    private = configparser.ConfigParser()
    path = character_private_config_path(cfg, name)
    if path is not None and path.is_file():
        private.read(path, encoding="utf-8")
    return private


def cached_remote_character(name: str) -> Optional[Dict[str, Any]]:
    """Return the first cached remote character with this name."""
    for doc in cached_remote_character_documents():
        if str(doc.get("name") or "").casefold() == name.casefold():
            return doc
    return None


def cached_remote_address(name: str) -> Optional[Dict[str, Any]]:
    """Load routing data from a cached remote character's character.conf."""
    doc = cached_remote_character(name)
    if doc is None:
        return None
    data_dir = doc.get("data_dir")
    if not data_dir:
        return None
    meta = configparser.ConfigParser()
    conf_path = Path(str(data_dir)) / "character.conf"
    if not conf_path.is_file():
        return None
    meta.read(conf_path, encoding="utf-8")
    if not meta.has_section("address"):
        return None
    return {
        "node": meta.get("address", "node", fallback=""),
        "address": meta.get("address", "tailcat_address", fallback=""),
        "api_port": meta.getint("address", "api_port", fallback=DEFAULT_PORT),
    }


def respond_as_character(cfg: configparser.ConfigParser, name: str, text: str) -> Dict[str, Any]:
    """Route one synchronous prompt to a local or cached remote character."""
    local_doc = character_document(cfg, name)
    if local_doc is not None:
        if local_doc.get("character_type") != "ai":
            raise RuntimeError(f"character not available: {name}")
        private = load_character_private_config(cfg, name)
        api = private.get("interface", "api", fallback="ollama")
        model = private.get("interface", "model", fallback="gemma3")

        # Lazy import keeps CharacterIF usable for routing-only installations.
        import responder

        response_text = responder.respond(text, api=api, model=model)
        return {
            "ok": True,
            "character": local_doc.get("name", name),
            "node": local_node_name(cfg),
            "local": True,
            "response": response_text,
            "time": utcnow(),
        }

    remote_doc = cached_remote_character(name)
    route = cached_remote_address(name)
    if remote_doc is None or route is None or not route.get("address"):
        raise RuntimeError(f"character not found or has no route: {name}")

    return tailcat.post_json(
        route["address"],
        int(route.get("api_port", DEFAULT_PORT)),
        f"/api/character/{name}/respond",
        {"text": text},
        timeout=180,
    )


def local_ai_document(cfg: configparser.ConfigParser) -> Dict[str, Any]:
    """Return the configured/default local AI participant."""
    name = local_ai_name(cfg)
    doc = character_document(cfg, name)
    if doc is not None and doc.get("character_type") == "ai":
        return doc
    return {
        "name": name,
        "character_type": "ai",
        "node": local_node_name(cfg),
        "state": "available",
        "portrait": f"/api/ai/{name}/portrait",
    }


def portrait_path(cfg: configparser.ConfigParser, name: Optional[str] = None) -> Optional[Path]:
    """Resolve the configured portrait for a character."""
    value = character_cfg_get(cfg, "portrait", name=name)
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def location_document() -> Dict[str, Any]:
    """
    Load location-manifest.json if present; otherwise return the v1 stage shape.

    The fallback preserves the API contract before any artwork exists.
    """
    if LOCATION_MANIFEST.exists():
        try:
            data = json.loads(LOCATION_MANIFEST.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return {
        "location": "skylab-default",
        "dimensions": {"width": 12, "height": 4, "depth": 8},
        "stage": {
            "background": None,
            "floor": None,
            "ceiling": None,
            "left_wall": None,
            "right_wall": None,
        },
        "implemented": False,
    }


def remember_chat_message(message: Dict[str, Any]) -> None:
    item = dict(message)
    item.setdefault("received_time", utcnow())
    with RECENT_CHAT_LOCK:
        RECENT_CHAT.append(item)
        if len(RECENT_CHAT) > RECENT_CHAT_LIMIT:
            del RECENT_CHAT[:-RECENT_CHAT_LIMIT]


def notify_chat_message(cfg: configparser.ConfigParser, sender: str, text: str) -> None:
    """Deliver an incoming chat to the desktop user as a cross-platform notification."""
    try:
        from notifypy import Notify
    except ImportError:
        return

    notification = Notify(default_notification_application_name=APP_NAME)
    notification.title = f"Message from {sender}"
    notification.message = text

    icon = portrait_path(cfg, sender)
    if icon is not None and icon.is_file():
        notification.icon = str(icon)

    try:
        notification.send()
    except Exception:
        pass


def api_port(cfg: configparser.ConfigParser) -> int:
    return int(cfg_get(cfg, "characterif", "api_port", DEFAULT_PORT))


def lan_ip_address() -> str:
    """Best-effort IPv4 address suitable for another device on the local LAN."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects the outbound interface without sending application data.
        sock.connect(("8.8.8.8", 80))
        address = sock.getsockname()[0]
        if address and not address.startswith("127."):
            return address
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if address and not address.startswith("127."):
                return address
    except OSError:
        pass
    return "127.0.0.1"


def mobile_public_url(port: int) -> str:
    return f"http://{lan_ip_address()}:{port}/mobile"


def daemon_url(cfg: configparser.ConfigParser) -> str:
    bind = character_cfg_get(cfg, "api_host", DEFAULT_BIND)
    if bind in ("0.0.0.0", "::"):
        bind = "127.0.0.1"
    return f"http://{bind}:{api_port(cfg)}"


def load_registry() -> Dict[str, Any]:
    ensure_state_dir()
    if not REGISTRY_CACHE.exists():
        return {"version": API_VERSION, "nodes": {}}

    try:
        data = json.loads(REGISTRY_CACHE.read_text())
        data.setdefault("version", API_VERSION)
        data.setdefault("nodes", {})
        return data
    except Exception:
        return {"version": API_VERSION, "nodes": {}}


def save_registry(data: Dict[str, Any]) -> None:
    ensure_state_dir()
    tmp = REGISTRY_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(REGISTRY_CACHE)


def save_peer(doc: Dict[str, Any]) -> None:
    reg = load_registry()
    doc = dict(doc)
    doc["updated"] = utcnow()
    reg["nodes"][doc["node"]] = doc
    save_registry(reg)


def get_peer(node: str) -> Optional[Dict[str, Any]]:
    return load_registry().get("nodes", {}).get(node)


def run_cmd(args, *, timeout=DEFAULT_TIMEOUT, input_text=None, env=None) -> Dict[str, Any]:
    started = time.time()
    try:
        cp = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
        return {
            "ok": cp.returncode == 0,
            "exit_code": cp.returncode,
            "stdout": cp.stdout,
            "stderr": cp.stderr,
            "elapsed": round(time.time() - started, 3),
            "argv": args,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "elapsed": round(time.time() - started, 3),
            "error": f"timeout after {timeout}s",
            "argv": args,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "elapsed": round(time.time() - started, 3),
            "error": f"command not found: {args[0]}",
            "argv": args,
        }


def cleanup_children() -> None:
    for proc in reversed(CHILDREN):
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass


atexit.register(cleanup_children)


def check_dependencies(require_croc=False) -> None:
    missing = []
    if not tailcat.available():
        missing.append("tailcat")
    if require_croc and not shutil.which("croc"):
        missing.append("croc")
    if missing:
        raise RuntimeError("missing command(s): " + ", ".join(missing))



def start_tailcat_listener(port: int) -> str:
    """Compatibility wrapper; Tailcat implementation now lives in tailcat.py."""
    global CURRENT_TAILCAT_ADDRESS
    CURRENT_TAILCAT_ADDRESS = tailcat.start(port)
    return CURRENT_TAILCAT_ADDRESS


def identity_document(cfg: configparser.ConfigParser, address: str) -> Dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "node": local_node_name(cfg),
        "character": local_user_account_name(cfg),
        "address": address,
        "api_port": api_port(cfg),
        "services": {
            "characterif_api": api_port(cfg),
        },
        "created": utcnow(),
    }


def parse_identity_text(text: str) -> Dict[str, Any]:
    """
    Find a characterif identity JSON object in croc's stdout.

    Normally croc's received --text content should be the stdout itself, but
    scanning permits harmless surrounding status text.
    """
    text = text.strip()

    try:
        obj = json.loads(text)
        if obj.get("protocol") == PROTOCOL:
            return obj
    except Exception:
        pass

    # Try line-by-line in case croc includes informational output on stdout.
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            obj = json.loads(line)
            if obj.get("protocol") == PROTOCOL:
                return obj
        except Exception:
            pass

    # Last-resort JSON object scan.
    for m in re.finditer(r"\{.*?\}", text, flags=re.DOTALL):
        try:
            obj = json.loads(m.group(0))
            if obj.get("protocol") == PROTOCOL:
                return obj
        except Exception:
            continue

    raise RuntimeError("received croc text did not contain a characterif/1 identity document")


def start_croc_send_text(payload: str) -> tuple[subprocess.Popen, str]:
    """
    Start `croc send --text ...`, read enough output to obtain its human code,
    and leave croc running until the receiver consumes the text.
    """
    check_dependencies(require_croc=True)

    proc = subprocess.Popen(
        ["croc", "send", "--text", payload],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    CHILDREN.append(proc)

    deadline = time.time() + 20
    lines = []
    code = None

    # Croc has historically printed variants such as "Code is: ...".
    patterns = [
        re.compile(r"code\s+is\s*:\s*(.+?)\s*$", re.I),
        re.compile(r"code\s*:\s*(.+?)\s*$", re.I),
    ]

    while time.time() < deadline:
        if proc.stdout is None:
            break

        line = proc.stdout.readline()
        if line:
            clean = line.rstrip()
            lines.append(clean)

            # Show croc's output verbatim. Earlier we suppressed every line
            # containing "code", which accidentally hid the actual receive
            # command / URL containing the generated secret.
            print(f"[croc] {clean}")

            # Older/current classic form:
            #     Code is: alpha-beta-gamma
            for pattern in patterns:
                m = pattern.search(clean)
                if m:
                    code = m.group(1).strip()
                    break

            # Current Linux/macOS form keeps the secret out of argv:
            #     CROC_SECRET='alpha-beta-gamma' croc
            if not code:
                m = re.search(
                    r"""CROC_SECRET\s*=\s*['\"]([^'\"]+)['\"]""",
                    clean,
                    flags=re.I,
                )
                if m:
                    code = m.group(1).strip()

            # Classic receive command:
            #     croc alpha-beta-gamma
            if not code:
                m = re.search(r"\bcroc\s+([^\s]+)\s*$", clean)
                if m:
                    candidate = m.group(1).strip().strip("'\"")
                    if not candidate.startswith("-"):
                        code = candidate

            # Browser form:
            #     https://getcroc.com/?code=alpha-beta-gamma
            if not code:
                m = re.search(r"[?&]code=([^&\s]+)", clean, flags=re.I)
                if m:
                    from urllib.parse import unquote
                    code = unquote(m.group(1)).strip()

            if code:
                return proc, code
        elif proc.poll() is not None:
            break
        else:
            time.sleep(0.05)

    raise RuntimeError(
        "croc did not print a pairing code"
        + (("\nOutput:\n" + "\n".join(lines)) if lines else "")
    )


def receive_croc_text(code: str, timeout: int = 300) -> str:
    """
    Receive croc text using CROC_SECRET in the child environment.

    This is intentionally the first thing to try. Python's subprocess API
    explicitly supports setting an environment for a spawned process.

    If the installed croc build does not accept CROC_SECRET for receive mode,
    we fall back to passing the code as an argument.
    """
    check_dependencies(require_croc=True)

    env = os.environ.copy()
    env["CROC_SECRET"] = code

    result = run_cmd(["croc", "--yes"], timeout=timeout, env=env)
    if result["ok"] and result.get("stdout", "").strip():
        return result["stdout"]

    # Compatibility fallback. If the environment-variable invocation fails,
    # try croc's ordinary positional-code form.
    fallback = run_cmd(["croc", "--yes", code], timeout=timeout)
    if fallback["ok"] and fallback.get("stdout", "").strip():
        return fallback["stdout"]

    raise RuntimeError(
        "could not receive croc text.\n"
        f"CROC_SECRET attempt stderr: {result.get('stderr','').strip()}\n"
        f"argument fallback stderr: {fallback.get('stderr','').strip()}"
    )


def find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_port(port: int, timeout=8) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def post_json(url: str, payload: Dict[str, Any], timeout=15) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def register_with_remote_peer(peer: Dict[str, Any], me: Dict[str, Any]) -> Dict[str, Any]:
    """Register through the optional Tailcat transport driver."""
    return tailcat.post_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/api/peer/register",
        me,
        timeout=15,
    )


def send_chat_to_remote_peer(peer: Dict[str, Any], envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Send chat through the optional Tailcat transport driver."""
    return tailcat.post_json(
        peer["address"],
        int(peer.get("api_port", DEFAULT_PORT)),
        "/api/chat-text",
        envelope,
        timeout=15,
    )


def make_app() -> "Flask":
    if Flask is None:
        raise RuntimeError("Flask is not installed. Try: pip install flask")

    cfg = load_config()
    app = Flask(APP_NAME)

    @app.get("/api/status")
    def api_status():
        return jsonify({
            "ok": True,
            "service": APP_NAME,
            "protocol": PROTOCOL,
            "api_version": API_VERSION,
            "node": local_node_name(cfg),
            "character": local_user_account_name(cfg),
            "tailcat_address": CURRENT_TAILCAT_ADDRESS,
            "time": utcnow(),
        })

    # --- Character / AI display API --------------------------------------


    @app.get("/mobile")
    def mobile_landing():
        port = api_port(cfg)
        return render_template_string(
            MOBILE_LANDING_TEMPLATE,
            node=local_node_name(cfg),
            public_url=mobile_public_url(port),
            croc_code=CURRENT_CROC_CODE,
        )

    @app.post("/api/mobile/wan-pairing")
    def mobile_wan_pairing():
        """Return this node's Tailcat address for the hosted WAN browser."""
        try:
            with WAN_PAIRING_LOCK:
                address = CURRENT_TAILCAT_ADDRESS or start_tailcat_listener(api_port(cfg))
                me = identity_document(cfg, address)

            return jsonify({
                "ok": True,
                "tailcat_address": address,
                "api_port": me["api_port"],
                "node": me["node"],
            })
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

    @app.get("/mobile/home")
    @app.get("/mobile/app")
    def mobile_home():
        return render_template_string(
            MOBILE_HOME_TEMPLATE,
            node=local_node_name(cfg),
        )

    @app.get("/mobile/remote-view")
    def mobile_remote_view():
        return render_template_string(
            MOBILE_REMOTE_VIEW_TEMPLATE,
            node=local_node_name(cfg),
        )

    @app.get("/mobile/messages")
    def mobile_messages():
        return render_template_string(
            MOBILE_MESSAGES_TEMPLATE,
            node=local_node_name(cfg),
        )

    @app.get("/mobile/settings")
    def mobile_settings():
        return render_template_string(
            MOBILE_SETTINGS_TEMPLATE,
            node=local_node_name(cfg),
        )

    @app.get("/")
    def index():
        # The public CharacterIF index is intentionally just JSON.  Only local
        # characters explicitly marked available_remotely are advertised.
        return jsonify({
            "ok": True,
            "node": local_node_name(cfg),
            "characters": remotely_available_character_documents(cfg),
        })

    @app.get("/api/characters")
    def api_characters():
        return jsonify({"ok": True, "characters": all_character_documents(cfg)})

    @app.get("/api/character/<name>")
    def api_character(name):
        character = character_document(cfg, name)
        if character is None:
            return jsonify({"ok": False, "error": "character not found", "name": name}), 404
        return jsonify({"ok": True, **character})

    @app.get("/api/ais")
    def api_ais():
        ais = [c for c in all_character_documents(cfg) if c.get("character_type") == "ai"]
        return jsonify({"ok": True, "ais": ais})

    @app.get("/api/ai/<name>")
    def api_ai(name):
        ai = character_document(cfg, name)
        if ai is None or ai.get("character_type") != "ai":
            return jsonify({"ok": False, "error": "ai not found", "name": name}), 404
        return jsonify({"ok": True, **ai})

    @app.get("/api/character/<name>/portrait")
    @app.get("/api/ai/<name>/portrait")
    @app.get("/api/ai/<name>/representation/standard")
    def api_character_portrait(name):
        character = character_document(cfg, name)
        if character is None:
            return jsonify({"ok": False, "error": "character not found", "name": name}), 404

        path = portrait_path(cfg, name)
        if path is None:
            return jsonify({
                "ok": False,
                "error": "portrait not configured",
                "name": name,
                "config_key": f"[{character_section(cfg, name)}] portrait",
            }), 501
        if not path.is_file():
            return jsonify({
                "ok": False,
                "error": "portrait file not found",
                "name": name,
                "path": str(path),
            }), 404
        return send_file(path)

    @app.post("/api/character/<name>/respond")
    def api_character_respond(name):
        body = flask_request.get_json(silent=True) or {}
        text_value = body.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            return jsonify({"ok": False, "error": "text is required"}), 400

        try:
            result = respond_as_character(cfg, name, text_value)
            return jsonify(result)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "name": name}), 502


    @app.post("/api/session/finish")
    def api_session_finish():
        """Append a lightweight mobile Remote View snapshot to session.json."""
        body = flask_request.get_json(silent=True) or {}
        messages = body.get("messages")
        if not isinstance(messages, list):
            return jsonify({"ok": False, "error": "messages must be a list"}), 400

        ensure_state_dir()
        payload = {
            "version": 1,
            "sessions": [],
        }
        if SESSION_LOG.is_file():
            try:
                existing = json.loads(SESSION_LOG.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            except Exception:
                # Keep this endpoint intentionally forgiving during the prototype phase.
                payload = {"version": 1, "sessions": []}

        sessions = payload.setdefault("sessions", [])
        if not isinstance(sessions, list):
            sessions = []
            payload["sessions"] = sessions

        session = {
            "finished": utcnow(),
            "node": local_node_name(cfg),
            "page": body.get("page") or "remote-view",
            "target": body.get("target") or "all",
            "messages": messages,
        }
        sessions.append(session)

        tmp = SESSION_LOG.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(SESSION_LOG)

        return jsonify({
            "ok": True,
            "saved": True,
            "path": str(SESSION_LOG),
            "messages": len(messages),
        })


    @app.get("/api/location")
    def api_location():
        return jsonify({"ok": True, **location_document()})

    @app.get("/api/chat/recent")
    def api_chat_recent():
        try:
            limit = int(flask_request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, RECENT_CHAT_LIMIT))
        with RECENT_CHAT_LOCK:
            messages = list(RECENT_CHAT[-limit:])
        return jsonify({"ok": True, "messages": messages})

    # --- Existing peer/node API -------------------------------------------

    @app.get("/api/nodes")
    def api_nodes():
        return jsonify(load_registry())

    @app.get("/api/nodes/<node>")
    def api_node(node):
        peer = get_peer(node)
        if not peer:
            return jsonify({"ok": False, "error": "node not found", "node": node}), 404
        return jsonify({"ok": True, "node": peer})

    @app.post("/api/peer/register")
    def api_peer_register():
        body = flask_request.get_json(silent=True) or {}

        if body.get("protocol") != PROTOCOL:
            return jsonify({"ok": False, "error": "unsupported protocol"}), 400
        if not body.get("node") or not body.get("address"):
            return jsonify({"ok": False, "error": "node and address are required"}), 400

        save_peer(body)

        # The joining node starts its Flask server immediately after this
        # registration returns, so retry its character index in the background.
        threading.Thread(
            target=_delayed_sync_remote_characters,
            args=(dict(body),),
            daemon=True,
        ).start()

        mine = None
        if CURRENT_TAILCAT_ADDRESS:
            mine = identity_document(cfg, CURRENT_TAILCAT_ADDRESS)

        print(f"\nPeer registered: {body['node']}")
        print(f"  address: {body['address'][:45]}{'...' if len(body['address']) > 45 else ''}")

        return jsonify({
            "ok": True,
            "registered": body["node"],
            "peer": mine,
        })

    @app.post("/api/chat-text")
    def api_chat_text():
        body = flask_request.get_json(silent=True) or {}

        text_value = body.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            return jsonify({"ok": False, "error": "text is required"}), 400

        sender_node = body.get("from_node") or "unknown-node"
        sender_character = body.get("from_character") or body.get("from_ai") or "user"
        target_character = body.get("to_character") or body.get("to_ai") or sender_character
        target_node = body.get("to_node") or local_node_name(cfg)

        # Keep a small display-oriented feed as well as printing to console.
        # This is not intended to replace durable chat storage/queueing.
        remembered = dict(body)
        remembered.setdefault("from_node", sender_node)
        remembered.setdefault("from_character", sender_character)
        remembered.setdefault("to_node", target_node)
        remembered.setdefault("to_character", target_character)
        remember_chat_message(remembered)

        print("\nCHAT")
        print(f"  from node:      {sender_node}")
        print(f"  from character: {sender_character}")
        print(f"  to node:        {target_node}")
        print(f"  to character:   {target_character}")
        print(f"  text:           {text_value}")

        if (
            target_node == local_node_name(cfg)
            and target_character.casefold() == local_user_account_name(cfg).casefold()
        ):
            notify_chat_message(cfg, sender_character, text_value)

        return jsonify({
            "ok": True,
            "received": True,
            "node": local_node_name(cfg),
            "character": local_user_account_name(cfg),
            "time": utcnow(),
        })

    @app.post("/api/ping")
    def api_ping():
        body = flask_request.get_json(silent=True) or {}
        node = body.get("node")
        timeout = int(body.get("timeout", DEFAULT_TIMEOUT))
        peer = get_peer(node) if node else None

        if not peer or not peer.get("address"):
            return jsonify({"ok": False, "error": "node/address not found", "node": node}), 404

        result = tailcat.ping(
            peer["address"],
            until_direct=bool(body.get("until_direct")),
            timeout=timeout,
        )
        result["node"] = node
        return jsonify(result), (200 if result["ok"] else 502)

    @app.post("/api/run")
    def api_run():
        body = flask_request.get_json(silent=True) or {}
        node = body.get("node")
        command = body.get("command")
        timeout = int(body.get("timeout", 60))

        if not node or not command:
            return jsonify({"ok": False, "error": "node and command are required"}), 400

        peer = get_peer(node)
        if not peer or not peer.get("address"):
            return jsonify({"ok": False, "error": "node/address not found", "node": node}), 404

        result = tailcat.run_remote(
            peer["address"],
            command,
            timeout=timeout,
        )
        result["node"] = node
        result["command"] = command
        return jsonify(result), (200 if result["ok"] else 502)

    return app


def run_flask(cfg: configparser.ConfigParser, bind=None, port=None) -> int:
    bind = bind or character_cfg_get(cfg, "api_host", DEFAULT_BIND)
    port = port or api_port(cfg)

    app = make_app()
    print(f"\n{APP_NAME}: node={local_node_name(cfg)}")
    print(f"{APP_NAME}: api=http://{bind}:{port}")
    print(f"{APP_NAME}: registry={REGISTRY_CACHE}")
    app.run(host=bind, port=port, threaded=True, use_reloader=False)
    return 0


def run_mobile_web(cfg: configparser.ConfigParser, bind: Optional[str] = None,
                   port: Optional[int] = None, open_browser: bool = False) -> int:
    """Run the LAN-only mobile-first CharacterIF web interface."""
    bind = bind or "0.0.0.0"
    port = port or api_port(cfg)
    url = mobile_public_url(port)

    # WAN mode needs the same Tailcat listener used by the normal server/start paths.
    # Starting it here also makes the address visible immediately for diagnostics.
    address = CURRENT_TAILCAT_ADDRESS or start_tailcat_listener(port)

    print(f"\n{APP_NAME}: mobile LAN web interface")
    print(f"Local web interface:\n  {url}")
    print(f"Tailcat address:\n  {address}")
    print("\nOpen that address on a phone connected to the same LAN.")
    print("QR code, connection/busy state, and remote mobile access are intentionally deferred.")

    if open_browser:
        local_url = f"http://127.0.0.1:{port}/mobile"
        threading.Timer(0.7, lambda: webbrowser.open(local_url)).start()

    app = make_app()
    app.run(host=bind, port=port, threaded=True, use_reloader=False)
    return 0


def api_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = load_config()
    url = daemon_url(cfg) + path
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(body)
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}", "body": body}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "url": url}


def print_result(obj: Any, raw=False) -> int:
    if raw and isinstance(obj, dict):
        if obj.get("stdout"):
            sys.stdout.write(obj["stdout"])
        if obj.get("stderr"):
            sys.stderr.write(obj["stderr"])
        return 0 if obj.get("ok") else 1

    print(json.dumps(obj, indent=2))
    return 0 if not isinstance(obj, dict) or obj.get("ok", True) else 1


def cmd_start(args) -> int:
    global CURRENT_CROC_CODE

    cfg = load_config()
    port = args.port or api_port(cfg)

    check_dependencies(require_croc=True)
    address = start_tailcat_listener(port)
    me = identity_document(cfg, address)
    payload = json.dumps(me, separators=(",", ":"))

    print(f"\ncharacterif node: {me['node']}")
    print("Tailcat listener: ready")
    print(f"Tailcat address: {address}")

    _, code = start_croc_send_text(payload)
    CURRENT_CROC_CODE = code

    print("\nPAIRING CODE")
    print(f"  {code}")
    print("\nGive that croc code to the second machine and run:")
    print(f"  python3 tools/characterif.py join '{code}'")
    print("\nWaiting for peer registration...")

    return run_flask(cfg, bind=args.bind, port=port)


def cmd_join(args) -> int:
    cfg = load_config()
    port = args.port or api_port(cfg)

    check_dependencies(require_croc=True)

    # B must become a server too before telling A about itself.
    address = start_tailcat_listener(port)
    me = identity_document(cfg, address)

    print(f"\ncharacterif node: {me['node']}")
    print("Tailcat listener: ready")
    print("Receiving first peer address through croc...")

    received = receive_croc_text(args.code, timeout=args.croc_timeout)
    peer = parse_identity_text(received)

    if peer["node"] == me["node"]:
        raise RuntimeError(f"peer has same node name as this machine: {me['node']}")

    save_peer(peer)

    print(f"Received peer: {peer['node']}")
    print("Connecting back over Tailcat and registering this node...")

    reply = register_with_remote_peer(peer, me)
    if not reply.get("ok"):
        raise RuntimeError("peer registration failed: " + json.dumps(reply))

    # A may return its current identity. Save it because it is authoritative.
    returned_peer = reply.get("peer")
    if isinstance(returned_peer, dict) and returned_peer.get("node") and returned_peer.get("address"):
        save_peer(returned_peer)

    print("\nPAIRING COMPLETE")
    print(f"  {me['node']} <-> {peer['node']}")
    print("Both nodes now have each other's Tailcat address.")

    print(f"Fetching characters from {peer['node']}...")
    written = sync_remote_characters(peer)
    print(f"Cached {len(written)} remote character(s).")
    for path in written:
        print(f"  {path}")

    return run_flask(cfg, bind=args.bind, port=port)



def _setup_prompt_value(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value if value else default


def _setup_prompt_bool(label: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        value = input(f"{label} {suffix}: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "1", "true", "on"}:
            return True
        if value in {"n", "no", "0", "false", "off"}:
            return False
        print("Please answer y or n.")


def _parse_bool_arg(value: str) -> bool:
    text = value.strip().lower()
    if text in {"y", "yes", "1", "true", "on"}:
        return True
    if text in {"n", "no", "0", "false", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _setup_config_bool(
    cfg: configparser.ConfigParser,
    option: str,
    fallback: bool,
) -> bool:
    try:
        return cfg.getboolean("characterif", option, fallback=fallback)
    except ValueError:
        return fallback


def _write_setup_config(cfg: configparser.ConfigParser) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as handle:
        cfg.write(handle)
    print(f"\nConfiguration written to:\n  {CONFIG_PATH.resolve()}")


def setup_character(args) -> int:
    """Create or update one CharacterIF character configuration."""
    cfg = load_config()

    name = (args.name or _setup_prompt_value("Character name")).strip()
    if not name:
        raise RuntimeError("character name is required")

    is_account_owner = name.casefold() == local_user_account_name(cfg).casefold()
    if args.character_type is not None:
        is_ai = args.character_type == "ai"
    else:
        is_ai = _setup_prompt_bool("Is this an AI character?", not is_account_owner)

    portrait_text = args.portrait
    if not portrait_text:
        portrait_text = _setup_prompt_value("Portrait image filename (blank for default graphic)")
    portrait_source = Path(portrait_text).expanduser() if portrait_text.strip() else None
    if portrait_source is not None and not portrait_source.is_file():
        raise RuntimeError(f"portrait file not found: {portrait_source}")

    available_remotely = (
        args.available_remotely
        if args.available_remotely is not None
        else _setup_prompt_bool("Available remotely?", False)
    )
    exists_remotely = (
        args.exists_remotely
        if args.exists_remotely is not None
        else _setup_prompt_bool("Exists remotely?", False)
    )
    interface_api = (args.interface_api or _setup_prompt_value("Interface API", "ollama")).strip()
    interface_model = (args.model or _setup_prompt_value("Model", "gemma3")).strip()

    if character_data_dir is None:
        raise RuntimeError("cannot import character_data_dir from src/config.py")

    data_dir = character_data_dir(name)
    data_dir.mkdir(parents=True, exist_ok=True)

    portrait_target = data_dir / "portrait.svg"
    if portrait_source is None:
        portrait_target.write_text(DEFAULT_PORTRAIT_SVG)
    else:
        portrait_target = data_dir / portrait_source.name
        if portrait_source.resolve() != portrait_target.resolve():
            shutil.copy2(portrait_source, portrait_target)

    section = f"character-{name}"
    if not cfg.has_section(section):
        cfg.add_section(section)

    cfg.set(section, "name", name)
    cfg.set(section, "type", "ai" if is_ai else "")
    cfg.set(section, "portrait", str(portrait_target.resolve()))
    cfg.set(section, "data_dir", str(data_dir.resolve()))
    cfg.set(section, "available_remotely", "true" if available_remotely else "false")
    cfg.set(section, "exists_remotely", "true" if exists_remotely else "false")

    # Private, machine-local implementation details. This file is never used
    # to build the public character document returned over CharacterIF.
    private_path = data_dir / "character.conf"
    private = configparser.ConfigParser()
    if private_path.is_file():
        private.read(private_path, encoding="utf-8")
    if not private.has_section("address"):
        private.add_section("address")
    if not private.has_section("interface"):
        private.add_section("interface")
    private.set("address", "node", local_node_name(cfg))
    private.set("address", "local", "true")
    private.set("interface", "api", interface_api)
    private.set("interface", "model", interface_model)
    with private_path.open("w", encoding="utf-8") as handle:
        private.write(handle)

    _write_setup_config(cfg)

    print("\nCharacter configured")
    print(f"  name:               {name}")
    print(f"  section:            [{section}]")
    print(f"  character type:     {'ai' if is_ai else 'human'}")
    print(f"  data:               {data_dir.resolve()}")
    print(f"  portrait:           {portrait_target.resolve()}")
    print(f"  available remotely: {'yes' if available_remotely else 'no'}")
    print(f"  exists remotely:    {'yes' if exists_remotely else 'no'}")
    print(f"  interface api:      {interface_api}")
    print(f"  model:              {interface_model}")
    print(f"  private config:     {(data_dir / 'character.conf').resolve()}")
    return 0


def setup_lan() -> int:
    """
    Configure CharacterIF's local-network identity and LAN discovery.

    Existing config.ini sections and unrelated options are preserved.
    The historical [characterif] section name is retained for compatibility.
    """
    cfg = load_config()
    if not cfg.has_section("characterif"):
        cfg.add_section("characterif")

    current_user_account = cfg_get(cfg, "characterif", "local_user_account_name", local_user_account_name(cfg))
    current_node = cfg_get(cfg, "characterif", "node", local_node_name(cfg))
    current_port = str(api_port(cfg))
    current_lan = _setup_config_bool(cfg, "lan", True)

    print("\nCharacterIF LAN setup\n")

    user_account_name = _setup_prompt_value("User account name", current_user_account)
    node_name = _setup_prompt_value("Node name", current_node)

    while True:
        port_text = _setup_prompt_value("API port", current_port)
        try:
            port = int(port_text)
            if not 1 <= port <= 65535:
                raise ValueError
            break
        except ValueError:
            print("Please enter a TCP port between 1 and 65535.")

    lan_enabled = _setup_prompt_bool(
        "Enable automatic local LAN discovery?",
        current_lan,
    )

    try:
        import zeroconf  # noqa: F401
        zeroconf_ok = True
    except ImportError:
        zeroconf_ok = False

    print("\nLAN dependency check")
    print(f"  zeroconf: {'installed' if zeroconf_ok else 'not installed'}")

    if not _setup_prompt_bool("\nSave LAN configuration?", True):
        print("Configuration not changed.")
        return 0

    cfg.set("characterif", "local_user_account_name", user_account_name)
    cfg.set("characterif", "node", node_name)
    cfg.set("characterif", "api_port", str(port))
    cfg.set("characterif", "lan", "true" if lan_enabled else "false")
    section = f"character-{user_account_name}"
    if not cfg.has_section(section):
        cfg.add_section(section)

    _write_setup_config(cfg)

    if lan_enabled and not zeroconf_ok:
        print("\nLAN discovery is enabled, but zeroconf is not installed.")
        print("Install it with:")
        print("  pip install zeroconf")

    return 0


def setup_remote() -> int:
    """
    Configure explicit online/Tailcat participation.

    Running this setup does not itself start Tailcat or contact the Internet.
    It only records whether online operation is enabled.
    """
    cfg = load_config()
    if not cfg.has_section("characterif"):
        cfg.add_section("characterif")

    current_online = _setup_config_bool(cfg, "online", False)

    print("\nCharacterIF remote setup\n")
    print("Remote mode uses Tailcat and Croc and may communicate over the Internet.")
    print("LAN-only operation does not require remote mode.\n")

    online_enabled = _setup_prompt_bool(
        "Enable online/Tailcat networking?",
        current_online,
    )

    tailcat_ok = tailcat.available()
    croc_ok = shutil.which("croc") is not None

    print("\nRemote dependency check")
    print(f"  tailcat: {'installed' if tailcat_ok else 'not installed'}")
    print(f"  croc:    {'installed' if croc_ok else 'not installed'}")

    if not _setup_prompt_bool("\nSave remote configuration?", True):
        print("Configuration not changed.")
        return 0

    cfg.set(
        "characterif",
        "online",
        "true" if online_enabled else "false",
    )
    _write_setup_config(cfg)

    if online_enabled and not tailcat_ok:
        print("\nOnline networking is enabled, but tailcat is not installed.")

    if online_enabled and not croc_ok:
        print("\nOnline bootstrap is enabled, but croc is not installed.")

    return 0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Heichalot CharacterIF node interface")
    p.add_argument(
        "--setup",
        choices=("lan", "remote"),
        help="configure LAN or remote networking",
    )
    p.add_argument(
        "--setup-character",
        action="store_true",
        help="create or update a character; prompts for missing values",
    )
    p.add_argument(
        "--character-list-json",
        action="store_true",
        help="print all known characters as JSON and exit",
    )
    p.add_argument(
        "--character-status-json",
        action="store_true",
        help="print the shared-memory character connection statuses as JSON and exit",
    )
    p.add_argument("--name", help="character name")
    p.add_argument(
        "--character-type", "--type",
        dest="character_type",
        choices=("ai", "human"),
        help="whether this is an AI or a biological-human character",
    )
    p.add_argument("--portrait", help="portrait image filename")
    p.add_argument("--api", dest="interface_api", help="local responder API (default: ollama)")
    p.add_argument("--model", help="local responder model (default: gemma3)")
    p.add_argument(
        "--available_remotely", "--available-remotely",
        dest="available_remotely",
        type=_parse_bool_arg,
        help="whether this character can be reached remotely (true/false)",
    )
    p.add_argument(
        "--exists_remotely", "--exists-remotely",
        dest="exists_remotely",
        type=_parse_bool_arg,
        help="whether this character exists on a remote node (true/false)",
    )
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("start", help="start first node and print a croc pairing code")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)

    s = sub.add_parser("join", help="join the first node using its croc pairing code")
    s.add_argument("code")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)
    s.add_argument("--croc-timeout", type=int, default=300)


    s = sub.add_parser("web", help="run the mobile-first LAN web interface")
    s.add_argument("--bind", default="0.0.0.0")
    s.add_argument("--port", type=int)
    s.add_argument("--open", action="store_true", help="open the landing page in the desktop browser")

    s = sub.add_parser("server", help="run API/Tailcat server without croc pairing")
    s.add_argument("--bind")
    s.add_argument("--port", type=int)

    sub.add_parser("status", help="show running daemon status")
    sub.add_parser("nodes", help="list locally known peers")

    s = sub.add_parser("sync-characters", help="fetch and cache characters from a known peer")
    s.add_argument("node")

    s = sub.add_parser("node", help="show one locally known peer")
    s.add_argument("node")

    s = sub.add_parser("ping", help="Tailcat ping a known peer")
    s.add_argument("node")
    s.add_argument("--until-direct", action="store_true")
    s.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)

    s = sub.add_parser("run", help="run a command using Tailcat SSH")
    s.add_argument("node")
    s.add_argument("remote_command", nargs=argparse.REMAINDER)
    s.add_argument("--timeout", type=int, default=60)

    s = sub.add_parser("chat", help="send simple text from one character to another")
    s.add_argument("node")
    s.add_argument("--chat-text", required=True)
    s.add_argument(
        "--from-character", "--ai-name",
        dest="from_character",
        help="sending character name; defaults to 'user'",
    )
    s.add_argument(
        "--to-character", "--to-ai",
        dest="to_character",
        help="target character name; defaults to the sending character",
    )

    s = sub.add_parser("respond", help="request one synchronous response from a character")
    s.add_argument("character")
    s.add_argument("--text", required=True)

    s = sub.add_parser("ssh", help="open interactive Tailcat SSH to a known peer")
    s.add_argument("node")
    s.add_argument("ssh_args", nargs=argparse.REMAINDER)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.setup == "lan":
        return setup_lan()

    if args.setup == "remote":
        return setup_remote()

    if args.setup_character:
        return setup_character(args)

    if args.character_list_json:
        print(json.dumps(load_characters(), indent=2, sort_keys=True))
        return 0

    if args.character_status_json:
        print(json.dumps(character_statuses(), indent=2, sort_keys=True))
        return 0

    if not args.command:
        parser.print_help()
        return 2

    cfg = load_config()

    try:
        if args.command == "start":
            return cmd_start(args)

        if args.command == "join":
            return cmd_join(args)

        if args.command == "web":
            return run_mobile_web(cfg, bind=args.bind, port=args.port, open_browser=args.open)

        if args.command == "server":
            port = args.port or api_port(cfg)
            start_tailcat_listener(port)
            return run_flask(cfg, bind=args.bind, port=port)

        if args.command == "status":
            return print_result(api_request("GET", "/api/status"))

        if args.command == "nodes":
            return print_result(api_request("GET", "/api/nodes"))

        if args.command == "sync-characters":
            peer = get_peer(args.node)
            if not peer or not peer.get("address"):
                print(f"node {args.node!r} not found in {REGISTRY_CACHE}", file=sys.stderr)
                return 1
            written = sync_remote_characters(peer)
            print(f"Cached {len(written)} remote character(s) from {args.node}.")
            for path in written:
                print(path)
            return 0

        if args.command == "node":
            return print_result(api_request("GET", f"/api/nodes/{args.node}"))

        if args.command == "ping":
            return print_result(api_request("POST", "/api/ping", {
                "node": args.node,
                "until_direct": args.until_direct,
                "timeout": args.timeout,
            }), raw=True)

        if args.command == "run":
            remote_command = " ".join(args.remote_command).strip()
            if not remote_command:
                parser.error("run requires a remote command")
            return print_result(api_request("POST", "/api/run", {
                "node": args.node,
                "command": remote_command,
                "timeout": args.timeout,
            }), raw=True)

        if args.command == "chat":
            peer = get_peer(args.node)
            if not peer or not peer.get("address"):
                print(f"node {args.node!r} not found in {REGISTRY_CACHE}", file=sys.stderr)
                return 1

            sender_character = args.from_character or "user"
            target_character = args.to_character or sender_character

            envelope = {
                "protocol": PROTOCOL,
                "type": "chat-text",
                "from_node": local_node_name(cfg),
                "from_character": sender_character,
                "to_node": args.node,
                "to_character": target_character,
                "text": args.chat_text,
                "time": utcnow(),
            }

            result = send_chat_to_remote_peer(peer, envelope)
            return print_result(result)

        if args.command == "respond":
            return print_result(respond_as_character(cfg, args.character, args.text))

        if args.command == "ssh":
            result = api_request("GET", f"/api/nodes/{args.node}")
            if not result.get("ok"):
                return print_result(result)

            address = result["node"].get("address")
            if not address:
                print(f"node {args.node!r} has no Tailcat address", file=sys.stderr)
                return 1

            return tailcat.ssh(address, args.ssh_args)

    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:
        print(f"{APP_NAME}: ERROR: {exc}", file=sys.stderr)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
