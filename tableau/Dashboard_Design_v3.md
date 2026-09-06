# Executive view v3: design specification

Written 2026-09-05 after Sergey judged v2 still short of the bar, in his words "not
global best practice for a live executive dashboard: hard to read, colour choice not
the best, numbers not aligned to columns", and set the standard as something that
could be put in front of a big-tech leadership team. This is the deep rework he asked
for rather than a polish pass, researched first and cited at the end.

It is one specification for two surfaces. The Tableau workbook is the published
snapshot; the cockpit's Executive page is the always-live one. They carry the same
hierarchy, the same numbers and the same colour rules, because two executive views of
one plant that look different are two claims about that plant.

`Dashboard_Design.md` is v2 and stays as the record of what was built and why. This
file supersedes its sections 2 to 8; sections 1, 9 and 10 there are still accurate
about their subjects.

---

## 1. What changed under this dashboard, and it changes the design

**The store moves now.** v2 was designed against a static extract, which is why it
carries the line "no sparklines: the store has one extract date and no history; a
sparkline over one point would be decoration". The live plant has been raising an
incident every eight to twelve minutes since 18:01, a crew has been acknowledging and
closing them, and the store now spans 2026-08-30 to the current minute. Two views
become possible that could not exist in v2, and one trap opens that did not exist
either. Both are in section 6.

**The store is bimodal, and that is the story.** Measured on the extract of
2026-09-05 19:21, 36 incidents are open and their ages split into two groups with
nothing between them: 11 raised in the last four hours by the running plant, and 20
more than three days old, from the replay batches of earlier sessions that nobody ever
worked. There is not a single open incident between four hours and one day old.

That shape is the single most useful thing this dashboard can show an executive, and
neither v1 nor v2 showed it at all. "26 open, 16 overdue" says a number. "20 of the 36
open incidents have been open for more than three days, and none of them has ever been
acknowledged" says what is wrong with the process. An aged backlog behind a healthy
live stream is exactly the pattern an incident-management dashboard exists to expose,
and it is what the ITSM literature calls aged backlog analysis.

---

## 2. The one message

A plant manager gets five seconds. The dashboard answers one question in those five
seconds: **is the Steering Cell keeping up, and if not, where is it behind?**

The hierarchy under that, in the order the eye should meet it:

1. **The breach count**, as the largest number on the page, with its share of open
   incidents beside it. Red, and the only red on the page.
2. **Three supporting numbers on the same baseline**: open incidents, median time to
   acknowledge against the window that was allowed, median time to close.
3. **Where the backlog is**, as an aging profile by priority. This is the dominant
   chart and it is where the bimodality shows.
4. **How late "late" is**, as bullet bars of time to acknowledge against each
   incident's own allowed window.
5. **Who acted and when**, demoted to a strip: the transition log as an activity feed.
6. **Which models are raising the work**, demoted with it.

A dashboard is "a visual display of data used to monitor conditions and facilitate
understanding" (Wexler, Shaffer and Cotgreave). Everything below band 2 exists to
answer "why" once bands 1 and 2 have answered "whether".

---

## 3. Layout: 1600 x 900, and the number grid

Sergey asked for 1600 x 900, which is a presentation screen rather than a laptop, and
that is also what buys the number grid below. Tiled containers, never floating.

White space is planned arithmetically rather than nudged, the method Playfair Data
sets out: fix the canvas, fix the gaps, divide. Tableau's own default is 4 px of
padding around every object, which is too tight to separate bands at this size.

```
outer margin        24 px on all four sides
band gap            20 px vertical
card gap            16 px horizontal
usable width        1600 - 48 = 1552
four KPI cards      (1552 - 3 x 16) / 4 = 376 px each
main row split      1552 x 0.62 = 962 left, 574 right, 16 px gap
```

