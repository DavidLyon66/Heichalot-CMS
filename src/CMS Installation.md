# Heichalot CMS — Desktop Installation

## Prerequisites

- Python 3.10+
- pip
- Git (optional, for version tracking)

---

## 1. Linux

### 1.1 System packages (GUI backend)

The desktop app uses **pywebview** with a Qt or GTK backend. Install the system-level dependencies:

```bash
# Qt backend (recommended — best looking)
sudo apt install python3-pyqt5 python3-pyqt5.qtwebengine

# OR GTK backend (fallback)
sudo apt install python3-gi python3-gi-cairo gir1.2-webkit2-4.1
```

> Only **one** backend is needed. Qt is preferred; install GTK only if Qt does not work on your system.

### 1.2 Python dependencies

From the project root:

```bash
pip install -e ".[desktop]"
```

This installs Flask, pywebview, Markdown, PyYAML, and the other runtime deps.

### 1.3 Download CMS content

```bash
heichalot-update --flush
```

This fetches the latest content archive from `https://heichalot.tech/cms/` and builds the local `content.db`.

> If the remote server is unreachable, you can seed the database from a local archive:
> ```bash
> python3 tools/seed-from-zip.py /path/to/cms-update-2026-06-25.zip
> ```

### 1.4 Run

```bash
python3 src/heichalot-cms.py
```

The GUI window will appear at 1280×850. The Flask server runs on `http://127.0.0.1:8765`.

To run the Flask server **without** the GUI window (e.g. for testing, or to access via browser):

```bash
HEICHALOT_NO_GUI=1 python3 src/heichalot-cms.py
```

---

## 2. Windows

### 2.1 System dependencies

Install **Python 3.10+** from [python.org](https://python.org). Ensure **"Add Python to PATH"** is checked during installation.

### 2.2 Python dependencies

Open **Command Prompt** or **PowerShell** in the project root:

```powershell
pip install -e ".[desktop]"
```

### 2.3 Known Windows issues

- **PyQtWebEngine** may need a separate install: `pip install PyQtWebEngine`
- If you see `ModuleNotFoundError: No module named 'PyQt5'`, run: `pip install PyQt5`
- If the GUI window is blank, try the GTK backend (requires MSYS2 or Cygwin — not recommended). Prefer Qt on Windows.

### 2.4 Run

```powershell
python src\heichalot-cms.py
```

---

## 3. Verifying the install

```bash
python3 -m py_compile src/heichalot-cms.py
echo "OK"
```

A clean compile without errors means all imports resolve correctly.

---

## 4. Troubleshooting

| Symptom | Likely fix |
|---|---|
| `qtpy.QtModuleNotInstalledError: The QtWebEngineCore module was not found` | `pip install PyQtWebEngine` |
| `Namespace WebKit2 not available` | Install GTK packages (see 1.1) or switch to Qt backend |
| `sqlite3.OperationalError: no such table: entries` | Run `heichalot-update --flush` to download content |
| `ModuleNotFoundError: No module named 'webview'` | `pip install pywebview` |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install pyyaml` |

## 5. Updating content

```bash
heichalot-update
```

To force a full re-download:

```bash
heichalot-update --flush
```

---

## Installing the Default Remote-Viewing Model

The Heichalot-CMS remote-viewing system uses a local Large Language Model (LLM)
running under Ollama.

Installing Ollama by itself is **not** sufficient. At least one compatible model
must also be installed before the live remote-viewing system can be used.

The default configuration uses the gemma3 LLM. It has been tested to be
able to provide baseline remote-viewing capabilities.

You can check your installation at any time by running:

```bash
python3 tools/config.py
```
Example output:
```bash
╭───────────────────── Heichalot-CMS Configuration ──────────────────────╮
│  Config exists  yes                                                    │
│  Config path    /home/dlyon/.heichalotcms/config.ini                   │
│  ...                                                                   │
│  LLM System     Ollama  /usr/local/bin/ollama, http://localhost:11434  │
│  LLM Model      gemma3  installed                                      │
╰────────────────────────────────────────────────────────────────────────╯
```

If the model is not installed, install the configured default model with:

```bash
python3 tools/config.py --install-default-model
```

This command reads the configured model from config.ini and downloads it into
the local Ollama installation.

Alternatively, you may install models manually using the standard Ollama
commands.

If Ollama is not installed, the configuration utility will report:

```bash
LLM System     Not installed
```

In this case, install Ollama first, then run the command above to install the
default model.

Once both Ollama and the configured model are installed, the Heichalot RV
backend becomes available from the Remote-Viewing screen.

