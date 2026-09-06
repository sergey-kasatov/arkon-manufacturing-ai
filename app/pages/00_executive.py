"""The executive view, live.

The Tableau workbook is the published snapshot of this same design; this is the
surface that is live without a publish step, because Tableau Public has no API and
its only scheduled refresh is Google Sheets. Both are built from one specification,
`tableau/Dashboard_Design_v3.md`, so two executive views of one plant cannot make two
different claims about it.

Three things about this page are deliberate.

**It computes no status.** Every incident's state is the transition log folded onto
its record, and the n8n status API performs that fold for every consumer. This page
arranges what the API returns and nothing else, which is why it cannot disagree with
the cockpit, the assistant or the workbook.

**It renders its own colours rather than Streamlit's theme.** The rest of the cockpit
follows the viewer's light or dark setting, which is right for a tool and wrong for a
surface someone puts on a screen in front of other people: a dashboard that looks
different every time it is shown is a dashboard nobody trusts twice. The board below
carries the palette of section 9 of the specification explicitly, so it renders the
same in both.

**It has no filters.** An executive page is a statement. The filterable list is one
click away on the Steering Cell page, and putting it here would invite a viewer to
change the numbers under the sentence at the top.
"""

import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from utils import api, config

st.set_page_config(
    page_title="Executive view | Arkon",
    layout="wide",
    initial_sidebar_state="collapsed",
)

REFRESH_SECONDS = 60

# The plant's clock. Every timestamp the status API returns is UTC, and this page used
# to print it as it came: a board on a wall in Cologne read 08:44 while the room read
# 10:44, which is the kind of wrongness nobody reports and everybody quietly distrusts.
# The zone is named rather than taken from the container's TZ, so the board does not
# change meaning if that environment variable is ever unset. The image already carries
# tzdata, so this adds no dependency.
PLANT_TZ = ZoneInfo("Europe/Berlin")


def local(stamp, fmt="%d %b %H:%M"):
    """Render an API timestamp on the plant clock, or hand it back untouched."""
    if not stamp:
        return ""
    try:
        moment = datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return str(stamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=datetime.timezone.utc)
    return moment.astimezone(PLANT_TZ).strftime(fmt)


# The bullet chart's fixed axis, in multiples of an incident's own window. Four
# puts the window tick at a quarter of the track, which is where it can be seen.
BULLET_CAP = 4.0

# Section 9 of the specification. Named here rather than repeated inline, because a
# colour that appears twice with two values is how a palette stops being one.
CANVAS = "#F2F2EF"
CARD = "#FFFFFF"
INK = "#16161A"
CONTEXT = "#55555E"
RULE = "#D8D8D2"
BREACH = "#C0392B"
# Three intensities of one hue, which is Few's rule for an ordered category, and
# priority is ordered. Never three unrelated colours.
PRIORITY_INK = {"P1": "#1F3A63", "P2": "#3D6394", "P3": "#8AA6C8", "P4": "#B9C6D8"}

# The status API's own definition of open, and it is used here rather than a more
# intuitive one on purpose. `resolved` is NOT counted: the store's `open_incidents`
# is new + acknowledged + in_containment, verified against a live summary reading
# 31 + 3 + 1 = 35. A resolved incident is still waiting for the Quality Manager to
# close it, so counting it as open would be defensible - and it would make this page
# disagree with the cockpit, the assistant and the workbook, which is worse than
# being slightly conservative. The resolved count is surfaced in the OPEN card's
# context line instead, so nothing is hidden.
OPEN_STATES = ["new", "acknowledged", "in_containment"]
ALL_STATES = config.LIFECYCLE

# Section 6. Bands open at the hour scale because this Steering Cell measures P1 in
# fifteen minutes; the ITSM convention of five-day buckets would collapse the whole
# live stream into one bar. An empty band between two full ones stays on the axis.
AGE_BANDS = [
    ("under 1 h", 0, 60),
    ("1 to 4 h", 60, 240),
    ("4 to 24 h", 240, 1440),
    ("1 to 3 d", 1440, 4320),
    ("over 3 d", 4320, float("inf")),
]

