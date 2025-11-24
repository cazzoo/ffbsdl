#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from collections import Counter

from typing import Any, Dict

try:
    from scripts.singlestore_client import (
        SingleStoreNotConfigured,
        authenticate_user,
        ensure_schema,
        upsert_test_suite,
        create_or_update_test_result,
        list_suites_for_user,
    )
except Exception:  # pragma: no cover - remote DB is optional
    SingleStoreNotConfigured = RuntimeError  # type: ignore
    authenticate_user = None  # type: ignore
    ensure_schema = None  # type: ignore
    upsert_test_suite = None  # type: ignore
    create_or_update_test_result = None  # type: ignore
    list_suites_for_user = None  # type: ignore


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_usb_summary(tshark, pcap_path, display_filter):
    """Extract USB payloads from a pcapng file using tshark.

    The goal is not full decoding, but a structured view of payload bytes
    and simple statistics that can be correlated with test inputs.

    This helper is intentionally defensive:
    - Some tshark builds (e.g. on certain Arch/Manjaro versions) don't
      support fields like "usb.endpoint_number".
    - Some capture setups expose the payload bytes as "usb.capdata", others
      (notably USB HID on Windows via USBPcap) use "usbhid.data" instead.
    - We therefore try a small set of candidate payload fields and fall back
      to a simpler field set when needed.
    """

    CANDIDATE_PAYLOAD_FIELDS = ["usb.capdata", "usbhid.data"]

    def run_tshark(field_names):
        cmd = [
            tshark,
            "-r",
            pcap_path,
            "-T",
            "fields",
        ]
        for name in field_names:
            cmd.extend(["-e", name])
        cmd.extend(
            [
                "-E",
                "separator=,",
                "-E",
                "quote=n",
                "-E",
                "occurrence=f",
            ]
        )
        if display_filter:
            cmd.extend(["-Y", display_filter])
        return subprocess.run(cmd, capture_output=True, text=True, check=False)

    def extract_for_payload_field(payload_field):
        # First try the full field set (preferred when available).
        primary_fields = [
            "frame.number",
            "frame.time_relative",
            "usb.endpoint_number",
            "usb.transfer_type",
            payload_field,
        ]
        proc = run_tshark(primary_fields)

        # If tshark complains about invalid fields, fall back to a minimal set
        # that should work everywhere.
        if proc.returncode != 0 and "Some fields aren't valid" in (proc.stderr or ""):
            fallback_fields = [
                "frame.number",
                "frame.time_relative",
                payload_field,
            ]
            proc = run_tshark(fallback_fields)
            using_fallback = True
        else:
            using_fallback = False

        lines = proc.stdout.splitlines()

        payload_counts = Counter()
        sample_frames = []

        for line in lines:
            if not line.strip():
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue

            # Layout depends on whether we used the full or fallback field set.
            if using_fallback:
                frame_no, t_rel, capdata = (parts + ["", ""])[:3]
                endpoint = ""
                ttype = ""
            else:
                if len(parts) < 5:
                    continue
                frame_no, t_rel, endpoint, ttype, capdata = parts[:5]

            if not capdata:
                continue

            payload_counts[capdata] += 1
            if len(sample_frames) < 32:
                try:
                    frame_num = int(frame_no)
                except ValueError:
                    frame_num = None
                try:
                    t_rel_val = float(t_rel)
                except ValueError:
                    t_rel_val = None
                sample_frames.append(
                    {
                        "frame": frame_num,
                        "time_relative": t_rel_val,
                        "endpoint": endpoint,
                        "transfer_type": ttype,
                        "capdata": capdata,
                    }
                )

        top_payloads = [
            {"capdata": cap, "count": count}
            for cap, count in payload_counts.most_common()
        ]

        return {
            "total_lines": len(lines),
            "unique_payloads": len(payload_counts),
            "top_payloads": top_payloads,
            "sample_frames": sample_frames,
            "payload_field": payload_field,
            "using_fallback_fields": using_fallback,
        }

    last_summary = None
    for field in CANDIDATE_PAYLOAD_FIELDS:
        summary = extract_for_payload_field(field)
        last_summary = summary
        if summary["unique_payloads"] > 0:
            return summary

    if last_summary is not None:
        return last_summary

    # Extremely unlikely: tshark produced no output at all for any field.
    return {
        "total_lines": 0,
        "unique_payloads": 0,
        "top_payloads": [],
        "sample_frames": [],
        "payload_field": None,
        "using_fallback_fields": False,
    }


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Analyze USB pcapng captures produced by run_usb_tests.py and "
            "correlate them with test case input parameters."
        )
    )
    parser.add_argument(
        "--manifest",
        default=os.path.join("captures", "manifest.json"),
        help="Path to manifest.json written by run_usb_tests.py.",
    )
    parser.add_argument(
        "--remote-owner-api-key",
        help=(
            "Optional API key for uploading analysis.json to SingleStore. "
            "If omitted, runs only locally."
        ),
    )

    parser.add_argument(
        "--tshark",
        default="tshark",
        help="Path to tshark executable (must match the capture environment).",
    )
    parser.add_argument(
        "--display-filter",
        default="usb",
        help="Tshark display filter used when extracting USB records.",
    )
    parser.add_argument(
        "--output",
        default=os.path.join("captures", "analysis.json"),
        help="Where to write the structured analysis JSON.",
    )

    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    results = {
        "manifest": os.path.abspath(args.manifest),
        "tshark": args.tshark,
        "display_filter": args.display_filter,
        "tests": [],
    }

    for entry in manifest.get("tests", []):
        pcap_path = entry["pcap_file"]
        print(f"[ANALYZE] {entry['id']} -> {pcap_path}")
        summary = extract_usb_summary(args.tshark, pcap_path, args.display_filter)

        # For multi-effect sequence tests, the runner records
        # entry["effect_type"] == "sequence" and provides detailed
        # per-step information in entry["sequence"]. We thread this
        # structure through into the analysis output so downstream
        # consumers can correlate USB payload patterns with the
        # individual effects that were intended to be active.
        results_entry = {
            "id": entry.get("id"),
            "effect_type": entry.get("effect_type"),
            "description": entry.get("description", ""),
            "input_params": entry.get("params", {}),
            "pcap_file": pcap_path,
            "usb_summary": summary,
        }
        if "sequence" in entry:
            results_entry["sequence"] = entry["sequence"]

        results["tests"].append(results_entry)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[DONE] Wrote analysis to {args.output}")

    # Optionally upload analysis to SingleStore as a new result version attached
    # to the logical result created from the manifest upload.
    api_key = getattr(args, "remote_owner_api_key", None)
    if (
        api_key
        and authenticate_user
        and ensure_schema
        and create_or_update_test_result
    ):
        try:
            user = authenticate_user(api_key)
        except SingleStoreNotConfigured as exc:  # pragma: no cover
            print(f"[REMOTE] SingleStore not configured: {exc}")
            user = None
        except Exception as exc:  # pragma: no cover
            print(f"[REMOTE] Failed to authenticate user: {exc}")
            user = None

        if user is None:
            print("[REMOTE] Invalid API key or SingleStore unavailable; skipping upload.")
        else:
            try:
                ensure_schema()
            except Exception as exc:  # pragma: no cover
                print(f"[REMOTE] Failed to ensure schema: {exc}")
            else:
                from os.path import basename

                suite_name = manifest.get("suite_name")
                tests_file = manifest.get("tests_file")
                if not suite_name and tests_file:
                    suite_name = basename(tests_file)

                suite = None
                # First try to find an existing suite for this user and name.
                try:
                    if list_suites_for_user:
                        for s in list_suites_for_user(user.id):
                            if s.name == suite_name:
                                suite = s
                                break
                except Exception as exc:  # pragma: no cover
                    print(f"[REMOTE] Failed to look up existing suites: {exc}")

                # If no suite exists yet but we know the tests file, create one now.
                if suite is None and tests_file and upsert_test_suite:
                    try:
                        with open(tests_file, "r", encoding="utf-8") as tf:
                            suite_json = json.load(tf)
                        suite, suite_version = upsert_test_suite(
                            owner_user_id=user.id,
                            name=suite_name or basename(tests_file),
                            suite_json=suite_json,
                            is_shared=True,
                        )
                        print(
                            "[REMOTE] Created suite "
                            f"'{suite.name}' as id={suite.id} v{suite_version} for analysis upload"
                        )
                    except FileNotFoundError:  # pragma: no cover
                        print(
                            f"[REMOTE] Tests file {tests_file!r} not found; "
                            "cannot create suite for analysis upload."
                        )
                    except Exception as exc:  # pragma: no cover
                        print(f"[REMOTE] Failed to create suite for analysis upload: {exc}")

                if suite is None:
                    print(
                        "[REMOTE] Could not determine or create suite; skipping analysis upload."
                    )
                else:
                    try:
                        label = f"manifest:{os.path.abspath(args.manifest)}"
                        _res, v = create_or_update_test_result(
                            owner_user_id=user.id,
                            suite_id=suite.id,
                            label=label,
                            manifest_json=manifest,
                            analysis_json=results,
                            is_shared=True,
                        )
                        print(
                            "[REMOTE] Uploaded analysis for result id="
                            f"{_res.id} as new version v{v}"
                        )
                    except Exception as exc:  # pragma: no cover
                        print(f"[REMOTE] Failed to upload analysis: {exc}")
    elif api_key:
        print(
            "[REMOTE] singlestore_client not available; skipping remote upload."
        )


if __name__ == "__main__":
    main()

