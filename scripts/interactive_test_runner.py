#!/usr/bin/env python3
"""Interactive orchestrator for ffbsdl USB test workflows.

This script is a thin TUI-style wrapper around:
  - scripts/run_usb_tests.py
  - scripts/analyze_usb_pcaps.py
  - scripts/compare_payloads.py
  - scripts/compare_analysis.py

It discovers test suites in tests/test_cases*.json, tracks capture/analysis
runs under captures/, and lets you run captures, analyze, compare, and
clean runs from a simple menu.
"""

import json
import os
import platform
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from glob import glob
from typing import Any, Callable, Dict, List, Optional
import shutil

try:  # Optional nice TUI; falls back to simple input() if missing
    import questionary  # type: ignore
except Exception:  # pragma: no cover - best-effort import
    questionary = None  # type: ignore


CAPTURES_ROOT = "captures"
TESTS_ROOT = "tests"

# Store per-user configuration (paths to binaries, etc.) at the repo root so
# it can be reused across runs of the interactive script.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, ".interactive_runner_config.json")

# Populated in main() via load_settings().
SETTINGS: Dict[str, Any] = {}


@dataclass
class SuiteInfo:
    name: str
    path: str
    num_tests: int


@dataclass
class RunInfo:
    suite_tests_file: str
    dir: str
    manifest_path: str
    analysis_path: Optional[str]
    num_manifest_tests: int
    num_analysis_tests: int
    mtime: float


def color(text: str, fg: Optional[str] = None) -> str:
    colors = {"red": "31", "green": "32", "yellow": "33", "cyan": "36"}
    if not fg or fg not in colors:
        return text
    return f"\033[{colors[fg]}m{text}\033[0m"


def load_settings() -> None:
    """Load persisted interactive runner settings into SETTINGS."""
    global SETTINGS
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            SETTINGS.update(data)
    except FileNotFoundError:
        # First run; nothing to load.
        pass
    except Exception as exc:  # pragma: no cover - defensive
        print(color(f"[WARN] Failed to load settings from {CONFIG_PATH}: {exc}", "yellow"))


