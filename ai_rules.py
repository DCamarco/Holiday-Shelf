"""
ai_rules.py — deterministic checks on a shortlist plan.

Each rule reads the dict from ai_context.build_context() and returns Findings
with the exact numbers behind them. These work with no API key: they are the
facts Gemini ranks and explains (ai_review.py), and the fallback cards when
Gemini is unavailable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

MAX_CATEGORY_SHARE_PCT = 40
ANCHOR_PRICE = 50  # Black Friday week needs at least one gift at or above this
STUFFER_PRICE = 20  # Mid-Dec needs at least one stocking stuffer below this


@dataclass
class Finding:
    id: str
    severity: str  # "high" | "medium" | "low"
    title: str
    message: str  # plain-language sentence, shown when the AI is unavailable
    products: list[str] = field(default_factory=list)
    numbers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}%"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_plan_size(ctx: dict) -> list[Finding]:
    plan = ctx["plan"]
    n, lo, hi = plan["count"], plan["target_min"], plan["target_max"]
    if n == 0 or lo <= n <= hi:
        return []
    if n < lo:
        msg = f"The plan has {n} products; the brief asks for {lo}–{hi}. Add {lo - n} more."
    else:
        msg = f"The plan has {n} products; the brief asks for {lo}–{hi}. Cut {n - hi}."
    return [
        Finding("plan_size", "medium", "Plan size is outside 10–15", msg,
                numbers={"count": n, "target_min": lo, "target_max": hi})
    ]


def rule_category_overload(ctx: dict) -> list[Finding]:
    out = []
    n = ctx["plan"]["count"]
    for c in ctx["plan"]["category_mix"]:
        if c["count"] >= 3 and c["share_pct"] > MAX_CATEGORY_SHARE_PCT:
            names = [p["name"] for p in ctx["picks"] if p["category"] == c["name"]]
            out.append(
                Finding(
                    "category_overload", "high",
                    f"Too much {c['name']}",
                    f"{c['count']} of {n} picks ({c['share_pct']}%) are {c['name']}. "
                    f"Shoppers who don't want {c['name']} see little else.",
                    products=names,
                    numbers={"count": c["count"], "plan_count": n, "share_pct": c["share_pct"],
                             "limit_pct": MAX_CATEGORY_SHARE_PCT},
                )
            )
    return out


def rule_empty_phase(ctx: dict) -> list[Finding]:
    empty = ctx["plan"]["empty_phases"]
    if ctx["plan"]["count"] == 0 or not empty:
        return []
    sev = "high" if "Black Friday / Cyber Monday" in empty or len(empty) >= 2 else "medium"
    listed = empty[0] if len(empty) == 1 else ", ".join(empty[:-1]) + " and " + empty[-1]
    return [
        Finding("empty_phase", sev, f"Nothing planned for {listed}",
                f"No picks are scheduled for {listed}, so that part of the season has no featured products.",
                numbers={"phases": empty, "count": 0})
    ]


def rule_phase_mismatch(ctx: dict) -> list[Finding]:
    out = []
    for p in ctx["picks"]:
        rec = p.get("recommended_phase")
        if rec and p.get("phase") and p["phase"] != rec:
            out.append(
                Finding("phase_mismatch", "medium", f"{p['name']}: phase differs from history",
                        f"{p['name']} is planned for {p['phase']}, but it sold best per week in {rec} "
                        f"(Season Playbook).",
                        products=[p["name"]],
                        numbers={"planned": p["phase"], "recommended": rec})
            )
    return out


def rule_weak_data(ctx: dict) -> list[Finding]:
    out = []
    for p in ctx["picks"]:
        if not p["weak_data"]:
            continue
        reasons = "; ".join(p["weak_reasons"])
        detail = ""
        if p["view_to_buy_pct"] is not None:
            detail = (f" Its rate is {_fmt_pct(p['view_to_buy_pct'])} from {p['views']} views "
                      f"(range {_fmt_pct(p['ci_low_pct'])}–{_fmt_pct(p['ci_high_pct'])}).")
        out.append(
            Finding("weak_data", "medium", f"{p['name']}: thin evidence",
                    f"{p['name']} rests on weak data ({reasons}).{detail}",
                    products=[p["name"]],
                    numbers={k: p[k] for k in ("views", "view_to_buy_pct", "ci_low_pct", "ci_high_pct")})
        )
    return out


def rule_downgrade(ctx: dict) -> list[Finding]:
    out = []
    for p in ctx["picks"]:
        old, old_lo, new_lo = p.get("replaces"), p.get("replaces_ci_low_pct"), p.get("ci_low_pct")
        if old and old_lo is not None and new_lo is not None and old_lo > new_lo:
            out.append(
                Finding("downgrade", "high", f"{p['name']} may be a downgrade",
                        f"{p['name']} replaces {old}, but {old} has the stronger floor: its rate is at least "
                        f"{_fmt_pct(old_lo)} versus {_fmt_pct(new_lo)} for {p['name']}.",
                        products=[p["name"], old],
                        numbers={"new_ci_low_pct": new_lo, "old_ci_low_pct": old_lo})
            )
    return out


def rule_price_anchors(ctx: dict) -> list[Finding]:
    out = []
    by_phase: dict[str, list[dict]] = {}
    for p in ctx["picks"]:
        by_phase.setdefault(p.get("phase"), []).append(p)

    bf = by_phase.get("Black Friday / Cyber Monday", [])
    if bf and not any((p["price"] or 0) >= ANCHOR_PRICE for p in bf):
        out.append(
            Finding("no_anchor", "low", "No big-ticket gift for Black Friday",
                    f"None of the {len(bf)} Black Friday / Cyber Monday picks costs ${ANCHOR_PRICE} or more, "
                    "so there is no anchor gift for the biggest shopping week.",
                    products=[p["name"] for p in bf],
                    numbers={"count": len(bf), "threshold": ANCHOR_PRICE})
        )
    md = by_phase.get("Mid-Dec", [])
    if md and not any(p["price"] is not None and p["price"] < STUFFER_PRICE for p in md):
        out.append(
            Finding("no_stuffer", "low", "No stocking stuffer for Mid-Dec",
                    f"None of the {len(md)} Mid-Dec picks costs under ${STUFFER_PRICE}, "
                    "so last-minute small gifts are missing.",
                    products=[p["name"] for p in md],
                    numbers={"count": len(md), "threshold": STUFFER_PRICE})
        )
    return out


def rule_addon_evidence(ctx: dict, min_orders: int = 2) -> list[Finding]:
    """A cart add-on should have been bought with its anchor (or another pick) before."""
    out = []
    for p in ctx["picks"]:
        if p.get("slot") != "Cart add-on":
            continue
        best = max(p.get("pair_orders") or 0, p.get("plan_pair_orders") or 0)
        if best >= min_orders:
            continue
        out.append(
            Finding("addon_no_evidence", "medium", f"{p['name']}: add-on without bundle evidence",
                    f"{p['name']} is a cart add-on, but it was bought together with any other pick "
                    f"in only {best} orders (fewer than {min_orders}).",
                    products=[p["name"]],
                    numbers={"min_orders": min_orders, "best_pair_orders": best})
        )
    return out


RULES = [
    rule_plan_size,
    rule_category_overload,
    rule_empty_phase,
    rule_downgrade,
    rule_phase_mismatch,
    rule_weak_data,
    rule_addon_evidence,
    rule_price_anchors,
]


def run_rules(ctx: dict) -> list[Finding]:
    """All findings, most severe first."""
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(ctx))
    return sorted(findings, key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
