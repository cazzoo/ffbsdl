#!/usr/bin/env python3
import argparse
import json
import os
import platform
from collections import Counter, defaultdict
from datetime import datetime
from typing import Dict, List, Any


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


def group_by_effect_type(tests: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in tests:
        et = t.get("effect_type", "")
        groups[et].append(t)
    return groups


def filter_tests(tests: List[Dict[str, Any]], effect_type: str = None, id_contains: str = None) -> List[Dict[str, Any]]:
    out = []
    for t in tests:
        if effect_type and t.get("effect_type") != effect_type:
            continue
        if id_contains and id_contains not in t.get("id", ""):
            continue
        out.append(t)
    return out


def payload_to_bytes(payload_hex: str) -> bytes:
    payload_hex = payload_hex.replace(":", "").replace(" ", "")
    try:
        return bytes.fromhex(payload_hex)
    except ValueError:
        return b""


def diff_payloads(payloads: List[str]) -> Dict[int, Dict[str, Any]]:
    """Return a map of byte index -> {values, stable}.

    values: Counter of observed byte values at this position.
    stable: True if only one value observed.
    """
    if not payloads:
        return {}

    byte_rows = [payload_to_bytes(p) for p in payloads]
    max_len = max(len(b) for b in byte_rows)

    result: Dict[int, Dict[str, Any]] = {}
    for i in range(max_len):
        vals = []
        for row in byte_rows:
            if i < len(row):
                vals.append(row[i])
        counter = Counter(vals)
        result[i] = {"values": dict(counter), "stable": len(counter) == 1}
    return result


def collect_representative_payloads(test_entry: Dict[str, Any]) -> List[str]:
    top_payloads = test_entry.get("usb_summary", {}).get("top_payloads", [])
    payloads = [p.get("capdata") for p in top_payloads if isinstance(p, dict) and p.get("capdata")]
    # Fallback to sample frames if no aggregated payloads exist
    if not payloads:
        for frame in test_entry.get("usb_summary", {}).get("sample_frames", []):
            cap = frame.get("capdata")
            if cap:
                payloads.append(cap)
    return payloads


def compare_group_platform(tests: List[Dict[str, Any]], platforms: Dict[str, str], label: str) -> None:
    """Compare payloads across different platforms for the same effect type."""
    print(f"=== Cross-Platform Group: {label} (n={len(tests)}) ===")
    if not tests:
        print("(no tests)")
        return

    # Group tests by platform
    tests_by_platform: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in tests:
        test_id = t.get("id")
        platform = platforms.get(test_id, "Unknown")
        tests_by_platform[platform].append(t)

    # Print summary by platform
    for platform_name in sorted(tests_by_platform.keys()):
        platform_tests = tests_by_platform[platform_name]
        print(f"Platform: {platform_name} ({len(platform_tests)} tests)")
        for t in platform_tests:
            test_id = t.get("id")
            effect_type = t.get("effect_type")
            summary = t.get("usb_summary", {}) or {}
            total = summary.get("total_lines", summary.get("total_frames", 0))
            unique = summary.get("unique_payloads", 0)
            print(f"  - {test_id} [{effect_type}] frames={total} unique_payloads={unique}")
        print()

    # Compare payloads across platforms
    all_platform_payloads: Dict[str, List[str]] = {}
    for platform_name, platform_tests in tests_by_platform.items():
        platform_payloads: List[str] = []
        for t in platform_tests:
            platform_payloads.extend(collect_representative_payloads(t))
        all_platform_payloads[platform_name] = platform_payloads

    if len(all_platform_payloads) < 2:
        print("Need at least two platforms to compare.")
        print()
        return

    # Find differences between platforms
    platforms_list = sorted(all_platform_payloads.keys())
    print(f"Cross-platform payload comparison ({' vs '.join(platforms_list)}):")

    # Compare each pair of platforms
    for i in range(len(platforms_list)):
        for j in range(i + 1, len(platforms_list)):
            platform_a = platforms_list[i]
            platform_b = platforms_list[j]
            payloads_a = all_platform_payloads[platform_a]
            payloads_b = all_platform_payloads[platform_b]
            
            print(f"\n  {platform_a} vs {platform_b}:")
            
            # Show sample payloads from each platform
            if payloads_a:
                print(f"    {platform_a} sample payloads: {len(payloads_a)} total")
                for idx, payload in enumerate(payloads_a[:3]):  # Show first 3
                    print(f"      {idx+1}: {payload[:50]}{'...' if len(payload) > 50 else ''}")
                if len(payloads_a) > 3:
                    print(f"      ... and {len(payloads_a) - 3} more")
            
            if payloads_b:
                print(f"    {platform_b} sample payloads: {len(payloads_b)} total")
                for idx, payload in enumerate(payloads_b[:3]):  # Show first 3
                    print(f"      {idx+1}: {payload[:50]}{'...' if len(payload) > 50 else ''}")
                if len(payloads_b) > 3:
                    print(f"      ... and {len(payloads_b) - 3} more")

            # Find common and unique payloads
            set_a = set(payloads_a)
            set_b = set(payloads_b)
            common = set_a & set_b
            only_a = set_a - set_b
            only_b = set_b - set_a

            print(f"    Common payloads: {len(common)}")
            print(f"    Only in {platform_a}: {len(only_a)}")
            print(f"    Only in {platform_b}: {len(only_b)}")

            if only_a:
                print(f"    Sample payloads only in {platform_a}:")
                for idx, payload in enumerate(list(only_a)[:3]):
                    print(f"      {idx+1}: {payload[:50]}{'...' if len(payload) > 50 else ''}")
            
            if only_b:
                print(f"    Sample payloads only in {platform_b}:")
                for idx, payload in enumerate(list(only_b)[:3]):
                    print(f"      {idx+1}: {payload[:50]}{'...' if len(payload) > 50 else ''}")

    print()


def compare_group(tests: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
    """Compare group and return structured results for JSON output."""
    print(f"=== Group: {label} (n={len(tests)}) ===")
    if not tests:
        print("(no tests)")
        return {"label": label, "test_count": 0, "tests": [], "byte_variations": {}}

    # Collect test summaries
    test_summaries = []
    for t in tests:
        test_id = t.get("id")
        effect_type = t.get("effect_type")
        summary = t.get("usb_summary", {}) or {}
        total = summary.get("total_lines", summary.get("total_frames", 0))
        unique = summary.get("unique_payloads", 0)
        test_summaries.append({
            "id": test_id,
            "effect_type": effect_type,
            "frames": total,
            "unique_payloads": unique
        })
        print(f"- {test_id} [{effect_type}] frames={total} unique_payloads={unique}")

    # Flatten representative payloads for the group
    all_payloads: List[str] = []
    for t in tests:
        all_payloads.extend(collect_representative_payloads(t))

    diffs = diff_payloads(all_payloads)
    changing_positions = [i for i, info in diffs.items() if not info["stable"]]
    print(f"Byte positions that vary across this group: {changing_positions}")

    # Show the distribution at each varying position
    byte_variations = {}
    for i in changing_positions:
        info = diffs[i]
        vals = ", ".join(f"0x{b:02x}x{cnt}" for b, cnt in sorted(info["values"].items()))
        print(f"  index {i}: {vals}")
        byte_variations[str(i)] = info["values"]

    print()

    return {
        "label": label,
        "test_count": len(tests),
        "tests": test_summaries,
        "byte_variations": byte_variations
    }


def create_payload_comparison_metadata(analysis_paths: List[str], all_analyses: List[Dict[str, Any]], 
                                      effect_type: str = None, id_contains: str = None, 
                                      cross_platform: bool = False) -> Dict[str, Any]:
    """Create metadata header for payload comparison results."""
    all_tests = []
    for analysis in all_analyses:
        tests = analysis.get("tests", [])
        if effect_type:
            tests = [t for t in tests if t.get("effect_type") == effect_type]
        if id_contains:
            tests = [t for t in tests if id_contains in t.get("id", "")]
        all_tests.extend(tests)
    
    return {
        "comparison_info": {
            "datetime": datetime.utcnow().isoformat() + "Z",
            "analysis_files": analysis_paths,
            "filters": {
                "effect_type": effect_type,
                "id_contains": id_contains,
                "cross_platform": cross_platform
            },
            "total_tests_analyzed": len(all_tests),
            "test_ids": [test.get("id") for test in all_tests],
            "platforms_used": list(set(extract_platform_from_analysis(analysis["_file_path"], analysis) 
                                     for analysis in all_analyses))
        }
    }


def create_payload_comparison_manifest(results: List[Dict[str, Any]], metadata: Dict[str, Any], 
                                      output_path: str) -> None:
    """Create a complete payload comparison manifest with metadata header and results."""
    manifest = {
        **metadata,
        "comparison_results": {
            "groups": results
        }
    }
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[DONE] Wrote payload comparison manifest to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare USB payload patterns across tests using analysis.json files",
    )
    parser.add_argument(
        "--analysis",
        action="append",
        help="Path to analysis.json generated by analyze_usb_pcaps.py (can specify multiple times)",
    )
    parser.add_argument(
        "--effect-type",
        help="Filter tests by effect type (e.g., constant, sine, ramp, spring)",
    )
    parser.add_argument(
        "--id-contains",
        help="Filter tests whose ID contains this substring (e.g., 'constant_level_', 'ramp_')",
    )
    parser.add_argument(
        "--cross-platform",
        action="store_true",
        help="Compare payloads across different platforms (Linux vs Windows)",
    )
    parser.add_argument(
        "--output-json",
        help="Path to write JSON comparison results with metadata",
    )

    args = parser.parse_args()
    
    # Handle default analysis path if none specified
    analysis_paths = args.analysis or ["captures/analysis.json"]
    
    # Load all analysis files
    all_analyses = []
    platforms = {}
    for path in analysis_paths:
        try:
            analysis = load_analysis(path)
            analysis["_file_path"] = path
            all_analyses.append(analysis)
            print(f"Loaded analysis from: {path}")
        except FileNotFoundError:
            print(f"Warning: Analysis file not found: {path}")
            continue
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")
            continue

    if not all_analyses:
        print("Error: No analysis files could be loaded.")
        return

    # Collect all tests and their platforms
    all_tests = []
    for analysis in all_analyses:
        platform = extract_platform_from_analysis(analysis["_file_path"], analysis)
        tests = analysis.get("tests", [])
        for test in tests:
            test_id = test.get("id")
            if test_id:
                platforms[test_id] = platform
        all_tests.extend(tests)

    if not all_tests:
        print("Warning: No tests found in analysis files.")

    filtered = filter_tests(all_tests, effect_type=args.effect_type, id_contains=args.id_contains)
    
    # Collect results for JSON output
    comparison_results = []

    if args.cross_platform and len(all_analyses) > 1:
        # Cross-platform comparison mode
        print("=== Cross-Platform Comparison Mode ===")
        
        # Group by effect type for cross-platform comparison
        groups = group_by_effect_type(filtered)
        for effect_type, group in sorted(groups.items()):
            label = effect_type
            if args.id_contains:
                label += f" (id contains '{args.id_contains}')"
            compare_group_platform(group, platforms, label)
            
            # Add to results for JSON (simplified version)
            comparison_results.append({
                "type": "cross_platform",
                "label": label,
                "effect_type": effect_type,
                "test_count": len(group),
                "test_ids": [t.get("id") for t in group],
                "platforms": {t.get("id"): platforms.get(t.get("id"), "Unknown") for t in group}
            })
    else:
        # Traditional single-analysis comparison mode
        if len(all_analyses) > 1:
            print("Note: Multiple analysis files loaded but --cross-platform not specified.")
            print("Using combined analysis for traditional comparison.")
        
        # Further group by effect type to make patterns clearer
        groups = group_by_effect_type(filtered)
        for effect_type, group in sorted(groups.items()):
            label = effect_type
            if args.id_contains:
                label += f" (id contains '{args.id_contains}')"
            result = compare_group(group, label)
            comparison_results.append(result)

    # Handle JSON output
    if args.output_json:
        metadata = create_payload_comparison_metadata(analysis_paths, all_analyses, 
                                                    args.effect_type, args.id_contains, 
                                                    args.cross_platform)
        create_payload_comparison_manifest(comparison_results, metadata, args.output_json)
    else:
        print("Note: Use --output-json to save results to file.")


if __name__ == "__main__":
    main()