```
+--------------------------------------------------------------------------+
| Arkon Quality Steering Cell            Executive view    as of 05 Sep 21:21|  40
| 20 of 36 open incidents have been open more than three days, none of them  |  34
| ever acknowledged. The 11 raised tonight are being worked inside window.    |
+--------------------------------------------------------------------------+
| [ OVERDUE   ] [ OPEN      ] [ TIME TO ACK ] [ TIME TO CLOSE ]              | 150
| [ 14        ] [ 36        ] [ 20.3 min    ] [ 90.9 min      ]              |
| [ of 36 open] [ 56 raised ] [ window 15/60] [ 20 closed     ]              |
+---------------------------------------------+----------------------------+
| Open incidents by age and priority          | Time to acknowledge        |
| stacked bars, one row per age band          | bullet bars vs the window  | 400
| P1 / P2 / P3 as three intensities of navy   | red only past the window   |
| red only on the bands that are past window  |                            |
+---------------------------------------------+----------------------------+
| Who acted, and when            | Incidents by model                      | 180
| last 8 transitions, actor+time | sorted desc, one navy                   |
+--------------------------------------------------------------------------+
| Source: n8n status API, extract of <as_of>. Operational context simulated. |  32
+--------------------------------------------------------------------------+
```

40 + 34 + 150 + 400 + 180 + 32 = 836, plus five 20 px band gaps and 2 x 24 outer
margin = 984.

**Corrected at build time, 2026-09-06.** The trim above worked out to 352, and the
subtraction gives 316; the sentence was written before the arithmetic was done. The
budget is therefore solved in `build_workbook.py` and asserted there rather than
carried in prose, because `bands()` normalises whatever it is handed and a budget that
does not add up rescales every box silently instead of failing.

The built band heights, which sum to exactly 900 with the zone margins inside them:

| Band | px | Holds |
|---|---|---|
| Header | 84 | Title, the generated status sentence, the as-of stamp |
| Filters | 44 | The three list parameters |
| KPI row | 150 | Four BANs |
| Main | 330 | Aging profile (62 percent) and bullet bars (38 percent) |
| Strip | 236 | Activity feed (62 percent) and models (38 percent) |
| Footer | 56 | What this store is |

Two of those differ from the plan on purpose. **The filter band survives**: this
document's layout has no room for it and section 11 argues an executive view should be
a statement, but the three controls were already built, they work (verified by setting
Priority to P1 and reading 11 raised, 11 closed, 0 open off the cards), and dropping a
working feature is Sergey's call rather than the specification's. **The strip grew and
the main row shrank**: at 186 px, seven model rows and six feed rows had about 14 px
each and their 11 pt labels overlapped into an unreadable stack, while the main row had
room to spare with five aging rows.

**A horizontal container does not honour a proportional child box.** The 62/38 split is
in the XML exactly as written, and Tableau rendered the charts 50/50 and the strip
18/82, sizing the text table to its own content. The right-hand child carries an
explicit pixel width and the left takes the remainder; that is what holds.

**Every block is left-aligned, and every number sits on a column grid.** This is the
point Sergey made most sharply and it is the one that separates a dashboard that looks
designed from one that looks assembled. Concretely:

- The four KPI cards are left-aligned inside themselves: label, number and context all
  start at the same x. Not centred. A centred number moves as its digits change, so a
  row of centred BANs has no vertical line anywhere in it.
- The four card numbers share one baseline, which means one font size for all four
  regardless of how many digits each has: 38 pt.
- Bar labels are right-aligned at the end of their bars, one decimal at most, and the
  same number of decimals within a chart.
- Row headers in the aging chart are one column, left-aligned, single line.

---

## 4. The KPI row: four BANs with context

Wexler's term for the big numbers at the top of a dashboard is BAN, and the pattern
that carries them is the KPI row: three to six cards across the top, charts below.
Six is the practical ceiling before cards get too narrow; four at 376 px is
comfortable.

A BAN without context is a number without a claim, so each card is three left-aligned
lines:

