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

## Language - strict
- Everything written to a file is ENGLISH: code, comments, docstrings, markdown,
  README, commit messages.
- Never use the em dash character (U+2014); use a comma, colon, period, or a
  spaced hyphen ( - ) instead. The same goes for curly quotes and the ellipsis
  character: plain ASCII only.

## Code conventions
- Self-contained code: all imports inside, runs as-is.
- Comments in code: English, minimal - only the non-obvious. Don't comment trivial
  lines (import, print).
- Structure code in logical blocks, each headed by a short English comment naming
  what it does (# Load data / # Clean / # Aggregate).
- One logical unit = one coherent block. Don't fragment.
- Match the existing project style; don't reformat unrelated code.
- No absolute local paths in tracked files. Derive the repository root from
  `__file__`, or read the location from an environment variable and fail with a
  message naming it.

## Behavior
- Density first: minimal code that fully solves the task. No boilerplate for its
  own sake.
- When proposing changes: explain the "why" briefly, in English, in the file or
  the commit description.
- Don't invent APIs or library behavior. Unsure -> say so, suggest how to verify
  (docs, quick test). Flag uncertainty about an API, a version or a behaviour
  rather than asserting it.
- Critique directly: flaw + fix together.
- Don't add dependencies silently - flag any new package.
- Prefer standard, well-documented approaches over clever ones that are harder to
  maintain.
