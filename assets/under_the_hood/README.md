# Under the hood: four pictures no script regenerates

Every picture in `assets/ui/` is taken by a script from the running deployment
(`tools/make_ui_screenshots.py`, `make_desk_screenshot.py`, `make_assistant_screenshot.py`),
so a clone can retake it. The four here cannot be retaken that way, so each one says what
it is instead: two were captured by hand, one by an agent off the n8n editor, and one is
a render of the repository's own flow JSON rather than a photograph of the deployed
canvas. All four were taken for presentations on 2026-09-07 and 2026-09-09 and
copied here byte for byte on 2026-09-11 (SHA-256 compared).

| File | What it shows | When and how it was taken | Checked against the repository on 2026-09-11 |
|---|---|---|---|
| `telegram_card.png` (483 x 238) | The P1 card the Steering Cell sent for ARK-INC-00308, a Scania truck flagged for its air pressure system, with the assignee, the action, the event id and the link that opens the incident in the cockpit | The card was sent at 13:44 plant time on 2026-09-07 (the incident's `created_at` is 11:44:07 UTC); Sergey took the screenshot by hand from the Telegram client that afternoon | The card is sent by the Telegram Alert node of `n8n/quality_steering_cell_v1.json`, which has had no commit since 2026-09-07 10:02, before the card was sent |
| `n8n_quality_steering_cell.png` (2102 x 678) | The Quality Steering Cell intake workflow in the deployed n8n editor, 16 nodes | By hand, by Sergey, on 2026-09-07 at about 16:00: the editor's dark theme, zoom to fit | 16 nodes, as `n8n/quality_steering_cell_v1.json` holds; no commit to that file since 2026-09-07 10:02 |
| `n8n_customer_desk.png` (1284 x 888) | The Customer Quality Desk workflow `arkonCustDesk02` in the deployed n8n editor, 12 nodes | By an agent off the deployed editor on 2026-09-09 at 09:47, with the light theme set in the page for the capture only (nothing in the account changed), cropped to the nodes | Node names, positions and connections identical to `n8n/customer_desk_v1.json`; the one later commit to that file, `8115b7c`, changed the prompt |
| `langflow_assistant_canvas.png` (700 x 1087) | The Arkon Quality Assistant canvas, 19 nodes, with one coloured note behind each of the six routes | **A render, not a photograph of the deployed canvas.** `langflow/build/build_deck_canvases.py --deploy` built a temporary copy, `ZZ_Deck_Canvas_Coloured`, from the repository JSON at the deployed positions and added the notes; an agent captured it in the Langflow UI on 2026-09-07 at 16:52 and cut the frame to its content (columns 790 to 1490 of a 2278 x 1087 capture). The copy was deleted at 16:57, and the deployed canvas was never edited | Node ids, names, positions and all 18 edges identical to `langflow/arkon_quality_assistant.json`; the two later commits to that file, `930d385` and `64ed4d9`, changed prompts only |

The notes on the canvas render are not on the deployed canvas: Langflow has no per-route
colour, and a fit-to-view capture of the real 19-node canvas is unreadable, which is why
the render exists. Do not use a capture of the shift-briefing sub-flow from the same
session: it shows 17 nodes, and the repository sub-flow has had 18 since commit `e7a3d7f`.