| Card | Label | Number | Context line |
|---|---|---|---|
| 1 | OVERDUE | 14 | of 36 open, 39 percent |
| 2 | OPEN | 36 | 56 raised, 20 closed |
| 3 | TIME TO ACKNOWLEDGE | 20.3 min | median, window 15 min P1 / 60 min P2 |
| 4 | TIME TO CLOSE | 90.9 min | median over 20 closed |

Card 1 is the only one with red ink and it carries a 6 px red rule on its left edge.
Cards 2 to 4 carry the same rule in the neutral gray, so the four cards are the same
object and only one of them is shouting.

Every figure comes from `store_summary.csv`, which is the status API's own computation.
The dashboard recomputes nothing. Cards 3 and 4 are MTTA and MTTR under their plant
names; the incident-management field leads with exactly those two plus SLA compliance
and backlog, which cards 1 and 2 carry.

---

## 5. The status line, and why it is a sentence

Under the title, one sentence, 13 pt, near-black on the canvas:

> 20 of 36 open incidents have been open more than three days, none of them ever
> acknowledged. The 11 raised tonight are being worked inside window.

It is generated, not typed: the generator computes both clauses from `incidents.csv`
and writes the string into the title zone. A sentence is worth more than a fifth KPI
card because it states the relationship between two numbers, which is the thing a card
cannot do and the thing an executive actually wants.

Rule for the generator: state the largest age band and its share, then whether the
freshest band is inside or outside its window. If the two clauses ever agree, the
sentence collapses to one clause rather than saying the same thing twice.

---

## 6. The aging profile: the dominant view, and the trap under it

**The chart.** Horizontal stacked bars, one row per age band, stacked by priority.
Age bands chosen for this store rather than copied: **under 1 h, 1 to 4 h, 4 to 24 h,
1 to 3 days, over 3 days.** The ITSM convention is coarser (0-5, 6-15, 16-30, 30+
days) because a service desk measures in days; this Steering Cell measures P1 in
fifteen minutes, so the bands have to open at the hour scale or the whole live stream
collapses into one bar. The empty 4-to-24-hour band stays on the axis: an empty band
between two full ones is information, and dropping it would hide the shape.

Row headers are **one combined label per row**, not two nested header columns.

**As built the label is the band name alone**, and the overdue count is carried by the
red segment's own data label instead. Composing `over 3 d / 11 overdue` in Tableau needs
a FIXED level-of-detail expression, and a FIXED LOD is computed before the dimension
filters, so the three parameter controls would have left a row label counting incidents
the chart was no longer drawing. A number that contradicts the bar beside it is worse
than a plainer label.

**The trap, and it is the reason there is no aging trend on this dashboard.** An aging
chart built from current state is honest about today and lies about every other day:
an incident that was open and ten days old in March reads as closed today, so a query
over current status reconstructs today's backlog and calls it history. `build_extracts.py`
writes current state only and keeps no dated snapshots, so **this dashboard shows an
aging snapshot and must never grow an aging trend line until the extract layer appends
a dated row per open incident per run.** That is the same finding v2 recorded about
sparklines, met again one level up, and it is written here so the next person who
thinks "we have timestamps now, we can trend this" reads the answer first.

**What the moving store does license**, because both read event times rather than
current state: incidents raised per hour from `created_at`, and closures per hour from
`transitions.recorded_at` where `to_status` is closed or false_positive. Those two as
one small combined chart are a genuine arrival-versus-clearance view and cannot be
falsified by later state changes. Held back from v3 only because the layout has no
sixth band; it is the first thing to add if a band is freed.

---

## 7. Time to acknowledge: bullet bars

Few designed the bullet graph to replace the gauges that dashboards accumulate: a
featured measure, one or two comparative measures, and two to five qualitative ranges
declaring the featured measure's state. His rules that bind here:

- **Ranges limited to five, ideally three**, because more than five needs perceptual
  reasoning a dashboard does not have time for. This chart uses two: inside the window
  and past it.
- **Ranges encoded as intensities of a single hue, not distinct hues**, so the chart
  survives colour blindness.
