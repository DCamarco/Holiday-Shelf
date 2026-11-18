# Person C: AI Shortlist Reviewer + Shipping — Build Plan

_Written Nov 16, 2026, after pulling main at `4701285`. Steps 1–3 built Nov 17 on branch `part-c-ai`, rebased onto main `eb40485` (pages moved to `views/`; the panel is called from `views/shortlist_builder.py`)._

## 1. Where the team is versus the plan doc

| Plan item | Owner | Status on `main` |
|---|---|---|
| B1 Data fix (join on product name) | B | ✅ Done. `pipeline.py` joins on `item_name`; `names.py` merges duplicate spellings |
| B2 Scorecard + Opportunity Finder updates | B | ✅ Rebuilt on fixed data, with "Add to shortlist" buttons |
| B3 Bundles & Cart Rescue | B | ✅ `bundle_pairs.csv` (643 pairs), `cart_rescue.csv`, page built |
| B4 Banner Performance | B | ✅ Page built from `banner_performance.csv` |
| A1 Shortlist Builder | A | ✅ Phase, slot, replacement, test plan, category/price mix, CSV + PDF export |
| A2 Season Playbook + Trends | A | ✅ Recommended phase, Google Trends, "apply phase to shortlist" |
| Extra | B | ✅ Overview page, light/dark theme (`ui.py`) |
| **C1 AI Shortlist Reviewer** | **C (me)** | ❌ No AI code anywhere |
| **C2 Deploy, README, demo** | **C (me)** | ❌ Not deployed; README still describes the old, fixed bug |

All 69 tests pass. The app has every page except the AI piece.

## 2. What I'm building

**Product:** a button in the Shortlist Builder, "Review my plan", that reads the merchandiser's current plan and gives advice like a colleague would. Every suggestion can be applied with one click, and every number the AI writes is checked against the data before it's shown.

**Why this design (rubric: AI Integration):**
- It works *with* the app's data and changes the app's state, so it isn't a chatbot on the side.
- Rules find the facts and Gemini judges and explains them. This keeps the AI grounded and makes it hard for it to invent numbers.
- Number checking plus a planted-mistake demo answers the client's request: "show me the verification catching a failure."

**Provider:** Gemini on Google's **Agent Platform API** (Vertex AI express mode, `genai.Client(enterprise=True, api_key=...)`, google-genai ≥ 3.5) via the `google-genai` SDK, with a structured JSON response schema. Model: `gemini-3.8-flash` (newest GA Flash; sampling parameters are ignored, so effort is set with `thinking_level=LOW`). Key, model and backend live in `st.secrets` (`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_VERTEXAI`). Calls time out after 45 s and fall back to rule checks.

## 3. Architecture

Modules are kept separate from the UI. `app.py` only calls functions.

```
ai_context.py   facts the AI is allowed to see (pure pandas, no AI)
ai_rules.py     deterministic plan checks → findings with exact numbers
ai_review.py    Gemini call + response schema + verification + fallback
tag_products.py one-time offline script → data/product_tags.csv
tests/test_ai_*.py
```

### 3.1 `ai_context.py`: what the AI sees
`build_context(shortlist, summary, weekly, pairs, rescue, tags) -> dict`
- **For each pick:** name, category, typical price, phase, slot, product it replaces, views, purchases, view→buy rate, CI low/high, label, weak-data flag, Season Playbook's recommended phase, best add-on (from `bundle_pairs`), cart-abandonment rate if listed.
- **For the plan as a whole:** count, category mix %, price-band mix %, picks per phase, weak-data count, empty phases.
- **Swap pool:** the top ~20 products *not* in the plan, ranked by CI low, with the same fields. The AI may only suggest products from this pool.
- Rounding happens here, so the AI and the verifier see identical numbers.

### 3.2 `ai_rules.py`: deterministic checks (work without an API key)
Each check returns `{id, severity, products, numbers}`:
1. One category over 40% of picks.
2. Holiday phases with no picks (one combined card).
3. Pick's phase ≠ Season Playbook's recommended phase.
4. Pick rests on weak data: label "Not Enough Data", too few views, unmatched purchases, or a 95% range wider than the rate itself. (Changed from "CI width over 20 points", which never fires at 1–20% rates.)
5. Pick replaces a product with a *higher* CI low (a downgrade).
6. No pick over $50 in Black Friday week (no anchor product), or no pick under $20 in Mid-Dec (no stocking stuffer).
7. Cart add-on with no bundle evidence behind it.
8. Plan size outside 10–15.

### 3.3 `ai_review.py`: Gemini plus verification
- **Prompt:** the context JSON and the rule findings. Instructions: rank the issues, explain each in plain merchandiser language, propose up to 3 swaps from the pool and phase moves; describe, don't predict; no causal claims.
- **Response schema (pydantic):**
  ```
  Review { headline: str,
           issues: [{severity, title, explanation, products: [str]}],
           actions: [{type: "swap"|"move_phase"|"remove", product: str,
                      add: str|None, phase: str|None, slot: str|None, reason: str}] }
  ```
- **`verify(review, context)`:**
  - Every product name must be in the plan or the swap pool. If not, drop that item.
  - Every number in the text (regex: %, $, counts) must match a value in the context after rounding. If not, drop the sentence and flag it.
  - Block banned phrases ("will sell", "guaranteed", "causes", "will increase").
  - Return the review plus a log of `{kept, dropped, reason}`.
- **Fallback:** no key, an API error, or everything dropped → show the rule findings as plain cards. The app never breaks.
- **Caching:** results cached by a hash of the plan, so reruns don't call the API again.

