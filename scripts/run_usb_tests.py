#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import time


def load_tests(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_param_value(name, value, key_levels):
    # Allow using symbolic key levels like "low"/"high" that map to numeric values.
    if isinstance(value, str):
        levels_for_param = key_levels.get(name) or {}
        if value in levels_for_param:
            return levels_for_param[value]
    return value


def build_cli_args(effect_type, params, defaults, key_levels, binary):
    """Build ffbsdl CLI arguments for a single effect.

    This helper is used both for legacy single-effect tests and for each
    step in a multi-effect *sequence* test. The caller is responsible for
    passing the concrete effect_type and the per-effect params dict.
    """

    merged = dict(defaults)
    merged.update(params or {})

    # Resolve symbolic levels into concrete integers using key_levels
    resolved = {}
    for k, v in merged.items():
        resolved[k] = resolve_param_value(k, v, key_levels)

    param_flags = {
        "direction_deg": "--direction-deg",
        "length_ms": "--length-ms",
        "delay_ms": "--delay-ms",
        "gain": "--gain",
        "level": "--level",
        "magnitude": "--magnitude",
        "period_ms": "--period-ms",
        "offset": "--offset",
        "phase_deg": "--phase-deg",
        "attack_length_ms": "--attack-length-ms",
        "attack_level": "--attack-level",
        "fade_length_ms": "--fade-length-ms",
        "fade_level": "--fade-level",
        "iterations": "--iterations",
        "ramp_start": "--ramp-start",
        "ramp_end": "--ramp-end",
        "cond_right_sat": "--cond-right-sat",
        "cond_left_sat": "--cond-left-sat",
        "cond_right_coeff": "--cond-right-coeff",
        "cond_left_coeff": "--cond-left-coeff",
        "cond_deadband": "--cond-deadband",
        "cond_center": "--cond-center",
    }

    args = [binary, "--effect-type", effect_type]
    for name, flag in param_flags.items():
        if name in resolved and resolved[name] is not None:
            args.extend([flag, str(resolved[name])])

    return args, resolved


def run_single_effect_capture(base_name, effect_type, params, defaults, key_levels, cli_args):
    """Capture USB traffic for a *single* effect invocation.

    This is used directly for legacy single-effect tests, and is also
    called repeatedly for each step in a multi-effect sequence test while
    tshark is already running.
    """

    os.makedirs(cli_args.output_dir, exist_ok=True)
    pcap_path = os.path.join(cli_args.output_dir, base_name + ".pcapng")

    ff_args, resolved_params = build_cli_args(
        effect_type, params, defaults, key_levels, cli_args.ffb_binary
    )

    # If a global gain override was provided on the runner CLI, force it
    # into the resolved params for this invocation so every effect in the
    # run uses a consistent device gain. This is threaded through as
    # --gain to ffbsdl's batch-mode CLI.
    if getattr(cli_args, "global_gain", None) is not None:
        resolved_params["gain"] = cli_args.global_gain
        ff_args, _ = build_cli_args(
            effect_type, resolved_params, {}, key_levels, cli_args.ffb_binary
        )

    print(f"[RUN] {base_name}: {effect_type} -> {pcap_path}")
    sys.stdout.flush()

    ff_result = subprocess.run(ff_args)

    return pcap_path, resolved_params, ff_result.returncode


def run_single_test(index, test, defaults, key_levels, cli_args):
    """Run either a legacy single-effect test or a multi-effect sequence.

    Legacy tests have top-level "effect_type" and "params" fields.

    Multi-effect tests instead provide a "sequence" array. Each entry in
    the sequence must have "effect_type" and "params". Optionally a
    "start_ms" field can be provided to document intended scheduling of
    effects within the *conceptual* timeline of the test. The current
    implementation does not yet align tshark/ffbsdl invocations to these
    timestamps – each step simply runs to completion in order – but the
    information is preserved in the manifest for downstream analysis.
    """

    test_id = test["id"]
    description = test.get("description", "")

    sequence = test.get("sequence")

    # Case 1: legacy single-effect test (backward compatible path)
    if not sequence:
        effect_type = test["effect_type"]
        base_name = f"{index:04d}_{test_id}_{effect_type}"

        # Start tshark for this one effect
        os.makedirs(cli_args.output_dir, exist_ok=True)
        pcap_path = os.path.join(cli_args.output_dir, base_name + ".pcapng")

        tshark_cmd = [cli_args.tshark, "-i", cli_args.iface, "-w", pcap_path]
        if cli_args.capture_filter:
            tshark_cmd.extend(["-f", cli_args.capture_filter])

        print(f"[RUN] Test {index}: {test_id} ({effect_type}) -> {pcap_path}")
        sys.stdout.flush()

        tshark_proc = subprocess.Popen(
            tshark_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        # Give tshark a moment to start capturing
        time.sleep(cli_args.pre_delay)

        pcap_path, resolved_params, returncode = run_single_effect_capture(
            base_name, effect_type, test.get("params", {}), defaults, key_levels, cli_args
        )

        # Ensure we capture tail of any remaining USB traffic
        time.sleep(cli_args.post_delay)

        tshark_proc.terminate()
        try:
            tshark_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tshark_proc.kill()

        return {
            "id": test_id,
            "effect_type": effect_type,
            "description": description,
            "pcap_file": pcap_path,
            "params": resolved_params,
            "cli_returncode": returncode,
        }

    # Case 2: multi-effect sequence test
    base_name = f"{index:04d}_{test_id}_sequence"
    os.makedirs(cli_args.output_dir, exist_ok=True)
    pcap_path = os.path.join(cli_args.output_dir, base_name + ".pcapng")

    tshark_cmd = [cli_args.tshark, "-i", cli_args.iface, "-w", pcap_path]
    if cli_args.capture_filter:
        tshark_cmd.extend(["-f", cli_args.capture_filter])

    print(f"[RUN] Test {index}: {test_id} [sequence of {len(sequence)} effects] -> {pcap_path}")
    sys.stdout.flush()

    tshark_proc = subprocess.Popen(
        tshark_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # Give tshark a moment to start capturing before the first step
    time.sleep(cli_args.pre_delay)

    step_results = []

    for step_index, step in enumerate(sequence, start=1):
        step_effect_type = step["effect_type"]
        step_params = step.get("params", {})
        step_id = step.get("id") or f"step{step_index}"
        start_ms = step.get("start_ms")

        step_base = f"{base_name}_{step_index:02d}_{step_id}_{step_effect_type}"
        print(
            f"  [STEP {step_index}] {step_id}: {step_effect_type} "
            f"(start_ms={start_ms!r})"
        )
        sys.stdout.flush()

        # NOTE: For now we simply run each step immediately one after the
        # other. The conceptual start_ms is *not* yet enforced as a
        # scheduling constraint; it is recorded purely for analysis so
        # that USB packet patterns can be correlated with intended timing.
        _step_pcap, resolved_params, returncode = run_single_effect_capture(
            step_base,
            step_effect_type,
            step_params,
            defaults,
            key_levels,
            cli_args,
        )

        step_results.append(
            {
                "id": step_id,
                "effect_type": step_effect_type,
                "params": resolved_params,
                "start_ms": start_ms,
                "cli_returncode": returncode,
            }
        )

    # Ensure we capture tail of any remaining USB traffic
    time.sleep(cli_args.post_delay)

    tshark_proc.terminate()
    try:
        tshark_proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        tshark_proc.kill()

    return {
        "id": test_id,
        "effect_type": "sequence",
        "description": description,
        "pcap_file": pcap_path,
        "sequence": step_results,
    }


def main():
    default_ffb = "./ffbsdl"
    if os.name == "nt":
        default_ffb = os.path.join("bin", "win64", "ffbsdl.exe")

    parser = argparse.ArgumentParser(
        description="Run USB haptic tests and capture USB traffic with tshark."
    )
    parser.add_argument(
        "--tests-file", default="tests/test_cases.json", help="JSON file with test cases.",
    )
    parser.add_argument(
        "--ffb-binary",
        default=default_ffb,
        help="Path to ffbsdl binary (non-interactive mode enabled via CLI parameters).",
    )
    parser.add_argument(
        "--tshark", default="tshark", help="Path to tshark executable.",
    )
    parser.add_argument(
        "--iface", required=True, help="Capture interface name (e.g. usbmon1 or \\.\\USBPcap1).",
    )
    parser.add_argument(
        "--output-dir", default="captures", help="Directory for generated pcapng files.",
    )
    parser.add_argument(
        "--capture-filter",
        default="",
        help="Optional tshark capture filter expression (e.g. 'usb').",
    )
    parser.add_argument(
        "--pre-delay",
        type=float,
        default=0.5,
        help="Seconds to wait after starting tshark before running ffbsdl.",
    )
    parser.add_argument(
        "--post-delay",
        type=float,
        default=0.5,
        help="Seconds to wait after ffbsdl exits before stopping tshark.",
    )
    parser.add_argument(
        "--gain",
        type=int,
        dest="global_gain",
        help=(
            "Optional global force feedback gain (0-100). If set, overrides any per-test "
            "gain value in the JSON and is passed to ffbsdl as --gain for each effect."
        ),
    )

    args = parser.parse_args()

    tests_doc = load_tests(args.tests_file)
    defaults = tests_doc.get("defaults", {})
    key_levels = tests_doc.get("key_levels", {})
    tests = tests_doc.get("tests", [])

    manifest = {
        "tests_file": os.path.abspath(args.tests_file),
        "ffb_binary": os.path.abspath(args.ffb_binary),
        "iface": args.iface,
        "tshark": args.tshark,
        "output_dir": os.path.abspath(args.output_dir),
        "tests": [],
    }

    for idx, test in enumerate(tests, start=1):
        result = run_single_test(idx, test, defaults, key_levels, args)
        manifest["tests"].append(result)

    manifest_path = os.path.join(args.output_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[DONE] Wrote manifest to {manifest_path}")


if __name__ == "__main__":
    main()