- The comparative measure is a single perpendicular tick, not a bar.

Applied: one row per acknowledged incident, the bar is the ratio to that incident's own
allowed window (15 minutes for P1, 60 for P2), the tick is that window at 1.0, and the
bar is red only where it has passed the tick. Sorted descending. The row label is the
incident id plus priority in one column.

**Six rows, not twelve.** Measured on the render: this panel pays for two things the
aging chart beside it does not, a wrapped second caption line and a quantitative axis,
which together cost about 43 px of a 143 px plot. At twelve rows that left four pixels
each and the labels printed on top of one another. Six rows and a one-line caption put
it back in proportion with the panel beside it.

**A consequence worth stating**: the six slowest acknowledgements are currently all
past their window, so the chart shows no in-window bar and Few's two qualitative ranges
collapse to one on this data. That is the honest answer to the question the panel asks
("how late is late") and the in-window count is on card 3, but if the store ever becomes
mostly punctual the selection rule is the thing to revisit.

**The axis stays visible**, which is a change from section 10's instinct to hide it.
Hiding it also removed the window tick, and a bullet graph without its quantitative
scale is not a bullet graph: the reader has to be able to see where 1.0 sits. It is the
axis TITLE that section 10 drops, not the axis.

P3 and P4 have no window and therefore no row. That is not a gap to fill with a zero.

---

## 8. Who acted, and when

Sergey asked for a notification panel, "who was told what, when". The honest version of
that panel today is **who acted**, and the difference has to be stated rather than
papered over.

**What is recorded:** every lifecycle transition, with the actor, the timestamp and
the free-text note (`transitions.csv`). That is a real audit trail and it is what the
panel shows: the last eight transitions as `time . actor . incident . from -> to`.

**What is not recorded anywhere queryable:** whether a Telegram card was actually
delivered. The intake workflow answers `incident_created_alert_sent` and Telegram's
reply carries a `message_id`, but that lives only in the n8n execution record; no
store holds it. So a panel claiming "told" would be inferring from the rule that P1
and P2 alert, and this project does not put inferred facts on dashboards.

**What closes the gap:** deploying `n8n/overdue_escalation_v1.json`, which writes
`incident_notifications.jsonl` carrying Telegram's own `message_id` per notification.
On the day that deploys, the panel becomes two lanes, told and acted, and this section
gets rewritten. Until then the panel is titled "Who acted, and when" and the footer
says the notification log does not exist yet.

---

## 9. Colour

v2 used one blue plus red. Sergey's note was that the choice is "not the best" and
that red should stay for breach. The v3 palette is a single navy family plus one
reserved red, which is also what lets the aging chart stack three priorities without
inventing three unrelated hues:

| Token | Value | Used for |
|---|---|---|
| canvas | `#F2F2EF` | page background |
| card | `#FFFFFF` | KPI cards and chart panels |
| ink | `#16161A` | numbers and titles |
| context | `#55555E` | context lines, axis labels, captions |
| navy 1 | `#1F3A63` | P1, and the single-series bars |
| navy 2 | `#3D6394` | P2 |
| navy 3 | `#8AA6C8` | P3 |
| rule | `#D8D8D2` | card left rules, separators, axis lines |
| breach | `#C0392B` | a response window that has run out. Nothing else. |

**`#55555E` replaces v2's `#6B6B66`**, which Sergey read as too light on the gray
canvas and which measures at roughly 4.0:1 against `#F2F2EF`; the replacement is about
7.3:1 and clears WCAG AA for body text with margin. The three navies are intensities
of one hue, which is Few's rule for ordered categories, and priority is ordered.

Red appears in exactly three places on the whole page: the OVERDUE card's number and
its left rule, the aging rows entirely past window, and the bullet bars past their
tick. If a viewer sees red anywhere, a response window has run out. It is never a
series colour and never a highlight.

---

## 10. Typography

