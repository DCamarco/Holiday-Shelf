"""
ai_review.py — Gemini reviews the merchandiser's plan, then every word is checked.

Flow:
  context (ai_context) + findings (ai_rules)
    -> Gemini, with a strict JSON response schema
    -> verify(): unknown products, unverifiable numbers and causal claims are removed
    -> ReviewResult shown in the app (ai_panel)
With no API key, or on any error, the rule findings are returned instead, so the
app never breaks.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ai_context import PHASES, SLOTS
from ai_rules import Finding

DEFAULT_MODEL = "gemini-3.8-flash"  # newest GA Flash on Agent Platform (Nov 2026)
THINKING_LEVEL = "LOW"  # LOW / MEDIUM / HIGH; LOW keeps reviews fast
TIMEOUT_MS = 45_000  # slower than this, show rule checks instead

BANNED_PHRASES = [
    "will sell", "will increase", "will boost", "will drive", "will grow",
    "guarantee", "guaranteed", "causes", "caused by", "proven to",
]

# Small whole numbers ("3 picks", "2 swaps", "10–15") are counts the model can
# derive itself; anything else must match a value in the context.
FREE_INTEGERS = set(range(0, 21))


# ---------------------------------------------------------------------------
# Response schema (sent to Gemini; also validates what comes back)
# ---------------------------------------------------------------------------


class Issue(BaseModel):
    severity: Literal["high", "medium", "low"]
    title: str = Field(description="Short title, under 8 words.")
    explanation: str = Field(description="1-3 plain sentences for a merchandiser, using only given numbers.")
    products: list[str] = Field(default_factory=list, description="Exact product names involved.")


class Action(BaseModel):
    type: Literal["swap", "move_phase", "remove"]
    product: str = Field(description="Exact name of the pick in the plan this action changes.")
    add: Optional[str] = Field(default=None, description="For swap: exact name from swap_pool to add.")
    phase: Optional[str] = Field(default=None, description="Holiday phase for the added or moved product.")
    slot: Optional[str] = Field(default=None, description="Placement slot for the added product.")
    reason: str = Field(description="One sentence, using only given numbers.")


class Review(BaseModel):
    headline: str = Field(description="One sentence summarising the plan's biggest problem.")
    issues: list[Issue]
    actions: list[Action]


@dataclass
class ReviewResult:
    source: Literal["gemini", "rules"]
    review: Review
    log: list[dict] = field(default_factory=list)  # {kept, item, reason}
    error: Optional[str] = None
    planted: bool = False


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTION = f"""You are a senior e-commerce merchandiser reviewing a colleague's
holiday shelf plan for the Google Merchandise Store. The plan picks 10-15 products
and assigns each a holiday phase and a placement slot.

You receive FACTS (JSON) and RULE_FINDINGS (problems found by exact checks).
Your job: decide which problems matter most, explain them plainly, and propose fixes.

Strict rules:
- Use ONLY numbers that appear in FACTS or RULE_FINDINGS, copied exactly as written.
  Do not compute new percentages, averages or differences. If unsure, use no number.
- Use product names EXACTLY as written in FACTS. Never invent products.
- Swaps may only ADD products listed in FACTS.swap_pool. The product being changed
  must be a pick in FACTS.picks.
- Phases must be one of: {", ".join(PHASES)}.
  Slots must be one of: {", ".join(SLOTS)}.
- Describe what the data shows; never predict sales or claim causes
  (no "will sell", "will increase", "causes", "guaranteed").
- Return at most 5 issues, most important first, and at most 3 actions.
  Prefer actions that fix more than one problem at once.
- Write for a busy merchandiser: short, concrete, no statistics jargon
  ("range" not "confidence interval").
"""


def build_prompt(ctx: dict, findings: list[Finding]) -> str:
    return (
        "FACTS:\n" + json.dumps(ctx, ensure_ascii=False)
        + "\n\nRULE_FINDINGS:\n" + json.dumps([f.to_dict() for f in findings], ensure_ascii=False)
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?%?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _walk_numbers(obj: Any, out: set[float]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_numbers(v, out)


def allowed_numbers(ctx: dict, findings: list[Finding]) -> set[float]:
    nums: set[float] = set()
    _walk_numbers(ctx, nums)
    for f in findings:
        _walk_numbers(f.numbers, nums)
    return nums


def _number_ok(text_num: str, decimals: str | None, allowed: set[float]) -> bool:
    value = float(text_num.replace(",", "") + ("." + decimals if decimals else ""))
    if not decimals and value in FREE_INTEGERS:
        return True
    places = len(decimals) if decimals else 0
    for a in allowed:
        if round(a, places) == round(value, places):
            return True
    return False


def _strip_names(text: str, names: set[str]) -> str:
    """Remove product and phase names so digits inside them aren't checked."""
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, " ")
    return text


