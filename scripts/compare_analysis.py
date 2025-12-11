#!/usr/bin/env python3
import argparse
import json
import os
import platform
from datetime import datetime
from typing import Any, Dict, List, Tuple


def load_analysis(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def detect_platform_from_path(path: str) -> str:
    """Detect platform (linux/windows) from directory path."""
    path_lower = path.lower()
    if "windows" in path_lower:
        return "Windows"
    elif "linux" in path_lower:
        return "Linux"
    else:
        return "Unknown"


def extract_platform_from_analysis(analysis_path: str, analysis_data: Dict[str, Any]) -> str:
    """Extract platform information from analysis data and path."""
    # First try to get from manifest path
    manifest_path = analysis_data.get("manifest", "")
    if manifest_path:
        platform_name = detect_platform_from_path(manifest_path)
        if platform_name != "Unknown":
            return platform_name
    
    # Fall back to analysis file path
    platform_name = detect_platform_from_path(analysis_path)
    if platform_name != "Unknown":
        return platform_name
    
    # Last resort: use current system
    return platform.system()


def index_tests_by_id(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for t in analysis.get("tests", []):
        tid = t.get("id")
        if not tid:
            continue
        out[tid] = t
    return out


def compare_usb_summary(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two usb_summary dicts at a detailed level.

    Focus on fields from analysis.json: total_lines, unique_payloads, top_payloads, sample_frames.
    Include detailed payload sequence comparison and inconsistencies.
    """

    def payload_set(summary: Dict[str, Any]) -> List[str]:
        top = summary.get("top_payloads") or []
        return sorted({p.get("capdata") for p in top if isinstance(p, dict) and p.get("capdata")})

    def compare_payload_sequences(sa: Dict[str, Any], sb: Dict[str, Any]) -> Dict[str, Any]:
        """Compare the sequences of payloads from sample_frames."""
        frames_a = sa.get("sample_frames", [])
        frames_b = sb.get("sample_frames", [])

        seq_a = [f.get("capdata") for f in frames_a if f.get("capdata")]
        seq_b = [f.get("capdata") for f in frames_b if f.get("capdata")]

        # Find differences in sequence
        min_len = min(len(seq_a), len(seq_b))
        sequence_differences = []
        for i in range(min_len):
            if seq_a[i] != seq_b[i]:
                sequence_differences.append({
                    "position": i,
                    "a": seq_a[i],
                    "b": seq_b[i]
                })

        missing_in_b = len(seq_a) - len(seq_b) if len(seq_a) > len(seq_b) else 0
        extra_in_b = len(seq_b) - len(seq_a) if len(seq_b) > len(seq_a) else 0

        return {
            "sequence_length_a": len(seq_a),
            "sequence_length_b": len(seq_b),
            "sequence_differences": sequence_differences,
            "missing_packets_in_b": missing_in_b,
            "extra_packets_in_b": extra_in_b,
            "total_packets_a": len(seq_a),
            "total_packets_b": len(seq_b)
        }

    sa = a or {}
    sb = b or {}

    total_a = sa.get("total_lines", sa.get("total_frames"))
    total_b = sb.get("total_lines", sb.get("total_frames"))
    uniq_a = sa.get("unique_payloads")
    uniq_b = sb.get("unique_payloads")

    payloads_a = payload_set(sa)
    payloads_b = payload_set(sb)

    only_in_a = sorted(list(set(payloads_a) - set(payloads_b)))
    only_in_b = sorted(list(set(payloads_b) - set(payloads_a)))
    in_both = sorted(list(set(payloads_a) & set(payloads_b)))

    # Detailed sequence comparison
    sequence_comparison = compare_payload_sequences(sa, sb)

    changed = False
    if (total_a != total_b or uniq_a != uniq_b or only_in_a or only_in_b or
        sequence_comparison["sequence_differences"] or
        sequence_comparison["missing_packets_in_b"] or
        sequence_comparison["extra_packets_in_b"]):
        changed = True

    return {
        "changed": changed,
        "total_lines": {"a": total_a, "b": total_b},
        "unique_payloads": {"a": uniq_a, "b": uniq_b},
        "payloads_only_in_a": only_in_a,
        "payloads_only_in_b": only_in_b,
        "payloads_in_both": in_both,
        "sequence_comparison": sequence_comparison,
    }


def compare_tests(baseline: Dict[str, Any], comparison: Dict[str, Any], baseline_path: str, comparison_path: str) -> Dict[str, Any]:
    idx_a = index_tests_by_id(baseline)
    idx_b = index_tests_by_id(comparison)

    # Detect platforms
    platform_a = extract_platform_from_analysis(baseline_path, baseline)
    platform_b = extract_platform_from_analysis(comparison_path, comparison)

    all_ids = sorted(set(idx_a.keys()) | set(idx_b.keys()))

    results = {
        "summary": {
            "platform_a": platform_a,
            "platform_b": platform_b,
            "baseline_path": baseline_path,
            "comparison_path": comparison_path,
            "total_tests_a": len(idx_a),
            "total_tests_b": len(idx_b),
            "matched_ids": [],
            "only_in_a": [],
            "only_in_b": [],
        },
        "per_test": {},
    }

    # Track drifting values for footer
    drifting_summary = {
        "total_tests_compared": 0,
        "tests_with_differences": 0,
        "tests_with_payload_differences": 0,
        "effect_type_differences": {},
        "significant_drifting_tests": [],
        "detailed_inconsistencies": []
    }

    for tid in all_ids:
        ta = idx_a.get(tid)
        tb = idx_b.get(tid)
        if ta and tb:
            results["summary"]["matched_ids"].append(tid)
            usb_a = ta.get("usb_summary") or {}
            usb_b = tb.get("usb_summary") or {}
            usb_diff = compare_usb_summary(usb_a, usb_b)

            results["per_test"][tid] = {
                "id": tid,
                "effect_type_a": ta.get("effect_type"),
                "effect_type_b": tb.get("effect_type"),
                "description_a": ta.get("description"),
                "description_b": tb.get("description"),
                "input_params_a": ta.get("input_params", {}),
                "input_params_b": tb.get("input_params", {}),
                "usb_diff": usb_diff,
            }

            # Update drifting summary
            drifting_summary["total_tests_compared"] += 1
            effect_type = ta.get("effect_type") or tb.get("effect_type", "unknown")

            if usb_diff.get("changed", False):
                drifting_summary["tests_with_differences"] += 1

                # Count by effect type
                if effect_type not in drifting_summary["effect_type_differences"]:
                    drifting_summary["effect_type_differences"][effect_type] = 0
                drifting_summary["effect_type_differences"][effect_type] += 1

                # Check for payload differences (significant drifting)
                if usb_diff.get("payloads_only_in_a") or usb_diff.get("payloads_only_in_b"):
                    drifting_summary["tests_with_payload_differences"] += 1
                    drifting_summary["significant_drifting_tests"].append({
                        "id": tid,
                        "effect_type": effect_type,
                        "description": ta.get("description", ""),
                        "payloads_only_in_a": len(usb_diff.get("payloads_only_in_a", [])),
                        "payloads_only_in_b": len(usb_diff.get("payloads_only_in_b", []))
                    })

                # Add detailed inconsistency for this test
                seq_comp = usb_diff.get("sequence_comparison", {})
                inconsistency = {
                    "test_id": tid,
                    "test_name": ta.get("description", ""),
                    "effect_type": effect_type,
                    "input_params": ta.get("input_params", {}),
                    "platform_a": platform_a,
                    "platform_b": platform_b,
                    "key_inconsistencies": {
                        "total_packets_a": seq_comp.get("total_packets_a", 0),
                        "total_packets_b": seq_comp.get("total_packets_b", 0),
                        "missing_packets_in_b": seq_comp.get("missing_packets_in_b", 0),
                        "extra_packets_in_b": seq_comp.get("extra_packets_in_b", 0),
                        "sequence_differences": seq_comp.get("sequence_differences", []),
                        "unique_payloads_a": usb_diff.get("unique_payloads", {}).get("a", 0),
                        "unique_payloads_b": usb_diff.get("unique_payloads", {}).get("b", 0),
                        "payloads_only_in_a": usb_diff.get("payloads_only_in_a", []),
                        "payloads_only_in_b": usb_diff.get("payloads_only_in_b", [])
                    }
                }
                drifting_summary["detailed_inconsistencies"].append(inconsistency)

        elif ta and not tb:
            results["summary"]["only_in_a"].append(tid)
            results["per_test"][tid] = {
                "id": tid,
                "only_in": "a",
                "effect_type_a": ta.get("effect_type"),
                "description_a": ta.get("description"),
            }
        elif tb and not ta:
            results["summary"]["only_in_b"].append(tid)
            results["per_test"][tid] = {
                "id": tid,
                "only_in": "b",
                "effect_type_b": tb.get("effect_type"),
                "description_b": tb.get("description"),
            }

    # Add footer with drifting summary
    results["drifting_summary"] = drifting_summary

    return results


def print_human_readable_report(results: Dict[str, Any]) -> None:
    summary = results.get("summary", {})
    print("=== Compare analysis.json (baseline vs comparison) ===")
    print(f"Platform A ({summary.get('baseline_path')}): {summary.get('platform_a', 'Unknown')}")
    print(f"Platform B ({summary.get('comparison_path')}): {summary.get('platform_b', 'Unknown')}")
    print(f"Total tests in A: {summary.get('total_tests_a')}")
    print(f"Total tests in B: {summary.get('total_tests_b')}")
    print(f"Matched test IDs: {len(summary.get('matched_ids', []))}")
    print(f"Only in A: {len(summary.get('only_in_a', []))}")
    print(f"Only in B: {len(summary.get('only_in_b', []))}")
    print()

    # Add cross-platform specific analysis if platforms are different
    platform_a = summary.get('platform_a', '')
    platform_b = summary.get('platform_b', '')
    if platform_a != platform_b and platform_a != 'Unknown' and platform_b != 'Unknown':
        print("=== Cross-Platform Analysis ===")
        print(f"Comparing {platform_a} vs {platform_b} captures")
        
        # Count differences by effect type
        effect_differences: Dict[str, int] = {}
        payload_differences = 0
        
        for tid, entry in results.get("per_test", {}).items():
            if "usb_diff" in entry:
                effect_type = entry.get("effect_type_a") or entry.get("effect_type_b", "unknown")
                usb_diff = entry.get("usb_diff", {})
                if usb_diff.get("changed", False):
                    effect_differences[effect_type] = effect_differences.get(effect_type, 0) + 1
                    if usb_diff.get("payloads_only_in_a") or usb_diff.get("payloads_only_in_b"):
                        payload_differences += 1
        
        print(f"Tests with different USB summaries: {sum(effect_differences.values())}")
        print(f"Tests with different payloads: {payload_differences}")
        
        if effect_differences:
            print("Differences by effect type:")
            for effect_type, count in sorted(effect_differences.items()):
                print(f"  {effect_type}: {count} tests")
        print()

    for tid in sorted(results.get("per_test", {}).keys()):
        entry = results["per_test"][tid]
        print(f"--- Test ID: {tid} ---")
        only_in = entry.get("only_in")
        if only_in == "a":
            print("Present only in baseline (A)")
            print(f"  effect_type_a: {entry.get('effect_type_a')}")
            print(f"  description_a: {entry.get('description_a')}")
            print()
            continue
        if only_in == "b":
            print("Present only in comparison (B)")
            print(f"  effect_type_b: {entry.get('effect_type_b')}")
            print(f"  description_b: {entry.get('description_b')}")
            print()
            continue

        usb_diff = entry.get("usb_diff", {})
        changed = usb_diff.get("changed")
        print(f"effect_type: A={entry.get('effect_type_a')} B={entry.get('effect_type_b')}")
        print(f"description A: {entry.get('description_a')}")
        print(f"description B: {entry.get('description_b')}")
        print(f"USB summary changed: {changed}")
        totals = usb_diff.get("total_lines", {})
        uniq = usb_diff.get("unique_payloads", {})
        print(f"  total_lines: A={totals.get('a')} B={totals.get('b')}")
        print(f"  unique_payloads: A={uniq.get('a')} B={uniq.get('b')}")
        only_a = usb_diff.get("payloads_only_in_a") or []
        only_b = usb_diff.get("payloads_only_in_b") or []
        if only_a or only_b:
            print("  Payload differences:")
            if only_a:
                print(f"    only in A ({len(only_a)}):")
                for p in only_a[:10]:
                    print(f"      {p}")
                if len(only_a) > 10:
                    print("      ...")
            if only_b:
                print(f"    only in B ({len(only_b)}):")
                for p in only_b[:10]:
                    print(f"      {p}")
                if len(only_b) > 10:
                    print("      ...")
            print()
    
        # Add footer with drifting summary
        drifting = results.get("drifting_summary", {})
        if drifting.get("total_tests_compared", 0) > 0:
            print("=== DRIFTING SUMMARY ===")
            print(f"Total tests compared: {drifting['total_tests_compared']}")
            print(f"Tests with differences: {drifting['tests_with_differences']} ({drifting['tests_with_differences']/drifting['total_tests_compared']*100:.1f}%)")
            print(f"Tests with payload differences: {drifting['tests_with_payload_differences']} ({drifting['tests_with_payload_differences']/drifting['total_tests_compared']*100:.1f}%)")
    
            if drifting.get("effect_type_differences"):
                print("\nDifferences by effect type:")
                for effect_type, count in sorted(drifting["effect_type_differences"].items()):
                    percentage = count / drifting['total_tests_compared'] * 100
                    print(f"  {effect_type}: {count} tests ({percentage:.1f}%)")
    
            if drifting.get("significant_drifting_tests"):
                print(f"\nSignificant drifting tests ({len(drifting['significant_drifting_tests'])}):")
                for test in drifting["significant_drifting_tests"][:10]:  # Show first 10
                    print(f"  {test['id']} [{test['effect_type']}] - A:{test['payloads_only_in_a']}, B:{test['payloads_only_in_b']}")
                if len(drifting["significant_drifting_tests"]) > 10:
                    print(f"  ... and {len(drifting['significant_drifting_tests']) - 10} more")

            if drifting.get("detailed_inconsistencies"):
                print(f"\n=== DETAILED INCONSISTENCIES ({len(drifting['detailed_inconsistencies'])}) ===")
                print(f"{'Test ID':<30} {'Effect':<10} {'Packets A/B':<12} {'Missing/Extra':<12} {'Seq Diffs':<10} {'Unique A/B':<10}")
                print("-" * 100)
                for inc in drifting["detailed_inconsistencies"]:
                    key = inc["key_inconsistencies"]
                    seq_diffs = len(key["sequence_differences"])
                    print(f"{inc['test_id']:<30} {inc['effect_type']:<10} {key['total_packets_a']}/{key['total_packets_b']:<12} {key['missing_packets_in_b']}/{key['extra_packets_in_b']:<12} {seq_diffs:<10} {key['unique_payloads_a']}/{key['unique_payloads_b']:<10}")
                print()
                # Optionally show details for first few
                for inc in drifting["detailed_inconsistencies"][:3]:
                    print(f"Details for {inc['test_id']}:")
                    key = inc["key_inconsistencies"]
                    if key["payloads_only_in_a"]:
                        print(f"  Payloads only in {inc['platform_a']}: {key['payloads_only_in_a'][:3]}...")
                    if key["payloads_only_in_b"]:
                        print(f"  Payloads only in {inc['platform_b']}: {key['payloads_only_in_b'][:3]}...")
                    if key["sequence_differences"]:
                        print(f"  Sequence differences: {len(key['sequence_differences'])} positions differ")
                    print()
            print()


def create_comparison_metadata(baseline_path: str, comparison_path: str, baseline_data: Dict[str, Any], comparison_data: Dict[str, Any]) -> Dict[str, Any]:
    """Create metadata header for comparison results."""
    return {
        "comparison_info": {
            "datetime": datetime.utcnow().isoformat() + "Z",
            "baseline_file": baseline_path,
            "comparison_file": comparison_path,
            "baseline_tests": [test.get("id") for test in baseline_data.get("tests", [])],
            "comparison_tests": [test.get("id") for test in comparison_data.get("tests", [])],
            "baseline_platform": extract_platform_from_analysis(baseline_path, baseline_data),
            "comparison_platform": extract_platform_from_analysis(comparison_path, comparison_data),
            "baseline_manifest": baseline_data.get("manifest", ""),
            "comparison_manifest": comparison_data.get("manifest", ""),
            "total_baseline_tests": len(baseline_data.get("tests", [])),
            "total_comparison_tests": len(comparison_data.get("tests", [])),
        }
    }


def create_comparison_manifest(results: Dict[str, Any], metadata: Dict[str, Any], output_path: str) -> None:
    """Create a complete comparison manifest with metadata header and results."""
    manifest = {
        **metadata,
        "comparison_results": results
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[DONE] Wrote comparison manifest to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two analysis.json files (e.g. Linux vs Windows captures) "
            "produced by analyze_usb_pcaps.py."
        )
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to baseline analysis.json (e.g. Linux run).",
    )
    parser.add_argument(
        "--comparison",
        required=True,
        help="Path to comparison analysis.json (e.g. Windows run).",
    )
    parser.add_argument(
        "--output-json",
        help=(
            "Optional path to write a JSON summary of differences. If omitted, "
            "only the human-readable report is printed to stdout."
        ),
    )
    parser.add_argument(
        "--output-manifest",
        help=(
            "Optional path to write a complete JSON manifest with metadata header. "
            "Takes precedence over --output-json if both specified."
        ),
    )

    args = parser.parse_args()

    baseline = load_analysis(args.baseline)
    comparison = load_analysis(args.comparison)

    results = compare_tests(baseline, comparison, args.baseline, args.comparison)

    print_human_readable_report(results)

    # Handle output files
    if args.output_manifest:
        metadata = create_comparison_metadata(args.baseline, args.comparison, baseline, comparison)
        create_comparison_manifest(results, metadata, args.output_manifest)
    elif args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"[DONE] Wrote JSON comparison report to {args.output_json}")
    else:
        print("Note: Use --output-json or --output-manifest to save results to file.")


if __name__ == "__main__":
    main()