### 3.4 UI in the Shortlist Builder (small edit in `app.py`)
- "🤖 Review my plan" button below "Plan overview".
- Headline, then issue cards coloured by severity, each with a "✓ numbers verified" badge.
- Action cards with an **Apply** button that edits `st.session_state.shortlist` (remove/add with phase and slot, clear widget keys like the Season Playbook does), then `st.rerun()`.
- "What the AI saw" expander showing the context JSON, for transparency.
- "Verification log" expander showing what was dropped and why.
- **Demo switch** (hidden unless `?demo=1`): "Plant a wrong number". It changes one number in the AI's answer before verification, so the audience sees it get caught.

### 3.5 `tag_products.py`: AI product tags (second AI use, offline)
- Batch about 425 product names through Gemini → `gift_persona`, `season` (winter / any), `stocking_stuffer` (y/n), `pandemic_related` (y/n), `theme`.
- Save `data/product_tags.csv`; hand-check 30 rows into `data/product_tags_review.csv` and report agreement in the README.
- Used by the reviewer's context ("7 of 12 picks are self-use drinkware") and as optional filters.

### 3.6 Scope expansion (added Nov 17): "Explain this product"
_Not in the original team plan. Agreed as an add-on after the core reviewer; build it only after steps 1–3 work._
- A button on Shelf Scorecard / Opportunity Finder rows that gives a 2–3 sentence explanation of one product's numbers, e.g. *"High views, low conversion, most carts abandoned before checkout. Reads as a Window-Shopper; a bundle may help."*
- Uses the same pieces as the reviewer: a single-product slice of `ai_context`, the same Gemini call with a smaller schema (`{summary, label_reason, suggestion}`), and the same `verify()` (numbers and names checked, causal claims blocked). Falls back to a rule-written sentence with no key.
- Purpose: explainability of the data for the merchandiser. It supports the reviewer and doesn't replace it as the main AI feature.
- Cost: about half a day once `ai_review.py` exists. Slot it between steps 3 and 4 below if time allows.

### 3.7 Stretch goals (only if time allows)
- An AI-written, verified executive summary at the top of the PDF brief (`build_shelf_brief_pdf`).
- Bundle names and banner copy for chosen cart add-ons.

## 4. Tests (no network)
- `test_ai_rules.py`: each rule fires on a hand-built plan and stays silent on a clean one.
- `test_ai_verify.py`: a wrong number is dropped, an unknown product is dropped, causal phrases are blocked, a clean answer passes untouched.
- `test_ai_review.py`: a fake Gemini client returns canned JSON; fallback works with no key and on errors; Apply actions change the shortlist correctly.

## 5. Shipping tasks (C2)
- `requirements.txt`: add `google-genai`, `pydantic`.
- `.streamlit/secrets.toml` (git-ignored) with `GEMINI_API_KEY` and `GEMINI_MODEL`; the same keys go in the Streamlit Cloud secrets UI.
- Remove the tracked `__pycache__/names.cpython-313.pyc` (`.gitignore` already covers it).
- Check that the app doesn't load the 42 MB `raw_events_v2.csv` at runtime (only the pipeline should).
- Deploy to Streamlit Community Cloud from `main`; confirm a cold start works.
- Rewrite the README: live link, one-command setup, the item-name fix replacing the outdated "view_item undercounts" limitation, the AI section and its verification, and data sources. Merge or retire `REPORT.MD`.
- Demo deck and script (see the team plan doc, section 5), including the 3 existing analyses we go beyond.

## 6. Order of work

| Step | Deliverable | Done when |
|---|---|---|
| 1 ✅ | `ai_context.py` + `ai_rules.py` + `ai_panel.py` + tests | Rule cards show in the Builder with no API key (done Nov 17, 17 new tests) |
| 2 ✅ | `ai_review.py` (Gemini + schema + verify) + tests | Review works on a real 12-product plan; a planted mistake is caught |
| 3 ✅ | UI: Apply buttons, transparency expanders, demo switch | A swap applied from the review updates the plan |
| 3b | _Scope expansion:_ "Explain this product" (§3.6) | Verified explanation shows on a Scorecard row |
| 4 | `tag_products.py` + spot-check | Tags CSV committed; reviewer uses tags |
| 5 | Requirements, secrets, deploy | Live URL works for a teammate. Community Cloud has no deploy CLI (streamlit/streamlit#17619 still open), so deploy from share.streamlit.io and paste the three `GEMINI_*` secrets there. Push `part-c-ai` first. |
| 6 | README + demo script | Teammates sign off |

Work on a branch, `part-c-ai`, with a PR to `main` after each of steps 1–3 so A and B can see it early.

## 7. Next up (Nov 18): UI polish and usability

Raised Nov 17 after trying the app; not started.
- **Plan review looks like text, not UI.** Add stat tiles (picks per phase, top category share vs the 40% limit, weak-data count, price mix) and small Altair charts; keep the words as short notes on each card.
- **Shortlist Builder: picking one product at a time is too slow.** Add bulk actions (e.g. "add top Stars per phase", add a whole Hidden Gem group), then edit.
- **Bundles and Cart Rescue pages need polish.** Review layout, labels and how the numbers are shown.
- Deploy (step 5) and add the live URL to the README.

## 8. Open items for the team
- Get a Gemini API key (from the existing "Gemini API" Google Cloud project) and share it only through Streamlit secrets, never in git.
- Agree with A not to rename the shortlist row fields (`holiday_phase`, `placement_slot`, `replacement_product`), because the AI reads them.
- Set the demo date so the timeline can be fixed.