Tableau's own typeface, which is what the workbook has and what the cockpit should
match with a system stack. Five sizes and no more:

| Role | Size | Weight | Colour |
|---|---|---|---|
| Dashboard title | 22 pt | Medium | ink |
| Status sentence | 13 pt | Regular | ink |
| BAN | 38 pt | Bold | ink, or breach on card 1 |
| Card label | 10 pt | Bold, letterspaced, uppercase | context |
| Card context, captions, axis | 11 pt | Regular | context |
| Chart title | 13 pt | Medium | ink |
| Bar value label | 12 pt | Bold | ink |

Sergey asked for 36 to 40 pt figures on one baseline and 11 to 12 pt bold bar labels;
38 and 12 sit in both ranges. Gridlines, zero lines, row banding and worksheet borders
stay off, as in v2. Axis titles are dropped wherever the chart title already names the
unit.

---

## 11. The cockpit's Executive page, same design

The Tableau workbook cannot refresh itself: Tableau Public has no API and its only
scheduled refresh is Google Sheets. So the honest live surface is a page in the
cockpit, reading the same status API with no manual step, and it is built from this
same specification rather than from a second idea.

What carries across unchanged: the hierarchy of section 2, the four BANs and their
context lines, the status sentence, the aging profile, the bullet bars, the activity
strip, and the whole palette and type scale of sections 9 and 10.

What is different, and only because the medium is:

- It reads the status API directly rather than an extract, so it has no "as of" lag to
  explain. It stamps the API's own `as_of` instead.
- It has no filters. An executive page is a statement, and the cockpit's Steering Cell
  page already carries the filterable list one click away.
- It auto-refreshes on a fixed interval, and the interval is stated on the page.
- Charts are drawn with the same primitives the rest of the cockpit uses, so nothing
  new is added to the image.

The two surfaces are checked against each other by reading one number off each on the
same minute. If they disagree, the extract is stale and that is what the "as of" stamp
is for.

---

## 12. What this dashboard deliberately does not show

- **P4.** The store contains none, and the reason is not that no module publishes one:
  CMAPSS publishes 481 P4 events and the replays filtered them out, while the live
  plant excludes them by default and admits them under `--include-p4`. So P4 is a
  switch rather than a design absence, and the dashboard shows the three levels the
  store holds. Adding an empty P4 row would assert something false about the plant.
- **An aging trend.** Section 6.
- **Sparklines.** Same reason as the trend: no dated snapshots.
- **Recurrence.** The quality-management literature leads with it, and it is the right
  measure for whether a corrective action worked. It cannot be computed here, because
  the same evidence record within 24 hours is suppressed by design and nothing tracks
  a record across suppression windows.
- **Cost of poor quality.** The measure that reaches executives fastest, and there is
  no cost figure anywhere in this system.

---

## 13. What Tableau refused, and what it silently ignored

Four findings from building this, each cheaper to read than to rediscover. Three of them
produce no error at all, which is what makes them worth writing down.

**`customized-tooltip` comes before `customized-label`.** Tableau refused the whole
workbook and named the content model: `(view, mark, mark-sizing?, encodings?, label-data?,
dropline?, trendline?, reference-line, customized-tooltip, customized-label, style)`. v2
never met this because no sheet carried both; the bullet chart is the first with a
reference line, a custom label and a custom tooltip together.

**A reference line whose value column is on no shelf is written and never drawn.** The
window tick was in the file, valid, and invisible. v2's tick worked by accident: its value
field was already on Detail for the tooltip. Putting the field on Detail is what draws it.
Its label is then set to `none`, because on a ratio axis the default printed "1.0000"
beside every row, which is the number the axis already carries.

**Fit is a property of the worksheet's window, not of the dashboard.** The dashboard
`<viewpoints>` block already asked for `entire-view` per sheet and every sheet still
rendered at the default Standard fit, so seven model bars used 32 px of a 140 px card.
The element that binds is `<viewpoint><zoom type='entire-view' /></viewpoint>` inside
`<window class='worksheet'>`. Found by setting it on one sheet with the mouse, saving,
and diffing - the same method that found the colour-map declaration for v2. Note that
Tableau Public's Ctrl+S publishes to the web; File > Save As is the local one.