CSS = """
<style>
  /* Streamlit pads its own block container by several rem top and bottom. On a
     tool that is right; on a board meant to be read in one glance it measured as
     240 px of empty screen at 1920x950, so it goes. */
  .stMain .block-container { padding-top: 1.2rem; padding-bottom: 0.6rem; }
  header[data-testid="stHeader"] { height: 0; min-height: 0; }
  .arkon-board {
    background: %(canvas)s;
    padding: 16px 20px 12px 20px;
    border-radius: 6px;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    color: %(ink)s;
  }
  .arkon-board * { box-sizing: border-box; }
  .ark-title { font-size: 22px; font-weight: 600; letter-spacing: -0.2px; margin: 0; }
  .ark-eyebrow { float: right; font-size: 11px; color: %(context)s; padding-top: 8px; }
  .ark-status { font-size: 13px; color: %(ink)s; margin: 6px 0 0 0; max-width: 1200px; }
  .ark-cards { display: flex; gap: 12px; margin: 12px 0 0 0; }
  .ark-card {
    flex: 1 1 0; background: %(card)s; border-left: 6px solid %(rule)s;
    padding: 9px 14px 8px 12px; text-align: left;
  }
  .ark-card.breach { border-left-color: %(breach)s; }
  .ark-label {
    font-size: 10px; font-weight: 700; letter-spacing: 0.09em;
    text-transform: uppercase; color: %(context)s; margin: 0;
  }
  /* One font size for all four numbers, so they share a baseline whatever their
     digit count, and left-aligned so the row has a vertical line in it. */
  .ark-ban { font-size: 34px; font-weight: 700; line-height: 1.08; margin: 2px 0 1px 0; }
  .ark-ban.breach { color: %(breach)s; }
  .ark-ctx { font-size: 11px; color: %(context)s; margin: 0; }
  .ark-panels { display: flex; gap: 12px; margin-top: 12px; align-items: stretch; }
  .ark-panel { background: %(card)s; padding: 10px 14px 8px 14px; }
  .ark-panel h3 { font-size: 12.5px; font-weight: 600; margin: 0 0 1px 0; color: %(ink)s; }
  .ark-panel p.sub { font-size: 10.5px; color: %(context)s; margin: 0 0 7px 0; line-height: 1.35; }
  table.ark-rows { width: 100%%; border-collapse: collapse; }
  table.ark-rows td { padding: 1px 0; vertical-align: middle; border: 0; }
  td.ark-rowlabel {
    font-size: 11px; color: %(context)s; white-space: nowrap;
    padding-right: 10px; width: 1%%;
  }
  td.ark-rowvalue {
    font-size: 12px; font-weight: 700; color: %(ink)s; text-align: right;
    padding-left: 10px; width: 1%%; white-space: nowrap; font-variant-numeric: tabular-nums;
  }
  .ark-track { position: relative; height: 13px; width: 100%%; }
  .ark-seg { height: 13px; display: inline-block; vertical-align: top; }
  /* Few's comparative measure: a perpendicular tick, never a second bar. */
  .ark-tick { position: absolute; top: -2px; height: 17px; width: 2px; background: %(ink)s; }
  .ark-feed td { font-size: 11px; color: %(ink)s; padding: 1px 0; }
  .ark-feed td.t { color: %(context)s; white-space: nowrap; padding-right: 12px; }
  .ark-feed td.a { font-weight: 600; white-space: nowrap; padding-right: 12px; }
  .ark-feed td.m { color: %(context)s; }
  .ark-legend { font-size: 11px; color: %(context)s; margin-top: 6px; }
  .ark-swatch {
    display: inline-block; width: 9px; height: 9px; margin: 0 5px 0 12px;
  }
  .ark-foot {
    font-size: 10.5px; color: %(context)s; margin-top: 10px; line-height: 1.4;
    border-top: 1px solid %(rule)s; padding-top: 7px;
  }

  /* Narrow screens. "One screen, no scrolling" and "works on a phone" are not the
     same requirement and cannot both be met: seven charts and four KPIs do not fit
     812 px of phone at a legible size, so below they are traded away rather than
     shrunk. Three columns squeezed side by side would be wrong under either policy.

     Under 1100 px the columns stack and the page scrolls, which is the honest
     behaviour for a laptop in portrait or a tablet. Under 640 px the board keeps
     what answers the question in five seconds - the sentence, the four numbers and
     where the backlog is - and drops the rest, which is the same reduction the
     Tableau phone layout makes (Dashboard_Design_v3.md section 11). */
  /* Short screens, by height rather than width: a 1440x780 laptop was 85 px over
     while a 1920x950 desktop fitted with room to spare. Trimming content for
     everyone to satisfy the smallest screen is the wrong trade, so the board
     tightens itself instead and nothing is removed. */
  @media (max-height: 820px) {
    /* Streamlit's own container keeps a little padding even after the rule above;
       on a 768 px laptop that is the last twenty pixels between fitting and not. */
    .stMain .block-container { padding-top: 0.35rem; padding-bottom: 0.15rem; }
    .arkon-board { padding: 4px 16px 4px 16px; }
    .ark-title { font-size: 18px; }
    .ark-eyebrow { padding-top: 5px; }
    .ark-status { font-size: 11.5px; margin-top: 3px; }
    .ark-cards { margin-top: 6px; gap: 10px; }
    .ark-card { padding: 6px 12px 6px 10px; }
    .ark-ban { font-size: 27px; margin: 1px 0 0 0; }
    .ark-panels { margin-top: 6px; gap: 10px; }
    .ark-panel { padding: 8px 12px 6px 12px; }
    .ark-panel p.sub { margin-bottom: 2px; line-height: 1.28; }
    .ark-panel h3 { font-size: 12px; }
    /* The rows are where the height actually is: about thirty of them across the
       three columns, so two pixels each is sixty pixels of screen. */
    table.ark-rows td { padding: 0; }
    .ark-track { height: 11px; }
    .ark-seg { height: 11px; }
    .ark-tick { height: 15px; }
    .ark-legend { margin-top: 2px; }
    .ark-foot { margin-top: 6px; padding-top: 4px; }
  }
  @media (max-width: 1100px) {
    .ark-panels { flex-direction: column; }
    .ark-panel { flex: 1 1 auto !important; }
    .ark-cards { flex-wrap: wrap; }
    .ark-card { flex: 1 1 40%%; }
  }
  @media (max-width: 640px) {
    .arkon-board { padding: 12px 12px 10px 12px; }
    .ark-eyebrow { float: none; display: block; padding-top: 0; margin-bottom: 4px; }
    .ark-cards { flex-direction: column; gap: 8px; }
    .ark-ban { font-size: 30px; }
    .ark-narrow-drop { display: none; }
    td.ark-rowlabel { font-size: 10px; }
  }
</style>
""" % {"canvas": CANVAS, "card": CARD, "ink": INK, "context": CONTEXT,
       "rule": RULE, "breach": BREACH}


