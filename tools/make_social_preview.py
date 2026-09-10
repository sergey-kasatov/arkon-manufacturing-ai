"""Compose the GitHub social-preview card (1280x640) from the project's own screenshots.

A repository linked from LinkedIn or a Projects entry shows a grey placeholder tile
unless GitHub has a social preview, and the tile is the only thing most readers see
before deciding whether to click. This builds one from `assets/ui/`, so the card can
never show something the repository does not.

**It composes real screenshots rather than drawing a logo**, for the reason
`tools/make_ui_screenshots.py` exists at all: the pictures are the cheapest proof that
the thing runs. The layout says the one thing that distinguishes this platform, which
is that it carries TWO agents facing opposite ways - the executive view on the left as
the surface a manager reads, and on the right the plant's own assistant above the
customer's desk, labelled so a reader does not have to guess which is which.

**No measured numbers on the card except the test count.** Everything else this project
reports moves when it is re-measured (the store grows, the KPIs shift with every plant
tick), and a preview card is cached by every scraper that sees it, so a number on it
goes stale somewhere no one will ever look. The test count is a property of the
repository rather than of the running plant, so it can stand.

The palette is the customer desk page's own CSS, read off the deployed page rather than
invented: `#101330`, `#f2f4f8`, `#20b69e`.

**Upload is by hand: GitHub Settings -> General -> Social preview.** There is no API for
it and `gh repo edit` cannot do it, which is why this script writes a file rather than
setting anything.

Run:  py tools/make_social_preview.py [--out assets/social_preview.png]
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "assets" / "ui"

W, H = 1280, 640
STRIP_H = 150
PAD = 30

NAVY = (16, 19, 48)          # #101330, the desk page header
PANEL = (10, 12, 32)
LIGHT = (242, 244, 248)      # #f2f4f8, the desk page background
TEAL = (32, 182, 158)        # #20b69e, the desk page accent
DIM = (150, 158, 180)

# One row per panel: source file, the box it fills, a crop of the SOURCE as fractions,
# and the label drawn into its bottom edge.
#
# **The crops are the whole design.** A preview tile is read at about a third of this
# card's width in a feed, so anything that is small here is gone there. The first build
# fitted whole screenshots and the executive view came out as a grey smear of nine
# charts. Each panel is therefore cropped to the part of it that survives being shrunk:
# the KPI row with its four big numbers across the top, and below it the two agents
# cropped to their conversations, which carry the largest type in the project.
PANELS = [
    {"src": "executive_view.png", "box": (PAD, PAD, 1250, 190),
     "crop": (0.0, 0.06, 1.0, 0.245), "label": None},
    # The 0.200 is measured, not guessed: the Streamlit sidebar ends at x = 600 of 3000
    # on this capture, found by walking the middle row to the first run of near-white.
    {"src": "assistant.png", "box": (PAD, 206, 636, 460),
     "crop": (0.200, 0.03, 1.0, 0.42), "label": "THE PLANT'S OWN AGENT"},
    # The desk keeps its own navy header, which names it, so this crop starts at the top
    # left. Its conversation ends around 0.50; below that is the input box and the footer.
    # The 0.52 is arithmetic rather than taste: the crop is wider than the box, so cover
    # scaling is set by height and the visible source width is box_ratio * crop_height.
    # At 0.50 that came to 0.776 of the source and clipped the green bubbles, which end
    # at about 0.79; 0.52 buys the width back at the cost of some empty page below.
    {"src": "customer_desk.png", "box": (644, 206, 1250, 460),
     "crop": (0.0, 0.0, 0.85, 0.52), "label": "THE CUSTOMER'S AGENT"},
]

TITLE = "Arkon Manufacturing AI"
LINE_1 = "Seven ML models on public manufacturing datasets, one risk-event contract, two agents"
LINE_2 = ("n8n Steering Cell - Langflow - Qdrant - Streamlit - Tableau - deployed on a NAS "
          "- 203 offline tests in CI")


def font(size, bold=False):
    """A Windows face if there is one, otherwise whatever Pillow can give us."""
    from PIL import ImageFont
    names = ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for name in names:
        for folder in (pathlib.Path("C:/Windows/Fonts"), pathlib.Path("/Library/Fonts")):
            candidate = folder / name
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default(size)


def fit(image, width, height, crop):
    """Take the panel's region of the source, then cover the box from its top edge."""
    l, t, r, b = crop
    image = image.crop((round(l * image.width), round(t * image.height),
                        round(r * image.width), round(b * image.height)))
    scale = max(width / image.width, height / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)))
    # Anchor top-left rather than centre. After a crop the interesting thing sits at the
    # crop's own left edge, and a centred trim ate it: the assistant heading came out as
    # "n Quality Assistant" because the sidebar was cropped away and then the remainder
    # was trimmed from both sides.
    return resized.crop((0, 0, width, height))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "assets" / "social_preview.png"))
    args = parser.parse_args()

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("Pillow is not installed in this interpreter: py -m pip install Pillow")

    missing = [p["src"] for p in PANELS if not (UI / p["src"]).exists()]
    if missing:
        sys.exit("these screenshots do not exist, so the card would misrepresent the repository: "
                 + ", ".join(missing) + ". Run tools/make_ui_screenshots.py and "
                 "tools/make_desk_screenshot.py first.")

    card = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(card)

    label_font = font(15, bold=True)
    for panel in PANELS:
        x0, y0, x1, y1 = panel["box"]
        box_w, box_h = x1 - x0, y1 - y0
        draw.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=PANEL)
        source = Image.open(UI / panel["src"]).convert("RGB")
        card.paste(fit(source, box_w, box_h, panel["crop"]), (x0, y0))
        if panel["label"]:
            bar_h = 30
            bar = Image.new("RGB", (box_w, bar_h), NAVY)
            card.paste(bar, (x0, y1 - bar_h))
            draw.text((x0 + 12, y1 - bar_h + 7), panel["label"], font=label_font, fill=TEAL)

    # The strip carries the words. The rule above it is the only drawn element on the
    # card, and it is there so the screenshots read as one composition rather than three.
    draw.rectangle((0, H - STRIP_H, W, H), fill=NAVY)
    draw.rectangle((0, H - STRIP_H, W, H - STRIP_H + 3), fill=TEAL)

    draw.text((PAD, H - STRIP_H + 26), TITLE, font=font(42, bold=True), fill=LIGHT)
    draw.text((PAD, H - STRIP_H + 84), LINE_1, font=font(20), fill=LIGHT)
    draw.text((PAD, H - STRIP_H + 114), LINE_2, font=font(17), fill=DIM)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    card.save(out)
    print("  %s  %dx%d" % (out.relative_to(ROOT), card.width, card.height))
    print("Upload it by hand: GitHub Settings -> General -> Social preview. There is no API.")


if __name__ == "__main__":
    main()
