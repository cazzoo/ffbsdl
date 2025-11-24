# ffbsdl

CLI force-feedback (FFB) editor and test tool written in C with SDL2.

This repository contains:

- `ffbsdl`: an interactive CLI tool to create, tweak, and play SDL2 haptic effects
- A **USB capture test harness** (Python scripts + JSON test suites) to exercise
  SDL haptic effects in a reproducible way and capture the resulting USB HID
  traffic for analysis.

The USB test harness is intended to help understand how different platforms
encode SDL haptic effects at the USB level, which is useful when developing
low-level FFB drivers or debugging device behaviour.

## Dependencies

### Core (for ffbsdl itself)

- SDL2

On Debian/Ubuntu:

- `sudo apt install libsdl2-dev make gcc`

On other Linux distros, install the equivalent SDL2 development package.

On Windows, a convenient way is to use [MSYS2](https://www.msys2.org/):

1. Follow the MSYS2 installation instructions up to step 7.
2. In the MSYS2 MinGW64 shell, install SDL2 and build tools, e.g.:
   - `pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2 make`
3. Install python and pip:
   - `pacman -S mingw-w64-x86_64-python3 mingw-w64-x86_64-python3-pip`

### USB capture & analysis

For the Python-based USB test harness you will need:

- Python 3.8+ (with the standard library is sufficient)
- Wireshark / tshark
- A way to capture USB traffic:
  - **Linux**: usbmon interfaces (e.g. `usbmon0`, `usbmon1`)
  - **Windows**: [USBPcap](https://desowin.org/usbpcap/) (typically installed
    together with Wireshark)

Make sure `tshark` is on your `PATH` or specify its full path with
`--tshark` when using the scripts.

## Building ffbsdl

From the repository root:

- On Linux / MSYS2 MinGW64:

  ```
  make
  ```

This should produce an `ffbsdl` binary (or `ffbsdl.exe` on Windows).

## Running ffbsdl interactively

On Linux:

- `./ffbsdl`

On Windows (MSYS2 MinGW64), you will usually get better behaviour by running
`ffbsdl.exe` from a regular `cmd.exe` window or by double-clicking the
executable in Explorer. Running it directly from the MSYS2 shell can cause
odd console I/O behaviour.

Once started, follow the on-screen menu to:

- Create and modify force feedback effects
- Play, stop, or destroy effects
- Adjust **autocenter** and **gain** interactively for the current device

## Non-interactive (batch) mode and gain control

`ffbsdl` also supports a non-interactive "batch" mode driven entirely by
command-line parameters. This is what the USB test harness uses.

Batch mode is selected whenever you pass `--effect-type` or any effect
parameter. Example:

- Constant force for 2 seconds at medium level:

  ```
  ./ffbsdl --effect-type constant --level 24000 --length-ms 2000
  ```

### Force feedback gain (`--gain`)

To get reproducible test conditions, you can explicitly set the device-wide
force feedback gain in batch mode:

- `--gain <0-100>` sets the global gain percentage before the effect is
  created and played.
- Example: run a constant effect with **5%** gain:

  ```
  ./ffbsdl --effect-type constant --level 24000 --length-ms 2000 --gain 5
  ```

If `--gain` is omitted, the existing device setting is used (for example,
what you configured in the Windows device control panel).

## USB test harness overview

The USB harness consists of three main scripts plus JSON test descriptions:

- `scripts/run_usb_tests.py`: runs a suite of tests, invokes `ffbsdl` in
  batch mode for each, and captures USB packets with `tshark`.
- `scripts/analyze_usb_pcaps.py`: parses the resulting `.pcapng` files with
  tshark and builds a structured `analysis.json` describing payload patterns.
- `scripts/compare_analysis.py`: compares two `analysis.json` files
  (typically Linux vs Windows) and summarises per-test differences.

Test suites live in `tests/`:

- `tests/test_cases.json`: **single-effect** tests (each test runs exactly
  one SDL haptic effect).
- `tests/test_cases_multi_effect.json`: **multi-effect sequence** tests
  (each test is a sequence of effects run back-to-back while capture is
  active).

### Test JSON structure (single-effect)

Each single-effect test suite has the form:

- `key_levels`: symbolic names (e.g. `"low"`, `"medium"`, `"high"`) mapped
  to numeric values per parameter (e.g. `level`, `magnitude`).
- `defaults`: default parameter values applied to every test unless
  overridden (e.g. `direction_deg`, `length_ms`, `iterations`).
- `tests`: array of test cases. Each test has:
  - `id`: unique identifier (used in filenames and analysis output)
  - `description`: free-form text
  - `effect_type`: one of `constant`, `sine`, `triangle`, `sawtoothup`,
    `sawtoothdown`, `ramp`, `spring`, `damper`, `inertia`, `friction`
  - `params`: effect parameters (overriding `defaults` as needed)

### Test JSON structure (multi-effect sequences)

`tests/test_cases_multi_effect.json` has the same `key_levels` and
`defaults`, but each test provides a `sequence` instead of a single
`effect_type`:

- `sequence`: array of steps, each with:
  - `id`: step identifier within the test
  - `effect_type`: same set of types as single-effect tests
  - `start_ms` (optional): intended start time in the *conceptual* test
    timeline (currently informational; steps actually run sequentially)
  - `params`: per-step effect parameters

During capture, `run_usb_tests.py` starts `tshark` once for the whole
sequence and then runs each step in order. The full packet trace ends up in
one `.pcapng` file per multi-effect test.

## Running the USB tests

Below, `--iface` is your capture interface:

- On Linux this is usually something like `usbmon1`.
- On Windows with USBPcap it looks like `\\.\\USBPcap1`.

### 1. Single-effect suite

From the repo root:

```bash
python scripts/run_usb_tests.py \
  --tests-file tests/test_cases.json \
  --iface usbmon1 \
  --output-dir captures_linux_single
```

On Windows (MSYS2 MinGW64), a typical command looks like:

```bash
python scripts/run_usb_tests.py \
  --tests-file tests/test_cases.json \
  --iface "\\\\.\\\\USBPcap1" \
  --output-dir captures_win_single \
  --capture-filter "" \
  --tshark "/c/Program Files/Wireshark/tshark.exe"
```

Key options:

- `--ffb-binary`: path to the `ffbsdl` binary. Defaults to `./ffbsdl` on
  POSIX and `bin/win64/ffbsdl.exe` on Windows.
- `--pre-delay` / `--post-delay`: delays (in seconds) before and after each
  effect to let capture settle (default `0.5`).
- `--gain` (runner CLI, mapped to `global_gain`): optional **global gain
  override** for the entire run. When specified, every effect invocation is
  passed `--gain <value>` to the `ffbsdl` binary, overriding any per-test
  gain values in JSON.

### 2. Multi-effect sequence suite

To run the multi-effect tests:

```bash
python scripts/run_usb_tests.py \
  --tests-file tests/test_cases_multi_effect.json \
  --iface usbmon1 \
  --output-dir captures_linux_multi
```

The runner behaviour is the same, except each JSON test describes a
sequence. The generated `.pcapng` filename and the `manifest.json` entry
for such tests will have `effect_type: "sequence"` and include a
per-step breakdown.

## Analyzing captures

After running a suite, `run_usb_tests.py` writes a manifest:

- `captures/.../manifest.json` – lists tests, their parameters, and the
  corresponding `.pcapng` paths.

To analyze the captures:

```bash
python scripts/analyze_usb_pcaps.py \
  --manifest captures_linux_single/manifest.json \
  --output captures_linux_single/analysis.json
```

Important details:

- The analyzer shells out to `tshark` to extract minimal USB fields and
  payload bytes. It is defensive about field availability and supports both
  `usb.capdata` and `usbhid.data` payload fields.
- For each test it records:
  - `usb_summary.total_lines`: number of tshark records examined
  - `usb_summary.unique_payloads`: number of distinct payload byte patterns
  - `usb_summary.top_payloads`: a frequency-sorted list of payloads
  - `usb_summary.sample_frames`: a small sample of frames with timing and
    endpoints
- For sequence tests, the input `sequence` structure (per-step IDs,
  params, and `start_ms`) from `manifest.json` is threaded into the
  analysis output so downstream tools can correlate USB patterns with
  individual steps.

## Comparing analysis results (Linux vs Windows)

To compare two analyzed runs (for example, Linux vs Windows) use
`scripts/compare_analysis.py`:

```bash
python scripts/compare_analysis.py \
  --baseline captures_linux_single/analysis.json \
  --comparison captures_win_single/analysis.json \
  --output-json compare_single_linux_vs_win.json
```

The script:

- Matches tests by `id` across the two analysis files.
- For each matched test compares:
  - `total_lines` (or `total_frames`) from tshark
  - `unique_payloads`
  - The set of representative payload byte strings taken from the
    `top_payloads` list
- Classifies tests into:
  - Present in both
  - Present only in baseline
  - Present only in comparison
- Prints a human-readable report to stdout and (optionally) writes a JSON
  summary when `--output-json` is provided.

This is designed to highlight where a given effect produces different USB
payload patterns between platforms.


## Interactive test runner (menu-driven workflow)

If you prefer not to remember the individual scripts and flags, you can use
an interactive orchestrator that wraps the whole workflow:

```bash
python scripts/interactive_test_runner.py
```

This script:

- Auto-discovers test suites in `tests/test_cases*.json`.
- Finds previous runs under `captures/` by looking for `manifest.json` and
  `analysis.json` files.
- Lets you, via a simple menu:
  - Select which test suite to work with.
  - Run captures for a new run (prompts for `ffbsdl` path, `tshark` path,
    capture interface, global gain, and output directory label).
  - Run a full workflow (captures + analysis, with an option to immediately
    compare the new analysis against an existing one).
  - Analyze an existing run whose captures are already in `captures/`.
  - Compare payloads **within** a run (wrapper around
    `scripts/compare_payloads.py`).
  - Compare analyses between **two** runs (wrapper around
    `scripts/compare_analysis.py`).
  - View an overview of all suites and whether they have been captured and/or
    analyzed.
  - Clean / delete old capture directories for a given suite.

The script prefers using the optional `questionary` library for a richer
TUI experience (arrow-key selection, checkboxes, etc.), but automatically
falls back to plain numbered prompts if `questionary` is not installed.

### Installing the optional TUI dependency (`questionary`)

`questionary` is **not required**, but recommended for a nicer interactive
experience. Install it into the same Python environment you use for the USB
harness scripts.

With [uv](https://github.com/astral-sh/uv) available in your shell (recommended):

```bash
uv pip install questionary
```

If you prefer plain `pip`, you can instead run:

```bash
python -m pip install questionary
```

After installation, rerun `python scripts/interactive_test_runner.py` – the
script will automatically enable the richer menus when `questionary` is
available.

## Directory layout and key files

- `ffbsdl.c`: main C source for the interactive/batch FFB tool.
- `scripts/run_usb_tests.py`: orchestrates `ffbsdl` runs and USB captures.
- `scripts/analyze_usb_pcaps.py`: converts `.pcapng` captures into
  `analysis.json`.
- `scripts/compare_analysis.py`: compares two `analysis.json` files.
- `tests/test_cases.json`: comprehensive single-effect test suite.
- `tests/test_cases_multi_effect.json`: multi-effect sequence test suite.
- `captures/`: default output root for pcapngs, manifests, and analyses.

## Optional SingleStore integration (remote storage)

The USB harness can optionally sync test suites and results to a remote
SingleStore database. This is completely optional; if the client library or
credentials are missing, the scripts fall back to local JSON files only.

### Configuring the database

1. Install the official Python client in the environment you use for the USB
   harness scripts. With [uv](https://github.com/astral-sh/uv) available
   (recommended):

   ```bash
   uv pip install singlestoredb
   ```

   If you prefer plain `pip`, you can instead run:

   ```bash
   python -m pip install singlestoredb
   ```

2. Point the scripts at your database using either:

   - `FFBSD_SINGLESTORE_URI` (recommended), for example `user:pass@host:3306/db`
   - or granular variables:

     - `FFBSD_SINGLESTORE_HOST`
     - `FFBSD_SINGLESTORE_PORT` (defaults to `3306`)
     - `FFBSD_SINGLESTORE_USER`
     - `FFBSD_SINGLESTORE_PASSWORD`
     - `FFBSD_SINGLESTORE_DATABASE`

If these variables are not set or the client library is missing, the
SingleStore integration is disabled and a small `[REMOTE] ...` message is
printed when you choose remote sync options.

### Users and API keys

SingleStore access is controlled by per-user API keys:

- Each user row has a `display_name` and a 64-character hex `api_key`.
- Scripts never send database passwords; they only send the API key.

At the moment, users/API keys are created manually by a SingleStore
administrator, for example:

```sql
INSERT INTO users (display_name, api_key)
VALUES ('alice', '<64-hex-character-random-token>');
```

Use that API key when prompted by the interactive runner (Settings → "Edit
SingleStore API key") or by passing `--remote-owner-api-key` on the CLI.

### What gets stored

When remote sync is enabled:

- `scripts/run_usb_tests.py` will:
  - Upsert a logical **test suite** (`test_suites` + `test_suite_versions`)
    using the JSON file under `tests/`.
  - Create or update a logical **test result** (`test_results` +
    `test_result_versions`) containing the `manifest.json` for a specific run.

- `scripts/analyze_usb_pcaps.py` can:
  - Attach an `analysis.json` document to the same logical result as a new
    immutable version.

Both suites and results support append-only versioning: each upload creates a
new version row with a timestamp; older versions remain queryable.

### CLI flags

- `scripts/run_usb_tests.py`:
  - `--remote-owner-api-key` – API key used to authenticate against SingleStore.
  - `--remote-suite-name` – optional logical name for the suite; defaults to
    the basename of `--tests-file`.

- `scripts/analyze_usb_pcaps.py`:
  - `--remote-owner-api-key` – same API key used for the capture run.

All uploaded suites and results are stored as shared/readable by other users
by default; owners still retain control for deleting or updating via new
versions.

The interactive runner (`scripts/interactive_test_runner.py`) wraps these flags
and, when a remote API key is configured in settings, automatically syncs
suites and results to SingleStore.


## Troubleshooting

- **Permission errors / cannot open interface (Linux)**
  - Ensure you have permission to read from usbmon devices. On many
    systems this requires `sudo` or adding your user to a group allowed to
    access `/sys/kernel/debug/usb/usbmon`.

- **Interface not found**
  - Run `tshark -D` to list available capture interfaces and use the exact
    name with `--iface`.

- **`tshark` not found**
  - Ensure Wireshark/tshark is installed and on the `PATH`. Otherwise pass
    the absolute path to `--tshark` (as in the Windows example above).

- **Wheel feels much stronger than expected**
  - Double-check both the OS-level device gain and the explicit
    `--gain` values you pass (via `ffbsdl` directly or
    `run_usb_tests.py --gain <value>`). A value like `5` corresponds to
    5% device gain.

If you run into issues that are not covered here, please open an issue with
as much detail as possible (platform, device, commands used, and logs).