**A stacked colour dimension stacks in DESCENDING sort order.** The dictionary that read
Overdue-first put the red at the far end of every bar, where its length has no common
baseline to be read against. Reversing it puts breach at the axis on both charts.

**And one that is not about Tableau.** `Preferences.tps` in this folder defined the same
palette NAME with the v2 colours. The workbook embeds its own copy and renders correctly
from it, but Tableau merges a same-named local palette over the embedded one when a
workbook is saved from the application, so the stale file came back as the v2 red and
gray in a hand save. Both now carry the section 9 values.

---

## 14. The footer says the response times are simulated, and that is a correction

The footer in section 3 read "Operational context simulated", which is true about the
people, lines and shifts on an incident and says nothing about the two response-time
cards beside it. Sergey asked on 2026-09-06 whether the crew working the incidents is an
automatic step. It is: `live_plant/plant.py` rolls per-incident probabilities every tick
and posts to the same transition endpoint an operator's form posts to, so **cards 3 and 4
measure that emitter rather than a workforce**, and the footer now says so.

The measurement behind it: of 302 transitions in the extract of that morning, 301 carry a
name from the simulated roster and one carries Sergey's. That is not a count of human
actions - the cockpit's transition form records the identity picked in its own selector,
and the crew draws from the same roster, so **a person's move and a dice roll are
indistinguishable in the `actor` column**. Every timestamp is real, which is why the
footer keeps that clause too.

The fix that would make the distinction real is small and is not built: the emitter sends
an origin marker to the transition endpoint, the endpoint stores it, and the two surfaces
can then separate work done by the crew from work done by a person. It is worth doing
because it turns "the numbers are simulated" into "the system records who made each move,
including whether it was a bot".

---

## Sources

Read 2026-09-05 for this revision. The v2 sources in `Dashboard_Design.md` still stand
and are not repeated.

- The Big Book of Dashboards, Wexler, Shaffer and Cotgreave: the definition of a
  dashboard as a display used to monitor conditions and facilitate understanding, and
  the BAN as the named pattern for the headline number.
  https://www.tableau.com/big-book-dashboards
- Stephen Few, Information Dashboard Design, and the bullet graph specification: the
  bullet graph as the replacement for gauges, a maximum of five qualitative ranges and
  ideally three, and ranges encoded as intensities of one hue rather than distinct hues
  so they survive colour blindness.
  https://www.perceptualedge.com/articles/misc/Bullet_Graph_Design_Spec.pdf
- Dashboard layout patterns, the KPI row plus chart grid as the executive pattern and
  the six-card ceiling before cards get too narrow.
  https://www.datawirefra.me/blog/dashboard-layout-patterns
- Playfair Data (Ryan Sleeper), white space in Tableau: the 4 px default padding and
  the arithmetic method of fixing canvas and gaps and dividing.
  https://playfairdata.com/dashboard-element-5-white-space/
- PagerDuty analytics: total incidents, MTTA, MTTR and acknowledgement rate as the
  metric set an incident dashboard leads with.
  https://support.pagerduty.com/main/docs/analytics-dashboard
- Aged backlog analysis and the snapshot warning: an aging chart built from current
  status reconstructs today's backlog rather than history, so a trend needs a scheduled
  job appending open-ticket ages per run.
  https://docs.bmc.com/docs/bhd/234/bmc-helix-itsm-incident-aged-backlog-analysis-dashboard-1276738500.html
  https://www.metabase.com/dashboards/it-ticket-dashboard
- Qualityze, nonconformance KPIs: recurrence as the measure of whether the quality
  system is improving, which is why section 12 says why it cannot be computed here.
  https://www.qualityze.com/blogs/top-kpis-nonconformance
