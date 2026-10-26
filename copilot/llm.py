"""The model through your subscription: we run a local CLI (`claude -p` or `codex exec`) that is
already signed in to your Claude / ChatGPT account. No API keys.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading

from .i18n import t

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW — no flashing console windows
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKDIR = os.path.join(tempfile.gettempdir(), "copilot_llm")
os.makedirs(WORKDIR, exist_ok=True)


class LLMError(Exception):
    pass


def _kill_tree(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                       capture_output=True, creationflags=NO_WINDOW)


class _Base:
    def __init__(self, cfg):
        self.cfg = cfg
        self.proc = None
        self.lock = threading.Lock()

    def cancel(self):
        with self.lock:
            _kill_tree(self.proc)

    def _popen(self, cmd):
        with self.lock:
            self.proc = subprocess.Popen(
                cmd, cwd=WORKDIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW,
            )
            return self.proc


class ClaudeCLI(_Base):
    label = "Claude"

    def __init__(self, cfg):
        super().__init__(cfg)
        local = os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe")
        self.exe = shutil.which("claude") or (local if os.path.exists(local) else None)

    def missing(self):
        return None if self.exe else t("claude_missing")

    def run(self, system, user, on_delta, image=None):
        if not self.exe:
            raise LLMError(t("claude_missing"))
        cmd = [
            self.exe, "-p",
            "--model", self.cfg.get("claude_model", "sonnet"),
            "--no-session-persistence",
            "--setting-sources", "project",  # do not load the user's own hooks / plugins
            "--strict-mcp-config",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--system-prompt", system,
        ]
        if self.cfg.get("claude_effort"):
            cmd += ["--effort", self.cfg["claude_effort"]]
        if image:  # the screenshot is read with the built-in Read tool
            cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", os.path.dirname(image)]
            user += f"\n\nScreenshot of the screen: {image} — open it with the Read tool."
        else:
            cmd += ["--tools", ""]
        p = self._popen(cmd)
        p.stdin.write(user)
        p.stdin.close()
        text, err = "", None
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "stream_event":
                e = ev.get("event", {})
                if e.get("type") == "content_block_delta" and e.get("delta", {}).get("type") == "text_delta":
                    text += e["delta"]["text"]
                    on_delta(text)
                elif e.get("type") == "message_start" and text:
                    text += "\n\n"  # a new turn after the Read call
            elif ev.get("type") == "result":
                if ev.get("is_error"):
                    err = ev.get("result") or "claude error"
                elif not text:
                    text = ev.get("result", "")
        p.wait()
        if err:
            if "login" in err.lower():
                err += "\n" + t("claude_login")
            raise LLMError(err)
        if p.returncode not in (0, None) and not text:
            raise LLMError(p.stderr.read()[-500:] or t("cli_exit", name="claude", code=p.returncode))
        return text


class CodexCLI(_Base):
    label = "Codex"

    def __init__(self, cfg):
        super().__init__(cfg)
        # Our own copy in tools\ first (npm install --prefix tools @openai/codex): a global npm install may sit
        # in another app's virtualised AppData and be invisible when the app is started from a shortcut.
        rel = os.path.join("node_modules", "@openai", "codex", "bin", "codex.js")
        candidates = [os.path.join(ROOT, "tools", rel),
                      os.path.join(os.environ.get("APPDATA", ""), "npm", rel)]
        js = next((p for p in candidates if os.path.exists(p)), None)
        node = next((p for p in (os.path.join(ROOT, "tools", "node", "node.exe"),) if os.path.exists(p)), None) \
            or shutil.which("node") \
            or next((p for p in (r"C:\Program Files\nodejs\node.exe",) if os.path.exists(p)), None)
        cmd = shutil.which("codex.cmd")
        self.base = [node, js] if node and js else [cmd] if cmd else None

    def missing(self):
        return None if self.base else t("codex_missing")

    def run(self, system, user, on_delta, image=None):
        if not self.base:
            raise LLMError(t("codex_missing"))
        cmd = self.base + [
            "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--json",
            "-c", f"model_reasoning_effort={self.cfg.get('codex_effort', 'low')}",
            "-c", "model_verbosity=low",
        ]
        if self.cfg.get("codex_service_tier"):
            cmd += ["-c", f"service_tier={self.cfg['codex_service_tier']}"]  # fast = 1.5x speed, uses limits faster
        if self.cfg.get("codex_ignore_user_config", True):
            cmd += ["--ignore-user-config"]  # no MCP servers / plugins from config.toml — starts several times faster
        if self.cfg.get("codex_model"):
            cmd += ["-m", self.cfg["codex_model"]]
        if image:
            cmd += ["-i", image]
        cmd += ["-"]
        p = self._popen(cmd)
        p.stdin.write(f"<instructions>\n{system}\n</instructions>\n\n{user}")
        p.stdin.close()
        text, err = "", None
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            item = ev.get("item") or {}
            if kind in ("item.completed", "item.updated") and item.get("type") == "agent_message":
                text = item.get("text", "")
                on_delta(text)
            elif kind in ("turn.failed", "error"):
                err = (ev.get("error") or {}).get("message") or ev.get("message") or "codex error"
        p.wait()
        if err and not text:
            raise LLMError(err)
        if p.returncode not in (0, None) and not text:
            raise LLMError(p.stderr.read()[-500:] or t("cli_exit", name="codex", code=p.returncode))
        return text


def make_backend(cfg):
    return CodexCLI(cfg) if cfg.get("backend", "codex").lower() == "codex" else ClaudeCLI(cfg)


def connection_status(backend, cfg):
    """'ok' — the CLI is installed and signed in, 'no_cli' — not installed, 'no_login' — not signed in.
    Takes under a second; run it off the UI thread."""
    probe = dict(cfg, backend=backend)
    try:
        if backend == "codex":
            b = CodexCLI(probe)
            if not b.base:
                return "no_cli"
            r = subprocess.run(b.base + ["login", "status"], capture_output=True, encoding="utf-8", errors="replace",
                               timeout=20, cwd=WORKDIR, creationflags=NO_WINDOW)
            return "ok" if "logged in" in (r.stdout + r.stderr).lower() else "no_login"
        b = ClaudeCLI(probe)
        if not b.exe:
            return "no_cli"
        r = subprocess.run([b.exe, "auth", "status", "--json"], capture_output=True, encoding="utf-8",
                           errors="replace", timeout=20, cwd=WORKDIR, creationflags=NO_WINDOW)
        return "ok" if json.loads(r.stdout or "{}").get("loggedIn") else "no_login"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "no_login"


CREATE_NEW_CONSOLE = 0x00000010


def start_connect(backend, lang):
    """Open the connection window (connect.ps1: installs the CLI if needed and opens the account sign-in).
    Returns the process, or None if the script is missing."""
    script = next((p for p in (os.path.join(ROOT, "connect.ps1"), os.path.join(ROOT, "installer", "connect.ps1"))
                   if os.path.exists(p)), None)
    if not script:
        return None
    return subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script,
                             "-Backend", backend, "-Dest", ROOT, "-Lang", lang],
                            cwd=ROOT, creationflags=CREATE_NEW_CONSOLE)