def check_text(text: str, allowed: set[float], names: set[str]) -> Optional[str]:
    """None if the text passes, otherwise the reason it fails."""
    low = text.lower()
    for phrase in BANNED_PHRASES:
        if phrase in low:
            return f'causal or predictive claim ("{phrase}")'
    for m in _NUMBER.finditer(_strip_names(text, names)):
        if not _number_ok(m.group(1), m.group(2), allowed):
            return f'number "{m.group(0)}" is not in the data'
    return None


def _clean_text(text: str, where: str, allowed, names, log) -> str:
    kept = []
    for sentence in _SENTENCE.split(text.strip()):
        if not sentence:
            continue
        problem = check_text(sentence, allowed, names)
        if problem:
            log.append({"kept": False, "item": f"{where}: {sentence}", "reason": problem})
        else:
            kept.append(sentence)
    return " ".join(kept)


def verify(
    review: Review,
    ctx: dict,
    findings: list[Finding],
    catalog_names: Optional[set[str]] = None,
) -> tuple[Review, list[dict]]:
    """Drop anything the data can't back up. Returns (clean review, log)."""
    log: list[dict] = []
    allowed = allowed_numbers(ctx, findings)
    pick_names = {p["name"] for p in ctx["picks"]}
    pool_names = {p["name"] for p in ctx["swap_pool"]}
    related = {p["replaces"] for p in ctx["picks"] if p.get("replaces")}
    related |= {p["paired_with"] for p in ctx["picks"] if p.get("paired_with")}
    related |= {p["best_addon"]["addon"] for p in ctx["picks"] + ctx["swap_pool"] if p.get("best_addon")}
    known = pick_names | pool_names | related
    strip = known | set(PHASES) | (catalog_names or set())

    def mentions_unknown(text: str) -> Optional[str]:
        for name in (catalog_names or set()) - known:
            if name in text:
                return name
        return None

    headline = _clean_text(review.headline, "headline", allowed, strip, log)
    if not headline or mentions_unknown(headline):
        headline = ""

    issues = []
    for i, issue in enumerate(review.issues, 1):
        bad = [p for p in issue.products if p not in known]
        if bad:
            log.append({"kept": False, "item": f"issue {i}: {issue.title}",
                        "reason": f"unknown product {bad[0]!r}"})
            continue
        unknown = mentions_unknown(issue.explanation)
        if unknown:
            log.append({"kept": False, "item": f"issue {i}: {issue.title}",
                        "reason": f"mentions product outside the plan and swap pool ({unknown!r})"})
            continue
        if check_text(issue.title, allowed, strip):
            log.append({"kept": False, "item": f"issue {i} title: {issue.title}",
                        "reason": check_text(issue.title, allowed, strip)})
            continue
        explanation = _clean_text(issue.explanation, f"issue {i}", allowed, strip, log)
        if not explanation:
            continue
        issues.append(issue.model_copy(update={"explanation": explanation}))
        log.append({"kept": True, "item": f"issue {i}: {issue.title}", "reason": "all numbers and names verified"})

    actions = []
    for i, a in enumerate(review.actions, 1):
        problem = None
        if a.product not in pick_names:
            problem = f"{a.product!r} is not in the plan"
        elif a.type == "swap" and a.add not in pool_names:
            problem = f"{a.add!r} is not in the swap pool"
        elif a.type == "move_phase" and a.phase not in PHASES:
            problem = f"unknown phase {a.phase!r}"
        elif a.phase is not None and a.phase not in PHASES:
            problem = f"unknown phase {a.phase!r}"
        elif a.slot is not None and a.slot not in SLOTS:
            problem = f"unknown slot {a.slot!r}"
        else:
            problem = check_text(a.reason, allowed, strip)
        if problem:
            log.append({"kept": False, "item": f"action {i}: {a.type} {a.product}", "reason": problem})
            continue
        actions.append(a)
        log.append({"kept": True, "item": f"action {i}: {a.type} {a.product}", "reason": "valid products and numbers"})

    if not headline and issues:
        headline = issues[0].title
    return Review(headline=headline, issues=issues, actions=actions), log


# ---------------------------------------------------------------------------
# Rule-only review (no key, errors, or everything dropped)
# ---------------------------------------------------------------------------


