"""Experimental trait-supported estimates; never alert eligible."""
from statistics import median
import math

VERSION = "trait-support-research-v1"

def estimate(target, sales):
    gift=target["gift"]
    out={"version":VERSION,"status":"ABSTAIN","alert_eligible":False,"reasons":[]}
    if not all(gift.get(k) for k in ("slug","model","backdrop","pattern")):
        return dict(out,reasons=["MISSING_TRAITS"])
    if gift["num"]<=1000:
        return dict(out,reasons=["LOW_SERIAL_NOT_MODELED"])
    unique={}
    for sale in sorted(sales,key=lambda s:s["at"]):
        g=sale["gift"]
        price=sale.get("price_ton")
        if (g.get("slug"),g.get("model"))!=(gift["slug"],gift["model"]): continue
        if g["num"]==gift["num"] or g["num"]<=1000: continue
        if not target["at"]-604800<=sale["at"]<target["at"]: continue
        if sale["observed_at"]>target["observed_at"]: continue
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0: continue
        unique[g["num"]]=sale
    peers=list(unique.values())
    out["model_comparable_count"]=len(peers)
    if len(peers)<5:
        return dict(out,reasons=["INSUFFICIENT_MODEL_SALES"])
    # Require evidence for each secondary trait; matching either alone is insufficient.
    for trait in ("backdrop","pattern"):
        if sum(s["gift"].get(trait)==gift[trait] for s in peers)<3:
            out["reasons"].append("INSUFFICIENT_"+trait.upper()+"_SUPPORT")
    if out["reasons"]: return out
    prices=[s["price_ton"] for s in peers]
    value=median(prices)
    mad=median(abs(p-value) for p in prices)/value
    if mad>.15: return dict(out,reasons=["DISPERSED_SALES"])
    return dict(out,status="RESEARCH_ESTIMATE",estimated_value_ton=value,relative_mad=mad,
                comparable_event_ids=[s["id"] for s in peers],
                reasons=["TRAIT_INTERACTIONS_UNMODELED","NOT_PROSPECTIVELY_VALIDATED","EXECUTION_UNVERIFIED"])
