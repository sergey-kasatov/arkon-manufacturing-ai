"""Capture the deployed cockpit's screens as tracked PNGs for the README.

A README that describes an operational surface and shows none of it asks the
reader to take its word for the thing that is easiest to prove. These are the
pictures; `tools/make_result_plots.py` is the equivalent for the model figures,
and the two scripts have the same contract: a clone regenerates the images and
nothing is hand-edited.

**These are photographs of a running system, not mockups.** The script points at
the deployment, waits for real content to appear rather than for a fixed number
of seconds, and fails loudly if a page does not render, so a stale or broken page
cannot quietly produce a pretty picture. The store moves, so two runs give two
different numbers; that is the point.

Streamlit cannot be captured with `chrome --screenshot`: the page is drawn from a
websocket after load, so a headless one-shot writes an empty dark rectangle
(measured 2026-09-05, twice, at 20 and 45 second virtual-time budgets - virtual
time fast-forwards timers and does nothing for a real round trip). Playwright
waits for the DOM instead.

Usage, from the repository root, with the cockpit running:

    py tools/make_ui_screenshots.py
    py tools/make_ui_screenshots.py --base http://localhost:8501
"""

import argparse
import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parent.parent / "assets" / "ui"

# One row per picture: file name, path on the cockpit, the text that proves the
# page has actually rendered, and the viewport to shoot it at. The wait is on
# content rather than on a timer, because a timer that is long enough today is
# the thing that silently captures a spinner on a slower day.
SHOTS = [
    {
        "name": "executive_view.png",
        "path": "/executive",
        "ready": "Open incidents by age and priority",
        "size": (1600, 1180),
    },
    {
        "name": "steering_cell.png",
        "path": "/steering_cell",
        "ready": "Needs a person now",
        "size": (1600, 1250),
    },
    # No assistant.png here. This page before anyone has asked it anything is a picture
    # of an input box, so `tools/make_assistant_screenshot.py` takes it with a
    # conversation in it, and a row here would overwrite that with an empty chat.
    {
        "name": "cockpit_home.png",
        "path": "/",
        "ready": "Arkon Manufacturing AI",
        "size": (1600, 1100),
    },
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://192.168.178.100:8303",
                        help="the running cockpit")
    parser.add_argument("--only", help="capture just this file name")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is not installed in this interpreter: py -m pip install playwright "
                 "&& py -m playwright install chromium")

    OUT.mkdir(parents=True, exist_ok=True)
    shots = [s for s in SHOTS if not args.only or s["name"] == args.only]
    if not shots:
        sys.exit("no shot named %r" % args.only)

    failures = []
    with sync_playwright() as play:
        browser = play.chromium.launch()
        for shot in shots:
            # A device scale factor of 2 so the type is legible when GitHub scales
            # the image down to the README's column width.
            context = browser.new_context(
                viewport={"width": shot["size"][0], "height": shot["size"][1]},
                device_scale_factor=2,
                # The cockpit follows the viewer's theme; the pictures are pinned to
                # light so the README does not change with whoever regenerates it.
                color_scheme="light",
            )
            page = context.new_page()
            url = args.base.rstrip("/") + shot["path"]
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.get_by_text(shot["ready"], exact=False).first.wait_for(timeout=60000)
                # One extra beat for the last chart to lay out, after the proof text
                # is already on the page. This is a settle, not the wait itself.
                page.wait_for_timeout(1500)
                page.screenshot(path=str(OUT / shot["name"]))
                print("  %-22s %s" % (shot["name"], url))
            except Exception as err:
                failures.append("%s (%s): %s" % (shot["name"], url, str(err).splitlines()[0][:160]))
            finally:
                context.close()
        browser.close()

    print("wrote to %s" % OUT)
    if failures:
        sys.exit("these pages did not render, and no picture was written for them:\n  "
                 + "\n  ".join(failures))


if __name__ == "__main__":
    main()
