# Arkon Manufacturing AI - Project Instructions

Mastery-level portfolio project simulating an AI quality control platform
for a fictional heavy manufacturing company. Uses real public datasets only.

## Project Goals
Showcase BI, ML, Time Series, Computer Vision, and LLM in one coherent project.

## Architecture
- **Time Series**: NASA CMAPSS -> engine degradation / RUL prediction
- **ML**: APS Failure at Scania Trucks (UCI) -> failure classification
- **CV**: NEU Surface Defect / Casting Product -> visual defect detection
- **BI**: Tableau -> executive analytics dashboard
- **App**: Streamlit -> live dashboard + CV module + LLM chatbot (RAG)

## Constraints
- Real data only, no synthetic datasets
- All datasets presented under one fictional company "Arkon Manufacturing"
- Stack: Python, pandas, scikit-learn, XGBoost, Streamlit, VS Code, Mac + NAS

<!-- Sections below = standard working profile from the AI-Brain vault package -->
<!-- (070 Agents/System_Prompts/code-overlay_2026-07-06.md). Refresh them when the -->
<!-- package regenerates; the project sections above are owned by this repo. -->

## Context
Working with Sergey: junior data analyst (career change from 17 yrs automotive
engineering - BIW/closures, quality: 8D/SPC/PPAP), retraining at MSIT Masterschool
(AI Data Science track, Sep 2025 - Sep 2026). Stack: Python, pandas, SQL, VS Code.
Strong engineering background - explain at intuition level, don't hand-hold, but
don't assume deep data-engineering experience yet. Languages: Russian native,
English C1, German B2.

## Coding calibration (2026-07-05)
- Concept knowledge is solid junior level; the weak spot is unaided from-scratch
  writing: ~3 months of mainly AI-assisted coding (muscle-memory gap, not a
  knowledge gap), live SQL fading.
- Don't assume fluent blank-page coding (matters for interview prep and exercises).
- When Sergey explicitly asks to practice or train: coach - hints, review, small
  exercises - instead of handing him the finished solution. Otherwise work normally.

## Language - strict
- This is a code project. EVERYTHING written to a file is ENGLISH: code, comments,
  docstrings, markdown, README, commit messages.
- No Russian in the repository. Never use the em dash character (U+2014); use a comma, colon, period, or spaced hyphen ( - ) instead.
- Conversational replies in the chat panel may be Russian - but anything written to
  disk is English.

## Code conventions
- Self-contained code: all imports inside, runs as-is.
- Comments in code: English, minimal - only the non-obvious. Don't comment trivial
  lines (import, print).
- Structure code in logical blocks, each headed by a short English comment naming
  what it does (# Load data / # Clean / # Aggregate).
- One logical unit = one coherent block. Don't fragment.
- Match the existing project style; don't reformat unrelated code.

## Behavior
- Density first: minimal code that fully solves the task. No boilerplate for its
  own sake.
- When proposing changes: explain the "why" briefly, in English, in the file or
  PR/commit description.
- Don't invent APIs or library behavior. Unsure -> say so, suggest how to verify
  (docs, quick test).
- Critique directly: flaw + fix together.
- Don't add dependencies silently - flag any new package.

## Junior-safe
- I can't always spot a confident hallucination - when uncertain about an API,
  version, or behavior, flag it rather than asserting.
- Prefer standard, well-documented approaches over clever ones I'd struggle to
  maintain.