def sweep():
    """Every incident, one lifecycle state at a time.

    The status API caps `limit` at 50 and has no pagination, so a single call
    cannot see a store this size. Asking per state raises the ceiling to 50 per
    state without needing pagination, because charter 7.2 puts every incident in
    exactly one state. Same method as `tableau/build_extracts.py`; if the two ever
    disagree, one of them changed this loop.
    """
    incidents, truncated, summary = [], [], None
    for state in ALL_STATES:
        answer = api.incidents(status=state, limit=50)
        if not api.reachable(answer):
            return None, None, answer
        summary = summary or answer
        incidents.extend(answer.get("incidents", []))
        if (answer.get("match_count") or 0) > (answer.get("returned") or 0):
            truncated.append(state)
    return incidents, truncated, summary


def band_of(minutes):
    for name, low, high in AGE_BANDS:
        if low <= minutes < high:
            return name
    return AGE_BANDS[-1][0]


def status_sentence(incidents):
    """Section 5: one generated sentence, stating a relationship rather than a number.

    Two clauses, the oldest band and the freshest, and it collapses to one when they
    would say the same thing. A fifth KPI card could not do this: a card holds a
    number, and what an executive wants first is what two numbers mean together.
    """
    openi = [i for i in incidents if i.get("status") in OPEN_STATES]
    if not openi:
        return "Nothing is open. Every incident in the store has been closed or dismissed."

    by_band = {}
    for i in openi:
        by_band.setdefault(band_of(i.get("age_minutes") or 0), []).append(i)

    oldest = next((n for n, _, _ in reversed(AGE_BANDS) if by_band.get(n)), None)
    newest = next((n for n, _, _ in AGE_BANDS if by_band.get(n)), None)
    old_group = by_band.get(oldest, [])
    never = [i for i in old_group if not i["lifecycle"].get("acknowledged_at")]

    first = "%d of %d open incidents have been open %s%s." % (
        len(old_group), len(openi),
        "more than three days" if oldest == "over 3 d" else "for " + oldest,
        ", none of them ever acknowledged" if len(never) == len(old_group) and never else "",
    )
    if newest == oldest:
        return first

    fresh = by_band[newest]
    late = [i for i in fresh if i.get("overdue")]
    second = " The %d raised %s %s." % (
        len(fresh), "in the last hour" if newest == "under 1 h" else "in the last " + newest,
        "are being worked inside window" if not late
        else "include %d already past window" % len(late),
    )
    return first + second