def rules_review(ctx: dict, findings: list[Finding]) -> Review:
    issues = [
        Issue(severity=f.severity, title=f.title, explanation=f.message, products=f.products)
        for f in findings
    ]
    picks = {p["name"]: p for p in ctx["picks"]}
    actions = [
        Action(type="move_phase", product=f.products[0], phase=f.numbers["recommended"],
               reason=f"Season Playbook: it sold best per week in {f.numbers['recommended']}.")
        for f in findings
        if f.id == "phase_mismatch" and f.products and f.products[0] in picks
    ][:3]
    headline = findings[0].title if findings else "No problems found."
    return Review(headline=headline, issues=issues, actions=actions)


# ---------------------------------------------------------------------------
# Demo: plant a wrong number so the audience sees verification catch it
# ---------------------------------------------------------------------------


def plant_wrong_number(review: Review) -> Review:
    if not review.issues:
        return review
    first = review.issues[0]
    m = re.search(r"\d+(?:\.\d+)?", first.explanation)
    if m:
        wrong = f"{float(m.group(0)) * 3 + 7.3:.1f}"
        text = first.explanation[: m.start()] + wrong + first.explanation[m.end():]
    else:
        text = first.explanation + " Last season this group converted at 87.3% of views."
    issues = [first.model_copy(update={"explanation": text})] + review.issues[1:]
    return review.model_copy(update={"issues": issues})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def make_client(api_key: str, vertexai: bool = True):
    """Agent Platform key by default (enterprise=True, formerly vertexai=True);
    pass vertexai=False for an AI Studio (Gemini Developer API) key."""
    from google import genai  # imported lazily so tests and no-key runs don't need it
    from google.genai import types

    return genai.Client(
        enterprise=vertexai,
        api_key=api_key,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
    )


def call_gemini(client, model: str, ctx: dict, findings: list[Finding]) -> Review:
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=build_prompt(ctx, findings),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=Review,
            # Gemini 3.8 ignores temperature/top_p/top_k; effort is set here instead.
            thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
        ),
    )
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, Review):
        return parsed
    return Review.model_validate_json(response.text)


def review_plan(
    ctx: dict,
    findings: list[Finding],
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    client=None,
    catalog_names: Optional[set[str]] = None,
    plant_mistake: bool = False,
    call=call_gemini,
    vertexai: bool = True,
) -> ReviewResult:
    """Gemini review if possible, rule review otherwise. Never raises."""
    if not ctx["picks"]:
        return ReviewResult("rules", rules_review(ctx, findings))
    if client is None and not api_key:
        return ReviewResult("rules", rules_review(ctx, findings), error="No GEMINI_API_KEY set.")
    try:
        client = client or make_client(api_key, vertexai)
        raw = call(client, model, ctx, findings)
    except Exception as exc:  # network, quota, bad JSON: fall back, never crash the app
        return ReviewResult("rules", rules_review(ctx, findings), error=f"{type(exc).__name__}: {exc}"[:300])

    if plant_mistake:
        raw = plant_wrong_number(raw)
    clean, log = verify(raw, ctx, findings, catalog_names)
    if not clean.issues and findings:
        fallback = rules_review(ctx, findings)
        return ReviewResult("rules", fallback, log=log, planted=plant_mistake,
                            error="Every AI issue failed verification; showing rule checks instead.")
    return ReviewResult("gemini", clean, log=log, planted=plant_mistake)


# ---------------------------------------------------------------------------
# Applying an action to the shortlist (pure: app.py does the session_state part)
# ---------------------------------------------------------------------------


def apply_action(shortlist: dict[str, dict], action: Action, summary_rows: dict[str, dict]) -> tuple[dict, list[str]]:
    """Return (new shortlist, widget keys to clear so the Builder shows new values)."""
    new = {k: dict(v) for k, v in shortlist.items()}
    keys = [k for k, v in new.items() if (v.get("item_name") or k) == action.product]
    clear: list[str] = []
    for k in keys:
        clear += [f"phase_{k}", f"slot_{k}", f"replacement_{k}"]

    if action.type == "move_phase":
        for k in keys:
            new[k]["holiday_phase"] = action.phase
    elif action.type == "remove":
        for k in keys:
            new.pop(k)
    elif action.type == "swap":
        old = new[keys[0]] if keys else {}
        for k in keys:
            new.pop(k)
        row = dict(summary_rows.get(action.add, {"item_name": action.add}))
        row["holiday_phase"] = action.phase or old.get("holiday_phase")
        row["placement_slot"] = action.slot or old.get("placement_slot")
        row["slot"] = row["placement_slot"]
        row["replacement_product"] = old.get("replacement_product")
        new[action.add] = row
        clear += [f"phase_{action.add}", f"slot_{action.add}", f"replacement_{action.add}"]
    return new, clear
