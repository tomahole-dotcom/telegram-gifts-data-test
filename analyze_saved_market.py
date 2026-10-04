"""Offline comparables audit: no network, no trading, no generated buy signals."""
import json
import time
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path.home() / ".local/share/telegram-gifts-data-test"

def traits(row):
    return {t["type"]: t["name"] for t in row.get("traits", [])}

def analyze(data):
    # Evaluate freshness as of capture, so repeating this audit gives stable results.
    at = data.get("finished_at") or data.get("started_at") or time.time()
    rows = list({r["slug"]: r for r in data["listings"]}.values())
    sales = []
    for row in rows:
        evidence = row.get("sale_evidence", {})
        timestamp = evidence.get("last_sale_timestamp")
        price = evidence.get("last_sale_price_minor")
        currency = evidence.get("currency")
        if timestamp and price is not None and price > 0 and currency and 0 <= at-timestamp <= 7*86400:
            sales.append(row)
    levels = {
        "model_backdrop_symbol": ("StarGiftAttributeModel", "StarGiftAttributeBackdrop", "StarGiftAttributePattern"),
        "model_backdrop": ("StarGiftAttributeModel", "StarGiftAttributeBackdrop"),
        "model": ("StarGiftAttributeModel",),
    }
    report = {"valuation_status": "NOT_VALIDATED", "recent_sales": len(sales), "levels": {}}
    for name, fields in levels.items():
        groups = defaultdict(list)
        def key(row):
            values = traits(row)
            if not all(values.get(f) for f in fields):
                return None
            currency = row.get("sale_evidence", {}).get("currency")
            if not currency:
                return None
            return (currency,) + tuple(values[f] for f in fields)
        for row in sales:
            group = key(row)
            if group:
                groups[group].append(row)
        eligible = 0
        for row in rows:
            # Own last sale must never count as a comparable for this listing.
            comps = [r for r in groups.get(key(row), []) if r["slug"] != row["slug"]]
            if len(comps) >= 5:
                eligible += 1
        largest = []
        for group, members in sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)[:5]:
            prices = [r["sale_evidence"]["last_sale_price_minor"] for r in members]
            middle = median(prices)
            largest.append({"currency": group[0], "traits": list(group[1:]), "sales": len(members),
                            "median_minor": middle, "min_minor": min(prices), "max_minor": max(prices),
                            "relative_median_absolute_deviation": round(median([abs(p-middle) for p in prices])/middle, 3)})
        report["levels"][name] = {"listings_with_at_least_5_other_recent_sales": eligible, "largest_groups": largest}
    report["limitations"] = [
        "Last sale per currently listed gift only; not the full market's completed sales.",
        "Broader trait matches are diagnostics, not validated valuation models.",
        "Fiat sale prices and TON/Stars listing prices have not been normalized.",
        "Serial, omitted traits, fees and execution risk are not priced in."
    ]
    return report

if __name__ == "__main__":
    data = json.loads((ROOT / "telegram-wide-probe.json").read_text())
    report = analyze(data)
    output = ROOT / "comparables-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    output.chmod(0o600)
    print("OFFLINE AUDIT | recent sales:", report["recent_sales"])
    for level, result in report["levels"].items():
        print(level, "| listings with 5+ OTHER comparable sales:",
              result["listings_with_at_least_5_other_recent_sales"])
        for group in result["largest_groups"][:3]:
            print(" ", " / ".join(group["traits"]), "|", group["currency"],
                  "| sales:", group["sales"], "| median (minor units):", group["median_minor"],
                  "| range:", group["min_minor"], "-", group["max_minor"])
    print("Opportunity NOT VALIDATED. No alert sent.")
    print("Saved:", output)
