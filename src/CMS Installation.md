# Heichalot CMS — Desktop Installation

## Prerequisites

- Python 3.10+
- pip
- Git (optional, for version tracking)

---

## 1. Linux

### 1.1 System packages (GUI backend)

The desktop app uses **pywebview** with the Qt backend on Linux. The Python
packages are installed into a local environment by the installer below; the
system only needs the libraries Qt loads at runtime.

The easiest path is:

```bash
bash install_linux.sh --system-deps
```

That installs the Qt/X11 libraries with `apt` on Debian/Ubuntu/Linux Mint (and
the equivalent package names on Fedora, Arch, and openSUSE).

To do it manually on Debian/Ubuntu/Mint:

```bash
sudo apt install python3-venv python3-pip \
  libgl1 libegl1 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-render-util0 \
  libxcb-shape0 libxcb-xfixes0 \
  libdbus-1-3 libnss3 libxcomposite1 libxdamage1 \
  libxrandr2 libxtst6 libgbm1 libxshmfence1 libasound2
```

> Only the Qt backend is used on Linux. Install the GTK packages only if you
> deliberately switch pywebview to GTK.

### 1.2 Python dependencies

From the project root:

```bash
bash install_linux.sh
```

This detects `uv`, `venv` + `pip`, or `conda` / `mamba` / `micromamba`,
creates `.venv-linux` (or `.conda-linux`), installs `src/requirements.txt`,
and runs the first-time configuration.

To do it manually:

```bash
python3 -m venv .venv-linux
.venv-linux/bin/python -m pip install -r src/requirements.txt
.venv-linux/bin/python tools/config.py --setup
```

This installs Flask, pywebview, the Qt bindings, PyYAML, and the other runtime
deps.

### 1.3 Download CMS content

```bash
.venv-linux/bin/python tools/updatecms.py --flush
```

This fetches the latest content archive from `https://heichalot.tech/cms/` and builds the local `content.db`.

### 1.4 Run

```bash
.venv-linux/bin/python src/heichalot-cms.py
```

The GUI window will appear at 1280×850. The Flask server runs on `http://127.0.0.1:8765`.

To run the Flask server **without** the GUI window (e.g. for testing, or to access via browser):

```bash
HEICHALOT_NO_GUI=1 .venv-linux/bin/python src/heichalot-cms.py
```

---

## 2. Windows

### 2.1 System dependencies

Install **Python 3.10+** from [python.org](https://python.org). Ensure **"Add Python to PATH"** is checked during installation.

### 2.2 Python dependencies

Open **Command Prompt** or **PowerShell** in the project root and run the
installer, which creates a local `.venv-win` and installs the requirements:

```bat
install_windows.bat
```

To install without running the first-time configuration:

```bat
install_windows.bat --no-setup
```

To do it manually:

```powershell
python -m venv .venv-win
.venv-win\Scripts\python.exe -m pip install -r src\requirements.txt
.venv-win\Scripts\python.exe tools\config.py --setup
```

### 2.3 Known Windows issues

- Windows uses the built-in **EdgeChromium (WebView2)** backend, so the Qt
  bindings are not needed.
- If the GUI window is blank, install the **WebView2 Runtime** from Microsoft.

### 2.4 Run

```powershell
.venv-win\Scripts\python.exe src\heichalot-cms.py
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
| `sqlite3.OperationalError: no such table: entries` | Run `.venv-linux/bin/python tools/updatecms.py --flush` to download content |
| `ensurepip is not available` when creating a venv | `sudo apt install python3-venv` (Debian/Ubuntu/Mint) |
| `ModuleNotFoundError: No module named 'webview'` | `pip install pywebview` |
| `ModuleNotFoundError: No module named 'yaml'` | `pip install pyyaml` |

## 5. Updating content

From a source checkout:

```bash
.venv-linux/bin/python tools/updatecms.py
```

To force a full re-download:

```bash
.venv-linux/bin/python tools/updatecms.py --flush
```

> If the package is installed (for example with `pip install -e .`), the
> `heichalot-update` command is equivalent.

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