def hbars(rows, widest=None):
    """One horizontal bar per row: label, coloured segments, tick, value.

    Hand-drawn rather than charted, because the specification asks for exact type
    sizes, an explicit palette and a number column that lines up, and a chart
    component that owns its own styling cannot give all three.

    `widest` fixes the axis instead of taking it from the data, which is what makes
    the bullet chart legible: see the comment where it is called.
    """
    widest = widest or max((r["value"] for r in rows), default=0) or 1
    out = ['<table class="ark-rows">']
    for row in rows:
        segments = ""
        for width, colour in row["segments"]:
            pct = 100.0 * min(width, widest) / widest
            if pct > 0:
                segments += '<span class="ark-seg" style="width:%.3f%%;background:%s"></span>' % (
                    pct, colour)
        if row.get("overflow"):
            # The bar ran off the fixed axis. Say so on the bar rather than letting
            # it look like a bar that merely reaches the end.
            segments += ('<span style="font-size:11px;font-weight:700;color:%s;'
                         'padding-left:3px;line-height:15px">&#9656;</span>' % BREACH)
        tick = ""
        if row.get("tick") is not None:
            tick = '<span class="ark-tick" style="left:%.3f%%"></span>' % (
                min(100.0, 100.0 * row["tick"] / widest))
        out.append(
            '<tr><td class="ark-rowlabel">%s</td>'
            '<td><div class="ark-track">%s%s</div></td>'
            '<td class="ark-rowvalue">%s</td></tr>'
            % (row["label"], segments, tick, row["display"])
        )
    out.append("</table>")
    return "".join(out)


