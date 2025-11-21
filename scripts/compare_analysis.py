#!/usr/bin/env python3
import argparse
import json
from typing import Any, Dict, List, Tuple


def load_analysis(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_tests_by_id(analysis: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for t in analysis.get("tests", []):
        tid = t.get("id")
        if not tid:
            continue
        out[tid] = t
    return out


def compare_usb_summary(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two usb_summary dicts at a coarse level.

    We intentionally focus on high-signal fields that exist in the
    analysis.json produced by analyze_usb_pcaps.py: total_lines,
    unique_payloads, top_payloads, sample_frames.
    """

    def payload_set(summary: Dict[str, Any]) -> List[str]:
        top = summary.get("top_payloads") or []
        return sorted({p.get("capdata") for p in top if isinstance(p, dict) and p.get("capdata")})

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

    changed = False
    if total_a != total_b or uniq_a != uniq_b or only_in_a or only_in_b:
        changed = True

    return {
        "changed": changed,
        "total_lines": {"a": total_a, "b": total_b},
        "unique_payloads": {"a": uniq_a, "b": uniq_b},
        "payloads_only_in_a": only_in_a,
        "payloads_only_in_b": only_in_b,
        "payloads_in_both": in_both,
    }


def compare_tests(baseline: Dict[str, Any], comparison: Dict[str, Any]) -> Dict[str, Any]:
    idx_a = index_tests_by_id(baseline)
    idx_b = index_tests_by_id(comparison)

    all_ids = sorted(set(idx_a.keys()) | set(idx_b.keys()))

    results = {
        "summary": {
            "total_tests_a": len(idx_a),
            "total_tests_b": len(idx_b),
            "matched_ids": [],
            "only_in_a": [],
            "only_in_b": [],
        },
        "per_test": {},
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
                "usb_diff": usb_diff,
            }
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

    return results


def print_human_readable_report(results: Dict[str, Any]) -> None:
    summary = results.get("summary", {})
    print("=== Compare analysis.json (baseline vs comparison) ===")
    print(f"Total tests in A: {summary.get('total_tests_a')}")
    print(f"Total tests in B: {summary.get('total_tests_b')}")
    print(f"Matched test IDs: {len(summary.get('matched_ids', []))}")
    print(f"Only in A: {len(summary.get('only_in_a', []))}")
    print(f"Only in B: {len(summary.get('only_in_b', []))}")
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

    args = parser.parse_args()

    baseline = load_analysis(args.baseline)
    comparison = load_analysis(args.comparison)

    results = compare_tests(baseline, comparison)

    print_human_readable_report(results)

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"[DONE] Wrote JSON comparison report to {args.output_json}")


if __name__ == "__main__":
    main()