def save_settings() -> None:
    """Persist SETTINGS to disk (best-effort)."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(SETTINGS, f, indent=2)
    except Exception as exc:  # pragma: no cover - defensive
        print(color(f"[WARN] Failed to save settings to {CONFIG_PATH}: {exc}", "yellow"))




def ask_select(message: str, choices: List[str]) -> Optional[str]:
    if not choices:
        print("No choices available.")
        return None
    if questionary:
        return questionary.select(message, choices=choices).ask()
    # Fallback numbered menu
    while True:
        print(message)
        for i, c in enumerate(choices, start=1):
            print(f"  {i}. {c}")
        sel = input("Select number (or blank to cancel): ").strip()
        if not sel:
            return None
        try:
            idx = int(sel)
        except ValueError:
            continue
        if 1 <= idx <= len(choices):
            return choices[idx - 1]


def ask_text(message: str, default: Optional[str] = None) -> Optional[str]:
    if questionary:
        return questionary.text(message, default=default or "").ask()
    prompt = f"{message}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    value = input(prompt).strip()
    if not value and default is not None:
        return default
    return value or None


def ask_confirm(message: str, default: bool = False) -> bool:
    if questionary:
        return bool(questionary.confirm(message, default=default).ask())
    yn = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{message} ({yn}): ").strip().lower()
        if not ans:
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def ask_multi_select(message: str, choices: List[str], max_sel: Optional[int] = None) -> List[str]:
    if not choices:
        return []
    if questionary:
        sel = questionary.checkbox(message, choices=choices).ask() or []
        if max_sel is not None and len(sel) > max_sel:
            sel = sel[:max_sel]
        return sel
    # Simple comma-separated selection
    print(message)
    for i, c in enumerate(choices, start=1):
        print(f"  {i}. {c}")
    raw = input("Select numbers separated by commas: ").strip()
    if not raw:
        return []
    out: List[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            idx = int(part)
        except ValueError:
            continue
        if 1 <= idx <= len(choices):
            out.append(choices[idx - 1])
    if max_sel is not None and len(out) > max_sel:
        out = out[:max_sel]
    return out


def discover_suites() -> List[SuiteInfo]:
    suites: List[SuiteInfo] = []
    pattern = os.path.join(TESTS_ROOT, "test_cases*.json")
    for path in sorted(glob(pattern)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                doc = json.load(f)
            tests = doc.get("tests", [])
            name = os.path.splitext(os.path.basename(path))[0]
            suites.append(SuiteInfo(name=name, path=path, num_tests=len(tests)))
        except Exception as exc:  # pragma: no cover - defensive
            print(color(f"[WARN] Failed to load {path}: {exc}", "yellow"))
    return suites


def discover_runs() -> Dict[str, List[RunInfo]]:
    runs_by_suite: Dict[str, List[RunInfo]] = defaultdict(list)
    if not os.path.isdir(CAPTURES_ROOT):
        return runs_by_suite
    for root, _dirs, files in os.walk(CAPTURES_ROOT):
        if "manifest.json" not in files:
            continue
        manifest_path = os.path.join(root, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:  # pragma: no cover
            print(color(f"[WARN] Failed to read {manifest_path}: {exc}", "yellow"))
            continue
        tests_file = manifest.get("tests_file") or ""
        if os.path.isabs(tests_file):
            tests_file = os.path.relpath(tests_file, start=".")
        tests_file = tests_file.replace("\\", "/")
        analysis_path = os.path.join(root, "analysis.json") if "analysis.json" in files else None
        num_manifest = len(manifest.get("tests", []))
        num_analysis = 0
        if analysis_path:
            try:
                with open(analysis_path, "r", encoding="utf-8") as f:
                    analysis = json.load(f)
                num_analysis = len(analysis.get("tests", []))
            except Exception:
                analysis_path = None
        mtime = os.path.getmtime(analysis_path or manifest_path)
        runs_by_suite[tests_file].append(
            RunInfo(
                suite_tests_file=tests_file,
                dir=root,
                manifest_path=manifest_path,
                analysis_path=analysis_path,
                num_manifest_tests=num_manifest,
                num_analysis_tests=num_analysis,
                mtime=mtime,
            )
        )
    return runs_by_suite


def format_time(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "?"


def list_tshark_interfaces(tshark_path: str) -> List[str]:
    try:
        proc = subprocess.run(
            [tshark_path, "-D"], capture_output=True, text=True, check=False
        )
    except OSError as exc:
        print(color(f"[WARN] Failed to run '{tshark_path} -D': {exc}", "yellow"))
        return []
    if proc.returncode != 0:
        return []
    out: List[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or "." not in line:
            continue
        try:
            _idx, rest = line.split(". ", 1)
        except ValueError:
            continue
        name = rest.split(" ", 1)[0]
        out.append(f"{name}  ({line})")
    return out


def choose_interface(tshark_path: str) -> Optional[str]:
    options = list_tshark_interfaces(tshark_path)
    if options:
        choice = ask_select("Select capture interface (from tshark -D):", options)
        if not choice:
            return None
        # Extract raw name before spaces
        return choice.split(" ", 1)[0]
    return ask_text("Enter capture interface (e.g. usbmon1 or \\.\\USBPcap1)")


def default_ffb_binary() -> str:
    if os.name == "nt":
        return os.path.join("bin", "win64", "ffbsdl.exe")
    return "./ffbsdl"


def auto_discover_tshark() -> Optional[str]:
    """Return a reasonable default tshark path based on OS, if found.

    This is intentionally simple/best-effort – users can always override in
    the settings menu or at the prompt.
    """
    # Honour an existing setting first.
    existing = SETTINGS.get("tshark_path")
    if isinstance(existing, str) and existing:
        return existing

    candidate_paths: List[str] = []
    system = platform.system().lower()
    if system == "windows":
        candidate_paths.extend(
            [
                r"C:\\Program Files\\Wireshark\\tshark.exe",
                r"C:\\Program Files (x86)\\Wireshark\\tshark.exe",
            ]
        )
    else:
        candidate_paths.extend([
            "/usr/bin/tshark",
            "/usr/local/bin/tshark",
        ])

    # Fallback to whatever is on PATH.
    if shutil.which("tshark"):
        candidate_paths.append("tshark")

    for p in candidate_paths:
        if shutil.which(p) or os.path.exists(p):
            return p
    return None


def auto_discover_iface(tshark_path: str) -> Optional[str]:
    """Try to pick a sane default capture interface using tshark -D.

    We keep the logic simple: prefer the first interface from tshark -D.
    """
    options = list_tshark_interfaces(tshark_path)
    if not options:
        return None
    return options[0].split(" ", 1)[0]


def run_subprocess(
    cmd: List[str],
    cwd: Optional[str] = None,
    line_handler: Optional[Callable[[str], None]] = None,
) -> int:
    print(color("[RUN] ", "cyan") + " ".join(cmd))
    try:
        # If no custom handler is provided, just stream output through.
        if line_handler is None:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout or []:
                sys.stdout.write(line)
                sys.stdout.flush()
            proc.wait()
            return proc.returncode or 0

        # With a handler, let the caller interpret each line (for progress bars
        # etc.) while still giving them the full raw output.
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout or []:
            try:
                line_handler(line)
            except Exception:
                # Be conservative: fall back to plain streaming so that errors
                # in the handler never hide important information.
                sys.stdout.write(line)
                sys.stdout.flush()
        proc.wait()
        return proc.returncode or 0
    except KeyboardInterrupt:
        print(color("Interrupted.", "yellow"))
        return 1


def display_current_settings(context: str = "") -> None:
    """Print current cached settings before launching a sub-script."""
    header = "Current settings"
    if context:
        header = f"{context}: current settings"
    print(color(f"\n=== {header} ===", "cyan"))
    print(f"tshark path      : {SETTINGS.get('tshark_path') or '(not set)'}")
    print(f"ffbsdl binary    : {SETTINGS.get('ffb_binary') or default_ffb_binary()}")
    print(f"capture interface: {SETTINGS.get('iface') or '(not set)'}")
    print(f"default gain     : {SETTINGS.get('gain') or '(none)'}")


def make_capture_progress_handler(total_tests: int) -> Callable[[str], None]:
    """Create a line handler that shows capture progress per test.

    This keeps a single progress bar "anchored" at the bottom of the output by
    rewriting the last line with a carriage return (similar to tqdm). All
    original sub-script output is still printed above the bar.
    """

    state = {
        "current": 0,
        "total": max(0, total_tests),
        "label": "",
        "bar_active": False,
        "last_len": 0,
    }
    prefix = "[RUN] Test "

    def build_bar() -> str:
        current = state["current"]
        total = state["total"]
        label = state["label"] or "..."
        if total > 0 and current >= 0:
            frac = max(0.0, min(1.0, float(current) / float(total)))
            width = 30
            filled = int(round(frac * width))
            bar = "#" * filled + "-" * (width - filled)
            percent = int(round(frac * 100))
            text = f"[CAPTURE] [{bar}] {current}/{total} ({percent:3d}%) {label}"
        else:
            text = f"[CAPTURE] {label}"
        return color(text, "cyan")

    def show_bar() -> None:
        text = build_bar()
        if state["bar_active"] and state["last_len"]:
            sys.stdout.write("\r" + " " * state["last_len"] + "\r")
        sys.stdout.write(text)
        sys.stdout.flush()
        state["last_len"] = len(text)
        state["bar_active"] = True

    def print_log(line: str) -> None:
        # Clear the bar, print the log line, then re-draw the bar so it stays on
        # the bottom.
        if state["bar_active"] and state["last_len"]:
            sys.stdout.write("\r" + " " * state["last_len"] + "\r")
        sys.stdout.write(line)
        if state["bar_active"]:
            show_bar()
        else:
            sys.stdout.flush()

    def handle(line: str) -> None:
        stripped = line.strip()
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :]
            try:
                # "3: some_id (...)"
                idx_part, rest2 = rest.split(":", 1)
                idx = int(idx_part.strip())
                remainder = rest2.strip()
                test_id = remainder.split(" ", 1)[0]
                state["current"] = idx
                state["label"] = test_id
            except Exception:
                # If parsing fails, just treat this as a normal log line and
                # fall back to a generic bar.
                print_log(line)
                if not state["bar_active"]:
                    state["label"] = "Running tests..."
                    show_bar()
                return

            print_log(line)
            show_bar()
            return

        # Non-progress line: print as-is, but ensure we at least show a generic
        # "running" bar once.
        print_log(line)
        if not state["bar_active"]:
            state["label"] = "Running tests..."
            show_bar()

    return handle


def make_analysis_progress_handler(total_tests: int) -> Callable[[str], None]:
    """Create a line handler that shows analysis progress per capture.

    This also keeps a single bar anchored at the bottom while printing all
    original analysis output above it.
    """

    state = {
        "current": 0,
        "total": max(0, total_tests),
        "label": "",
        "bar_active": False,
        "last_len": 0,
    }
    prefix = "[ANALYZE] "

    def build_bar() -> str:
        current = state["current"]
        total = state["total"]
        label = state["label"] or "..."
        if total > 0 and current >= 0:
            frac = max(0.0, min(1.0, float(current) / float(total)))
            width = 30
            filled = int(round(frac * width))
            bar = "#" * filled + "-" * (width - filled)
            percent = int(round(frac * 100))
            text = f"[ANALYSIS] [{bar}] {current}/{total} ({percent:3d}%) {label}"
        else:
            text = f"[ANALYSIS] {label}"
        return color(text, "cyan")

    def show_bar() -> None:
        text = build_bar()
        if state["bar_active"] and state["last_len"]:
            sys.stdout.write("\r" + " " * state["last_len"] + "\r")
        sys.stdout.write(text)
        sys.stdout.flush()
        state["last_len"] = len(text)
        state["bar_active"] = True

    def print_log(line: str) -> None:
        # Clear the bar, print the log line, then re-draw the bar.
        if state["bar_active"] and state["last_len"]:
            sys.stdout.write("\r" + " " * state["last_len"] + "\r")
        sys.stdout.write(line)
        if state["bar_active"]:
            show_bar()
        else:
            sys.stdout.flush()

    def handle(line: str) -> None:
        stripped = line.strip()
        if stripped.startswith(prefix):
            rest = stripped[len(prefix) :]
            test_id, _sep, _rest = rest.partition(" -> ")
            state["current"] += 1
            state["label"] = test_id
            print_log(line)
            show_bar()
            return

        print_log(line)
        if not state["bar_active"]:
            state["label"] = "Running analysis..."
            show_bar()

    return handle



def run_captures_for_suite(suite: SuiteInfo) -> Optional[RunInfo]:
    print(color(f"Running captures for suite {suite.name}", "cyan"))

    # Show what we're about to use.
    display_current_settings("Captures")

    # Reuse previously entered tools/paths where possible, falling back to
    # auto-discovered values.
    tshark_path = SETTINGS.get("tshark_path") or auto_discover_tshark() or "tshark"
    iface = SETTINGS.get("iface") or auto_discover_iface(tshark_path)
    ffb = SETTINGS.get("ffb_binary") or default_ffb_binary()
    gain_str = SETTINGS.get("gain") or ""

    # If anything critical is missing, prompt just for that.
    if not SETTINGS.get("tshark_path"):
        tshark_path = ask_text("Path to tshark", default=tshark_path) or tshark_path
        SETTINGS["tshark_path"] = tshark_path
        save_settings()

    if not iface:
        iface = choose_interface(tshark_path)
        if not iface:
            print(color("No interface selected; aborting.", "red"))
            return None
        SETTINGS["iface"] = iface
        save_settings()

    if not SETTINGS.get("ffb_binary"):
        ffb = ask_text("Path to ffbsdl binary", default=ffb) or ffb
        SETTINGS["ffb_binary"] = ffb
        save_settings()

    # Always ask for a run label; this is run-specific.
    label_default = platform.system().lower() + "_" + time.strftime("%Y%m%d_%H%M%S")
    run_label = ask_text("Run label (used for captures subdir)", default=label_default) or label_default
    out_dir = os.path.join(CAPTURES_ROOT, suite.name, run_label)
    os.makedirs(out_dir, exist_ok=True)

    # Gain: only prompt if no default gain is stored yet.
    if "gain" not in SETTINGS:
        gain_str = ask_text("Global gain 0-100 (optional, blank to skip)")
        if gain_str:
            SETTINGS["gain"] = gain_str
            save_settings()

    # Show final settings actually used for this run.
    print(color("\nUsing settings for this capture run:", "cyan"))
    print(f"  tshark   : {tshark_path}")
    print(f"  iface    : {iface}")
    print(f"  ffbsdl   : {ffb}")
    print(f"  gain     : {SETTINGS.get('gain', '(none)')}")
    print(f"  out_dir  : {out_dir}")

    cmd = [
        sys.executable,
        os.path.join("scripts", "run_usb_tests.py"),
        "--tests-file",
        suite.path,
        "--ffb-binary",
        ffb,
        "--tshark",
        tshark_path,
        "--iface",
        iface,
        "--output-dir",
        out_dir,
    ]
    if SETTINGS.get("gain"):
        try:
            int(SETTINGS["gain"])
            cmd.extend(["--gain", SETTINGS["gain"]])
        except ValueError:
            print(color("Ignoring invalid stored gain value; must be integer 0-100.", "yellow"))

    # Use a progress-aware handler while still streaming full output.
    progress_handler = make_capture_progress_handler(suite.num_tests)
    rc = run_subprocess(cmd, line_handler=progress_handler)
    if rc != 0:
        print(color("run_usb_tests.py failed; see output above.", "red"))
        return None
    manifest_path = os.path.join(out_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(color("No manifest.json found; capture may have failed.", "red"))
        return None
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    num_manifest = len(manifest.get("tests", []))
    mtime = os.path.getmtime(manifest_path)
    return RunInfo(
        suite_tests_file=manifest.get("tests_file", suite.path).replace("\\", "/"),
        dir=out_dir,
        manifest_path=manifest_path,
        analysis_path=None,
        num_manifest_tests=num_manifest,
        num_analysis_tests=0,
        mtime=mtime,
    )



def settings_menu() -> None:
    """Interactive menu to view and edit cached settings.

    This lets you configure paths once up-front instead of only when starting
    a capture or analysis.
    """
    while True:
        print(color("\n=== Settings ===", "cyan"))
        print(f"tshark path      : {SETTINGS.get('tshark_path') or '(auto / not set)'}")
        print(f"ffbsdl binary    : {SETTINGS.get('ffb_binary') or default_ffb_binary()}" )
        print(f"capture interface: {SETTINGS.get('iface') or '(auto / not set)'}")
        print(f"default gain     : {SETTINGS.get('gain') or '(none)'}")
        choice = ask_select(
            "Settings menu:",
            [
                "Edit tshark path",
                "Edit ffbsdl binary path",
                "Edit capture interface",
                "Edit default gain",
                "Re-run auto-discovery for tshark/interface",
                "Back to main menu",
            ],
        )
        if not choice or choice.startswith("Back"):
            return
        if choice.startswith("Edit tshark"):
            current = SETTINGS.get("tshark_path") or auto_discover_tshark() or "tshark"
            new_val = ask_text("Path to tshark", default=current)
            if new_val:
                SETTINGS["tshark_path"] = new_val
                save_settings()
        elif choice.startswith("Edit ffbsdl"):
            current = SETTINGS.get("ffb_binary") or default_ffb_binary()
            new_val = ask_text("Path to ffbsdl binary", default=current)
            if new_val:
                SETTINGS["ffb_binary"] = new_val
                save_settings()
        elif choice.startswith("Edit capture interface"):
            tshark_path = SETTINGS.get("tshark_path") or auto_discover_tshark() or "tshark"
            use_picker = ask_confirm("Discover interfaces via tshark -D?", default=True)
            if use_picker:
                iface = choose_interface(tshark_path)
            else:
                iface = ask_text("Enter capture interface (e.g. usbmon1 or \\.\\USBPcap1)")
            if iface:
                SETTINGS["iface"] = iface
                save_settings()
        elif choice.startswith("Edit default gain"):
            current = SETTINGS.get("gain") or ""
            new_val = ask_text("Default global gain 0-100 (blank for none)", default=current)
            if new_val:
                SETTINGS["gain"] = new_val
            else:
                SETTINGS.pop("gain", None)
            save_settings()
        elif choice.startswith("Re-run auto-discovery"):
            tshark = auto_discover_tshark()
            if tshark:
                SETTINGS["tshark_path"] = tshark
                print(color(f"Auto-discovered tshark: {tshark}", "green"))
            iface = auto_discover_iface(SETTINGS.get("tshark_path") or tshark or "tshark") if (SETTINGS.get("tshark_path") or tshark) else None
            if iface:
                SETTINGS["iface"] = iface
                print(color(f"Auto-selected interface: {iface}", "green"))
            save_settings()

def analyze_run(run: RunInfo, tshark_path: Optional[str] = None) -> Optional[RunInfo]:
    # Decide tshark path: explicit arg wins, then cached setting, then auto-discover, then fallback.
    tshark_path = tshark_path or SETTINGS.get("tshark_path") or auto_discover_tshark() or "tshark"

    # Show the settings used for this analysis.
    display_current_settings("Analysis")
    print(color(f"\nAnalyzing {run.dir}", "cyan"))
    print(f"  tshark   : {tshark_path}")

    # Remember the tshark path we actually used.
    SETTINGS["tshark_path"] = tshark_path
    save_settings()

    out_path = os.path.join(run.dir, "analysis.json")
    cmd = [
        sys.executable,
        os.path.join("scripts", "analyze_usb_pcaps.py"),
        "--manifest",
        run.manifest_path,
        "--tshark",
        tshark_path,
        "--output",
        out_path,
    ]
    progress_handler = make_analysis_progress_handler(run.num_manifest_tests)
    rc = run_subprocess(cmd, line_handler=progress_handler)
    if rc != 0:
        print(color("analyze_usb_pcaps.py failed.", "red"))
        return None
    if not os.path.isfile(out_path):
        print(color("analysis.json not found after analysis.", "red"))
        return None
    with open(out_path, "r", encoding="utf-8") as f:
        analysis = json.load(f)
    run.analysis_path = out_path
    run.num_analysis_tests = len(analysis.get("tests", []))
    run.mtime = os.path.getmtime(out_path)
    return run


def choose_run_for_suite(suite: SuiteInfo, runs_by_suite: Dict[str, List[RunInfo]]) -> Optional[RunInfo]:
    key = suite.path.replace("\\", "/")
    candidates = runs_by_suite.get(key, [])
    if not candidates:
        print(color("No runs found for this suite under captures/.", "yellow"))
        return None
    choices: List[str] = []
    by_label: Dict[str, RunInfo] = {}
    for r in sorted(candidates, key=lambda r: r.mtime, reverse=True):
        status = (
            "analyzed" if r.analysis_path else "captured"
        ) + f" {r.num_analysis_tests}/{r.num_manifest_tests}"
        rel_dir = os.path.relpath(r.dir, start=CAPTURES_ROOT)
        label = f"{rel_dir} [{status}] {format_time(r.mtime)}"
        choices.append(label)
        by_label[label] = r
    sel = ask_select("Select run:", choices)
    if not sel:
        return None
    return by_label[sel]


def compare_payloads_for_run(run: RunInfo) -> None:
    if not run.analysis_path or not os.path.isfile(run.analysis_path):
        print(color("Run has no analysis.json; analyze first.", "red"))
        return
    effect_type = ask_text("Filter by effect type (optional)")
    id_contains = ask_text("Filter by ID substring (optional)")
    cmd = [
        sys.executable,
        os.path.join("scripts", "compare_payloads.py"),
        "--analysis",
        run.analysis_path,
    ]
    if effect_type:
        cmd.extend(["--effect-type", effect_type])
    if id_contains:
        cmd.extend(["--id-contains", id_contains])
    run_subprocess(cmd)


def compare_analyses_across_runs(runs: List[RunInfo]) -> None:
    analyzed = [r for r in runs if r.analysis_path]
    if len(analyzed) < 2:
        print(color("Need at least two analyzed runs to compare.", "yellow"))
        return
    choices: List[str] = []
    by_label: Dict[str, RunInfo] = {}
    for r in sorted(analyzed, key=lambda r: r.mtime, reverse=True):
        rel_dir = os.path.relpath(r.dir, start=CAPTURES_ROOT)
        label = f"{rel_dir} ({format_time(r.mtime)})"
        choices.append(label)
        by_label[label] = r
    sel = ask_multi_select("Select TWO runs to compare (baseline vs comparison):", choices, max_sel=2)
    if len(sel) != 2:
        print(color("Exactly two runs must be selected.", "yellow"))
        return
    a, b = by_label[sel[0]], by_label[sel[1]]
    cmd = [
        sys.executable,
        os.path.join("scripts", "compare_analysis.py"),
        "--baseline",
        a.analysis_path or "",
        "--comparison",
        b.analysis_path or "",
    ]
    run_subprocess(cmd)


def clean_runs_for_suite(suite: SuiteInfo, runs_by_suite: Dict[str, List[RunInfo]]) -> None:
    import shutil

    key = suite.path.replace("\\", "/")
    runs = runs_by_suite.get(key, [])
    if not runs:
        print(color("No runs to clean for this suite.", "yellow"))
        return
    choices = []
    by_label: Dict[str, RunInfo] = {}
    for r in sorted(runs, key=lambda r: r.mtime, reverse=True):
        rel_dir = os.path.relpath(r.dir, start=CAPTURES_ROOT)
        label = f"{rel_dir} ({format_time(r.mtime)})"
        choices.append(label)
        by_label[label] = r
    sel = ask_multi_select("Select runs to delete (this removes capture directories):", choices)
    if not sel:
        return
    if not ask_confirm("Really delete selected capture directories?", default=False):
        return
    for label in sel:
        r = by_label[label]
        print(color(f"Deleting {r.dir}", "red"))
        shutil.rmtree(r.dir, ignore_errors=True)


def print_status(suites: List[SuiteInfo], runs_by_suite: Dict[str, List[RunInfo]]) -> None:
    print(color("\n=== Suite Status ===", "cyan"))
    for suite in suites:
        key = suite.path.replace("\\", "/")
        runs = runs_by_suite.get(key, [])
        analyzed = [r for r in runs if r.analysis_path]
        if analyzed:
            status = color("COMPLETE", "green")
        elif runs:
            status = color("PARTIAL", "yellow")
        else:
            status = color("NOT RUN", "red")
        last_time = max((r.mtime for r in runs), default=0.0)
        last_str = format_time(last_time) if last_time else "-"
        print(
            f"- {suite.name}: {status} | tests={suite.num_tests} | runs={len(runs)} "
            f"| analyzed={len(analyzed)} | last_run={last_str}"
        )
    print()


def suite_menu(suite: SuiteInfo) -> None:
    while True:
        runs_by_suite = discover_runs()
        print(color(f"\n=== Suite: {suite.name} ({suite.path}) ===", "cyan"))
        choice = ask_select(
            "Choose action:",
            [
                "Run captures (new run)",
                "Run full workflow (captures + analysis, optional compare)",
                "Analyze existing run",
                "Compare payloads within a run",
                "Compare analyses (two runs of this suite)",
                "Clean/delete captures for this suite",
                "Back to main menu",
            ],
        )
        if not choice or choice.endswith("Back to main menu"):
            return
        if choice.startswith("Run captures"):
            run_captures_for_suite(suite)
        elif choice.startswith("Run full workflow"):
            new_run = run_captures_for_suite(suite)
            if not new_run:
                continue
            # Directly analyze using the stored/auto-discovered tshark path.
            analyzed_run = analyze_run(new_run)
            if analyzed_run:
                # Optionally compare with an existing analyzed run
                runs_by_suite = discover_runs()
                key = suite.path.replace("\\", "/")
                all_runs = runs_by_suite.get(key, []) + [analyzed_run]
                others = [r for r in all_runs if r.analysis_path and r.dir != analyzed_run.dir]
                if others and ask_confirm(
                    "Compare this run against another analyzed run now?", default=False
                ):
                    compare_analyses_across_runs(others + [analyzed_run])
        elif choice.startswith("Analyze existing"):
            run = choose_run_for_suite(suite, runs_by_suite)
            if run:
                analyze_run(run)
        elif choice.startswith("Compare payloads"):
            run = choose_run_for_suite(suite, runs_by_suite)
            if run:
                compare_payloads_for_run(run)
        elif choice.startswith("Compare analyses"):
            key = suite.path.replace("\\", "/")
            runs = runs_by_suite.get(key, [])
            compare_analyses_across_runs(runs)
        elif choice.startswith("Clean/delete"):
            clean_runs_for_suite(suite, runs_by_suite)


def main() -> None:
    # Load any persisted settings first so we can offer good defaults.
    load_settings()

    print(color("ffbsdl interactive USB test runner", "cyan"))
    print(f"Platform: {platform.system()} {platform.release()}")
    current_suite: Optional[SuiteInfo] = None
    while True:
        suites = discover_suites()
        runs_by_suite = discover_runs()
        label = current_suite.name if current_suite else "(none)"
        choice = ask_select(
            f"Main menu (current suite: {label})",
            [
                "Select test suite",
                "View status",
                "Configure settings",
                "Compare analyses across all runs",
                "Exit",
            ],
        )
        if not choice or choice == "Exit":
            break
        if choice.startswith("Select test suite"):
            if not suites:
                print(color("No test_cases*.json suites found in tests/.", "red"))
                continue
            names = [f"{s.name} ({s.path})" for s in suites]
            sel = ask_select("Select suite:", names)
            if not sel:
                continue
            idx = names.index(sel)
            current_suite = suites[idx]
            suite_menu(current_suite)
        elif choice.startswith("View status"):
            print_status(suites, runs_by_suite)
        elif choice.startswith("Configure settings"):
            settings_menu()
        elif choice.startswith("Compare analyses across"):
            all_runs: List[RunInfo] = []
            for lst in runs_by_suite.values():
                all_runs.extend(lst)
            compare_analyses_across_runs(all_runs)


if __name__ == "__main__":
    main()