def board():
    incidents, truncated, summary = sweep()
    if incidents is None:
        st.error(
            "The Steering Cell did not answer, so nothing on this page can be read as the "
            "state of the plant. " + str(summary.get("message", ""))
        )
        st.caption("Endpoint: " + config.STATUS_API)
        return

    store = summary["store"]
    times = summary.get("response_times", {})
    as_of = summary.get("as_of", "")
    openi = [i for i in incidents if i.get("status") in OPEN_STATES]

    # --- KPI row. Counted off the same sweep the charts are drawn from, rather than
    # off the store summary, and the reason is a defect this page had on its first
    # render: the summary comes from one call and the sweep from six, so the plant
    # raised an incident between them and the sentence said 37 open while the card
    # said 36. Two numbers for one thing on one screen is the worst failure an
    # executive view can have, and it is a failure of construction rather than of
    # arithmetic. Counting the API's own per-incident answers is not a fold; the
    # status of each incident is still computed by the API and never here. The two
    # medians are the only figures the API alone can produce, and they are labelled
    # as such on the cards.
    overdue = sum(1 for i in incidents if i.get("overdue"))
    open_count = len(openi)
    resolved = sum(1 for i in incidents if i.get("status") == "resolved")
    closed = sum(1 for i in incidents if i.get("status") in ("closed", "false_positive"))
    share = (100.0 * overdue / open_count) if open_count else 0.0
    mtta = times.get("median_minutes_to_acknowledge")
    mttr = times.get("median_minutes_to_close")
    open_context = "%d raised, %d closed or dismissed" % (len(incidents), closed)
    if resolved:
        open_context += ", %d resolved awaiting closure" % resolved
    cards = [
        ("Overdue", "{:,}".format(overdue),
         "of %d open, %.0f percent" % (open_count, share), True),
        ("Open", "{:,}".format(open_count), open_context, False),
        ("Time to acknowledge", "-" if mtta is None else "%.1f min" % mtta,
         "median, window 15 min P1 / 60 min P2", False),
        ("Time to close", "-" if mttr is None else "%.1f min" % mttr,
         "median over %d closed" % times.get("closed_incidents", 0), False),
    ]
    card_html = "".join(
        '<div class="ark-card%s"><p class="ark-label">%s</p>'
        '<p class="ark-ban%s">%s</p><p class="ark-ctx">%s</p></div>'
        % (" breach" if red else "", label, " breach" if red else "", value, ctx)
        for label, value, ctx, red in cards
    )

    # --- Aging profile, the dominant view. A snapshot and never a trend: see
    # section 6 of the specification, and the comment in build_extracts.py.
    aging_rows = []
    for name, _, _ in AGE_BANDS:
        members = [i for i in openi if band_of(i.get("age_minutes") or 0) == name]
        if not members and name not in ("4 to 24 h",):
            if not any(band_of(i.get("age_minutes") or 0) == name for i in openi):
                # An empty band between two full ones is information; an empty band
                # at the end of the axis is not. Keep interior gaps, drop the tails.
                idx = [n for n, _, _ in AGE_BANDS].index(name)
                before = any(band_of(i.get("age_minutes") or 0) in
                             [n for n, _, _ in AGE_BANDS][:idx] for i in openi)
                after = any(band_of(i.get("age_minutes") or 0) in
                            [n for n, _, _ in AGE_BANDS][idx + 1:] for i in openi)
                if not (before and after):
                    continue
        # Breach first, as its own red segment, then the rest by priority. Two
        # earlier versions of this line hid the thing the chart exists to show. The
        # first coloured a band red only when EVERY incident in it was past its
        # window, and P3 carries no window at all, so a band of 12 blown P2 beside 8
        # P3 came out entirely navy. The second coloured per priority on the same
        # all-or-nothing test, and the "over 3 d" band went navy again because a few
        # of its P2 had been acknowledged late rather than not at all. Counting the
        # overdue into one red segment cannot be defeated by a mixture: the red is
        # exactly as long as the number in the row label.
        overdue_here = sum(1 for i in members if i.get("overdue"))
        segments = [(overdue_here, BREACH)] if overdue_here else []
        for priority in ("P1", "P2", "P3", "P4"):
            rest = sum(1 for i in members
                       if i.get("priority") == priority and not i.get("overdue"))
            if rest:
                segments.append((rest, PRIORITY_INK[priority]))
        aging_rows.append({
            # Section 3: one combined row label, not two nested header columns.
            "label": name + (" / %d overdue" % overdue_here if overdue_here else ""),
            "segments": segments,
            "value": len(members),
            "display": str(len(members)),
        })

    # --- Time to acknowledge as bullet bars. Few: the featured measure is the bar,
    # the allowed window is a tick, and the two qualitative ranges are inside and
    # past. P3 and P4 have no window, so they have no row; a zero would be a lie.
    acked = [
        i for i in incidents
        if i["lifecycle"].get("minutes_to_acknowledge") is not None
        and i.get("acknowledge_due_minutes")
    ]
    acked.sort(key=lambda i: i["lifecycle"]["minutes_to_acknowledge"], reverse=True)
    bullet_rows = []
    for i in acked[:6]:
        minutes = i["lifecycle"]["minutes_to_acknowledge"]
        window = i["acknowledge_due_minutes"]
        late = minutes > window
        # The bar is the RATIO to that incident's own window, not the raw minutes,
        # and the axis is fixed at BULLET_CAP rather than taken from the data. Drawn
        # in minutes it does not work: this store holds acknowledgements from 0.0 to
        # 9,055 minutes against windows of 15 and 60, so a 600-fold range puts every
        # tick within a pixel of the left edge and the comparison Few designed the
        # bullet graph to make disappears. On the ratio scale the tick is always at
        # 1.0, which is a quarter of the way along. A bar past the cap keeps its real
        # figure in the number column and is marked as running off the axis, so the
        # cap loses resolution and never loses the fact.
        ratio = minutes / window if window else 0.0
        bullet_rows.append({
            "label": "%s / %s" % (i["incident_id"].replace("ARK-INC-", ""), i["priority"]),
            "segments": [(ratio, BREACH if late else PRIORITY_INK[i["priority"]])],
            "tick": 1.0,
            "value": ratio,
            "overflow": ratio > BULLET_CAP,
            "display": "%.0f" % minutes if minutes >= 10 else "%.1f" % minutes,
        })

    # --- Raised against cleared, by hour. This one is licensed by the moving store
    # and could not exist in v2, and it is the only chart here that reads event times
    # rather than current state - which is also why it is honest where an aging TREND
    # would not be. An incident's `created_at` and a transition's `recorded_at` are
    # facts about a moment and no later state change can rewrite them, whereas a
    # backlog reconstructed from today's statuses silently rewrites its own history
    # every time it is drawn (section 6 of the specification).
    now = datetime.datetime.now(datetime.timezone.utc)

    def hour_of(stamp):
        try:
            moment = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
        return int((now - moment).total_seconds() // 3600)

    HOURS = 6
    raised_by_hour = {h: 0 for h in range(HOURS)}
    cleared_by_hour = {h: 0 for h in range(HOURS)}
    for i in incidents:
        hour = hour_of(i.get("created_at"))
        if hour is not None and 0 <= hour < HOURS:
            raised_by_hour[hour] += 1
        for step in i["lifecycle"].get("history", []):
            if step.get("to_status") in ("closed", "false_positive"):
                hour = hour_of(step.get("recorded_at"))
                if hour is not None and 0 <= hour < HOURS:
                    cleared_by_hour[hour] += 1
    flow_rows = []
    for hour in range(HOURS):
        raised, cleared = raised_by_hour[hour], cleared_by_hour[hour]
        label = "this hour" if hour == 0 else "%d h ago" % hour
        flow_rows.append({
            "label": label,
            "segments": [(raised, PRIORITY_INK["P2"]), (cleared, PRIORITY_INK["P3"])],
            "value": raised + cleared,
            "display": "%d / %d" % (raised, cleared),
        })

    # --- Who acted, and when. Section 8: this is the transition log, which is a real
    # audit trail. It is NOT a notification log; the platform has none yet.
    feed = []
    for i in incidents:
        for step in i["lifecycle"].get("history", []):
            feed.append((step["recorded_at"], step, i))
    feed.sort(key=lambda row: row[0], reverse=True)
    feed_html = ['<table class="ark-rows ark-feed">']
    for recorded_at, step, incident in feed[:5]:
        stamp = local(recorded_at, "%H:%M") or recorded_at
        feed_html.append(
            '<tr><td class="t">%s</td><td class="a">%s</td>'
            '<td class="m">%s &nbsp;%s &rarr; %s</td></tr>'
            % (stamp, step.get("actor") or "unknown",
               incident["incident_id"].replace("ARK-INC-", ""),
               step.get("from_status"), step.get("to_status"))
        )
    feed_html.append("</table>")

    # --- Which models raise the work.
    by_module = {}
    for i in openi:
        by_module[i.get("source_module") or "unknown"] = by_module.get(i.get("source_module") or "unknown", 0) + 1
    module_rows = [
        {"label": name, "segments": [(count, PRIORITY_INK["P2"])],
         "value": count, "display": str(count)}
        for name, count in sorted(by_module.items(), key=lambda kv: -kv[1])
    ]

    legend = "".join(
        '<span class="ark-swatch" style="background:%s"></span>%s' % (PRIORITY_INK[p], p)
        for p in ("P1", "P2", "P3")
    ) + '<span class="ark-swatch" style="background:%s"></span>past its window' % BREACH

    truncation = ""
    if truncated:
        truncation = (" The store returned more incidents than the API's 50-row cap for %s, "
                      "so those bands are short." % ", ".join(truncated))

    board_html = (
        '<div class="arkon-board">'
        '<span class="ark-eyebrow">Executive view &nbsp;|&nbsp; as of %(as_of)s &nbsp;|&nbsp; '
        'refreshes every %(refresh)d s</span>'
        '<p class="ark-title">Arkon Quality Steering Cell</p>'
        '<p class="ark-status">%(sentence)s</p>'
        '<div class="ark-cards">%(cards)s</div>'
        '<div class="ark-panels">'
        '  <div class="ark-panel" style="flex:1.62 1 0">'
        '    <h3>Open incidents by age and priority</h3>'
        '    <p class="sub">A snapshot of what is open right now, not a history. The '
        'red segment is the incidents in that band whose response window has run '
        'out; the rest are shaded by priority.</p>'
        '    %(aging)s'
        '    <p class="ark-legend">%(legend)s</p>'
        '    <h3 style="margin-top:11px">Raised against cleared, by hour</h3>'
        '    <p class="sub">Event times, so nothing here is rewritten by a later '
        'state change. Cleared means closed or dismissed as a false positive.</p>'
        '    %(flow)s'
        '    <p class="ark-legend"><span class="ark-swatch" style="background:%(p2)s">'
        '</span>raised<span class="ark-swatch" style="background:%(p3)s"></span>cleared'
        '</p>'
        '  </div>'
        '  <div class="ark-panel ark-narrow-drop" style="flex:1 1 0">'
        '    <h3>Time to acknowledge, against the window allowed</h3>'
        '    <p class="sub">The bar is how the acknowledgement compared with that '
        'incident&#39;s own window, 15 min for P1 and 60 for P2, so the tick is always '
        'the window itself. Bars are cut off at four times it and marked; the number '
        'is the real figure in minutes. P3 has no window and no row.</p>'
        '    %(bullets)s'
        '    <h3 style="margin-top:11px">Open incidents by model</h3>'
        '    <p class="sub">Which of the seven modules the open work came from.</p>'
        '    %(modules)s'
        '  </div>'
        '  <div class="ark-panel ark-narrow-drop" style="flex:1 1 0">'
        '    <h3>Who acted, and when</h3>'
        '    <p class="sub">The last five lifecycle transitions, from the append-only '
        'transition log, on the plant clock.</p>'
        '    %(feed)s'
        '  </div>'
        '</div>'
        '<p class="ark-foot">Every figure comes from the n8n status API; this page folds nothing of its own, so it cannot disagree with the cockpit, the assistant or the workbook. Model evidence is real, the operational context around it is simulated and labelled so, and &quot;who acted&quot; is the transition log rather than a record of who was told.%(truncation)s</p>'
        '</div>'
    ) % {
        "as_of": local(as_of) or "an unknown time",
        "refresh": REFRESH_SECONDS,
        "sentence": status_sentence(incidents),
        "cards": card_html,
        "aging": hbars(aging_rows),
        "bullets": hbars(bullet_rows, widest=BULLET_CAP) if bullet_rows
                   else '<p class="ark-ctx">No incident with a response window has been '
                        'acknowledged yet.</p>',
        "feed": "".join(feed_html) if feed
                else '<p class="ark-ctx">No transition has been recorded yet.</p>',
        "modules": hbars(module_rows),
        "flow": hbars(flow_rows),
        "legend": legend,
        "p2": PRIORITY_INK["P2"],
        "p3": PRIORITY_INK["P3"],
        "truncation": truncation,
    }

    # The board is assembled by concatenating strings, and an unbalanced <div> in
    # that assembly does not raise anything: the browser silently reparents half the
    # page and the layout collapses into narrow columns. That happened once here, on
    # an edit that moved one panel and dropped its closing tag, and the only signal
    # was the picture looking wrong. Counting the tags is two lines and turns a
    # silent catastrophe into a sentence.
    opened, closed = board_html.count("<div"), board_html.count("</div>")
    if opened != closed:
        st.warning(
            "This page's markup is unbalanced: %d opening div tags against %d closing. "
            "The layout below is not what it is meant to be." % (opened, closed)
        )
    st.markdown(CSS + board_html, unsafe_allow_html=True)


# The whole board is one fragment, so the refresh redraws it without rerunning the
# rest of the app. Streamlit reruns the fragment on its own clock; nothing here polls.
try:
    board = st.fragment(run_every=REFRESH_SECONDS)(board)
except TypeError:
    # An older Streamlit has no run_every. The page still works; it just does not
    # refresh itself, and saying so is better than looking live and being stale.
    st.caption("This Streamlit does not support timed refresh, so reload to update.")

board()
