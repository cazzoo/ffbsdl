#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
from collections import Counter


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
    - In that case we transparently fall back to a simpler field set that
      only requires "usb.capdata".
    """

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

    # First try the full field set (preferred when available).
    primary_fields = [
        "frame.number",
        "frame.time_relative",
        "usb.endpoint_number",
        "usb.transfer_type",
        "usb.capdata",
    ]
    proc = run_tshark(primary_fields)

    # If tshark complains about invalid fields, fall back to a minimal set
    # that should work everywhere.
    if proc.returncode != 0 and "Some fields aren't valid" in (proc.stderr or ""):
        fallback_fields = [
            "frame.number",
            "frame.time_relative",
            "usb.capdata",
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
        "--tshark",
        default="tshark",
        help="Path to tshark executable (must match the capture environment).",
    )
    parser.add_argument(
        "--display-filter",
        default="usb && usb.capdata",
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
        results["tests"].append(
            {
                "id": entry.get("id"),
                "effect_type": entry.get("effect_type"),
                "description": entry.get("description", ""),
                "input_params": entry.get("params", {}),
                "pcap_file": pcap_path,
                "usb_summary": summary,
            }
        )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[DONE] Wrote analysis to {args.output}")


if __name__ == "__main__":
    main()

