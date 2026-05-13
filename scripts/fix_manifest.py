#!/usr/bin/env python3
"""
Fix manifest.jsonl:
1. Sort by timestamp (ascending)
2. Reassign tick numbers sequentially (1, 2, 3, ...)
3. Remove duplicate entries (same action_type + similar timestamp)
"""

import json
from pathlib import Path

MANIFEST_PATH = Path("/home/bcyq/XIA/data/xia_voice/manifest.jsonl")

def main():
    # Read all records
    records = []
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    print(f"Read {len(records)} records")

    # Sort by timestamp
    records.sort(key=lambda r: r.get("timestamp", 0))

    print(f"Sorted by timestamp. First timestamp: {records[0]['timestamp']}")
    print(f"Last timestamp: {records[-1]['timestamp']}")

    # Deduplicate: group by timestamp, keep the last one per timestamp
    # (last one has the most "settled" state)
    seen_ts = {}
    for r in records:
        ts = r.get("timestamp")
        seen_ts[ts] = r  # overwrite: later entry wins

    deduped = list(seen_ts.values())
    deduped.sort(key=lambda r: r.get("timestamp", 0))
    print(f"After dedup: {len(deduped)} records (removed {len(records) - len(deduped)} duplicates)")

    # Reassign tick numbers
    for i, r in enumerate(deduped):
        r["tick"] = i + 1

    # Write back
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        for r in deduped:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Written {len(deduped)} records. Tick range: 1–{len(deduped)}")

    # Verify
    prev_ts = 0
    prev_tick = 0
    ok = True
    for r in deduped:
        if r["timestamp"] < prev_ts:
            print(f"  ERROR: timestamp decreased at tick {r['tick']}")
            ok = False
        if r["tick"] <= prev_tick:
            print(f"  ERROR: tick not increasing at timestamp {r['timestamp']}")
            ok = False
        prev_ts = r["timestamp"]
        prev_tick = r["tick"]

    if ok:
        print("Verification passed: timestamps and ticks are monotonically increasing.")

    # Print sample
    print("\nFirst 5 records:")
    for r in deduped[:5]:
        print(f"  tick={r['tick']} action={r['action_type']} loneliness={r['context'].get('loneliness', 'N/A')}")

    print("\nLast 5 records:")
    for r in deduped[-5:]:
        print(f"  tick={r['tick']} action={r['action_type']} loneliness={r['context'].get('loneliness', 'N/A')}")

if __name__ == "__main__":
    main()
