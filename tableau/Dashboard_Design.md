# Executive view: design specification

Written 2026-09-05 after Sergey judged the first built dashboard below the level the
project needs. He was right: `Arkon_Executive_View.twb` v1 is numerically correct and
visually a Tableau default. This note is the redesign, grounded in the sources at the
end (all read that day, nothing quoted from memory), applied to this dashboard's own
data.

**Status, 2026-09-05 evening: BUILT by the generator, sections 2 to 8, and verified in
Tableau Public 2026.2 by opening, clicking and hovering.** The hybrid split in section
10 turned out not to be needed: everything it assigned to "the application" was
expressible in XML once the forms were read out of Tableau's own files, so the
generator produces the finished view and nothing is reapplied by hand. What remains
is section 9, the publish, which is Sergey's sign-in. `README.md` describes what was
built and where every number comes from; the build record is in the vault log of
2026-09-05.

## 1. What v1 gets wrong, measured against the sources

| Defect in v1 | The rule it breaks | Source |
|---|---|---|
| Five charts plus three tiles, all the same visual weight | "limit the number of views ... to two or three"; important content should be LARGER than the rest | Tableau help; Blueprint |
| No reading order: the eye has nowhere to land | "most important view ... upper-left"; newspaper / Z-layout, most important top-left, detail right and down | Tableau help; Blueprint |
| KPI tiles are a bare number with a label | a KPI needs context: comparison, target or delta, or it is not a sentence anyone can act on | phData; Domo/Perceptive (search summaries) |
| Default gridlines, axis titles, alphabetical bars | delineate with negative space and padding, not lines; sort so the shape carries the message | Blueprint |
| No color meaning at all (one blue everywhere) | primary palette neutral, ONE accent for what must be noticed, alert colors reserved strictly for alerts | Blueprint |
| Sentence-long chart titles, tiny caveat footer | titles digestible, subtitles say how to read or interact | Blueprint |
| No filters, no highlight, no drill-down | interactivity should be discoverable and predictable; show filters with clear titles; highlight between views | Tableau help |
| Desktop only | separate phone layout, "fit width" for vertical scrolling | Tableau help |
| No "as of" stamp, no source, no owner | executives need to know how fresh the number is | incident-dashboard conventions (search summaries) |

Five-second test on v1, honestly applied: a stranger sees eight equal boxes of blue
bars and cannot say what the dashboard wants them to do. That is the whole problem.

## 2. The one message, and the hierarchy under it

The dashboard answers one question for a plant manager: **are we on top of the open
incidents?** Everything is arranged so that this is read in five seconds and the rest
is read only if wanted.

1. **Dominant metric:** open incidents past their response window, as a count AND as a
   share of open incidents (today 16 of 26, 62 percent). The only red on the page.
2. **Supporting, same row, smaller:** open incidents (26); acknowledged inside the
   window (0 of 2 that were acknowledged at all); median time to acknowledge (65.7 h)
   against the windows the SOP allows (15 min P1, 60 min P2, 24 h P3).
3. **Explanatory, middle band:** where the overdue sit (priority by response state),
   and how late "late" is (time to acknowledge against the allowed window).
4. **Detail, bottom band:** which modules raised the incidents, and what the lifecycle
   has recorded. Collapsible in spirit: smaller, grayer, no red.

Two-to-three views is the Tableau rule; the design respects it by making the middle
band the two real views, the KPI row one composite object, and the bottom band a
demoted detail strip rather than two more equal charts.

## 3. Layout

Fixed size, authored at the size it is viewed: **1300 x 900** desktop, plus a phone
layout (section 8). Tiled containers, not floating, so the grid survives edits. Z
reading order: title band, KPI row, main row left-heavy, detail strip, footer.

```
+----------------------------------------------------------------------------------+
| Arkon Quality Steering Cell            Executive view      as of 05 Sep 2026 11:51 |  56 px
| Open incidents across seven inspection and reliability models, demo store          |
+----------------------------------------------------------------------------------+
| [ OVERDUE 16 of 26 open ] [ OPEN 26 ] [ ACK IN WINDOW 0 of 2 ] [ MEDIAN ACK 65.7 h ] | 130 px
|   red stripe, red number    neutral       neutral                neutral            |
+-----------------------------------------------+----------------------------------+
| Open incidents by priority and response state | Time to acknowledge vs window    |
| (the most important view, 60 percent width)   | (bullet bars, allowed window as  |
|  P1  Overdue        #1                        |  a reference tick)               | 380 px
|  P2  Overdue        ###############15         |  ARK-INC-00013  6,225 min | 15  |
|  P3  Within window  ##########10 (gray)       |  ARK-INC-00032  1,657 min | 60  |
+-----------------------------------------------+----------------------------------+
| Incidents by model (sorted desc, domain color-neutral) | Lifecycle transitions   | 220 px
+----------------------------------------------------------------------------------+
| What this store is (one line) . Source: status API, extract layer . Repo link      |  50 px
+----------------------------------------------------------------------------------+
```

Sizes are shares of 900 px height; the sum is 836 with 64 px of padding between bands.
Upper-left is the priority view because it is where the red lives.

## 4. KPI cards

Built the way the Data School and phData describe: a white card on a light gray canvas
(`#F5F5F3`), 4 px outer padding, 8 to 12 px inner padding, a 6 px accent stripe on the
left of the card that is red on the overdue card only and gray on the rest. Each card is
one worksheet with a Text mark and three lines:

| Line | Content | Type |
|---|---|---|
| label | OVERDUE (caps, letter-spaced) | 9 pt, gray `#6B6B66` |
| number | 16 | 30 pt Tableau Bold, red `#d03b3b` on this card, near-black `#1F1F1D` elsewhere |
| context | of 26 open, 62 percent | 10 pt, gray |

Contexts for the four cards, computed from `store_summary.csv` (the API's own numbers,
never recomputed): "of 26 open, 62 percent"; "3 P1, 16 P2, 10 P3" (from `incidents`,
the one exception); "of 2 acknowledged, both late"; "windows: 15 min P1, 60 min P2".
No sparklines: the store has one extract date and no history; a sparkline over one point
would be decoration, which is the exact thing the sources forbid. Add sparklines only
once `build_extracts.py` keeps dated snapshots.

## 5. Color

- **Neutral primary.** Canvas `#F5F5F3`, cards white, text near-black `#1F1F1D` and
  gray `#6B6B66`, axis and reference ticks `#C3C2B7`. Grayscale carries the structure.
- **One data accent.** `#2a78d6` for bars that carry no state (models, transitions,
  the within-window rows).
- **One alert color, reserved.** `#d03b3b` for overdue and for nothing else: the overdue
  card's number and stripe, the P1 and P2 overdue bars, the breach side of the time-to-
  acknowledge bars. A viewer who sees red anywhere on this page is looking at a
  response window that has run out. Never used on a series.
- **Register both as named palettes** in `Documents/My Tableau Repository/Preferences.tps`
  (Tableau's documented custom-palette route, `<color-palette name="Arkon status"
  type="regular">`), so the GUI's Edit Colors / Assign Palette applies them in one
  click. This matters because the generator's XML `<map to>` assignment was ignored by
  Tableau 2026.1 (see `README.md`), so color is assigned in the application, not in the
  generator, until that is understood.
- Color-blind check: red against gray, never red against green; the state is also
  written on the row header, so no meaning is color-alone.

## 6. Typography and declutter

Tableau's own typeface, which is the default and is designed for small sizes. Three
levels only: dashboard title 20 pt Tableau Medium; card numbers 30 pt Bold; section
titles 12 pt Medium; everything else 9 to 10 pt Regular. Titles become short nouns
("Open incidents by priority", "Time to acknowledge"), and the sentence that v1 put in
the title moves to a 9 pt gray subtitle that says how to read the chart.

Remove: gridlines, zero lines, axis titles where the subtitle already names the unit,
row banding, worksheet borders. Keep: direct value labels on every bar (there are at most
seven marks per chart, so this is not clutter), a single reference tick for the allowed
window. Sort every bar chart descending. Padding, not lines, separates the bands.

## 7. Interactivity

- **Filter row** under the title band, right-aligned, three dropdowns with plain titles:
  Priority, Model, Status. All three apply to every sheet.
- **Highlight action** from the priority view to the model view: click P2 Overdue and the
  bars of the models that raised those incidents light up, the rest recede.
- **Drill-down sheet**, hidden until used: "Incidents behind this bar", a text table of
  incident id, priority, raised at, age, assignee, summary; opened by a dashboard
  action from any bar, shown as a sheet in a floating container or as a separate tab.
- **Tooltips rewritten as sentences**: "ARK-INC-00013, P1, raised 30 Aug 12:00,
  acknowledged after 6,225 minutes against a 15 minute window, M. Brandt." Every field
  in the tooltip is one already in `incidents.csv`.

## 8. Device layout

Phone layout, fit width, vertical: title, the overdue card alone at full width, the
priority view, then the other three cards in a 2 x 2 grid, and nothing else. The detail
strip is desktop-only. Tableau Public renders the phone layout automatically when the
viewport is narrow, so this is what a recruiter opening the link on a phone sees first.

## 9. Publishing polish on Tableau Public

Show only the dashboard (hide the sheets), name the viz "Arkon Quality Steering Cell,
executive view", set the description to the one-line caveat plus the repository link,
tag it (manufacturing, quality, incident management, n8n, Tableau Public), and let the
thumbnail be the dashboard at 1300 x 900. Add the "as of" stamp from
`store_summary.as_of` to the subtitle so the freshness is on the image itself.

## 10. Implementation plan, and the honest split

> Superseded the same evening, see the status note at the top: the generator now
> builds everything below, including the parts this section reserved for the mouse.
> Kept as the record of what was known when the split was drawn.


The generator can produce, with forms already verified in Tableau 2026.1: the container
tree and band sizes, text zones (title, subtitle, footer), sheet placement, nested row
headers, mark labels, single mark colors, sort-free layouts, and all the data plumbing.
What it has NOT been able to do, verified by trying: per-member color assignment (the
palette was ignored), and everything in sections 4 to 7 that Tableau stores as
formatting XML nobody has read from a working file yet (fonts, sizes, padding, borders,
gridline removal, reference lines, filters, actions, device layouts).

So the recommended route is a **hybrid**:

1. **Generator (this repository):** produce the skeleton, the data, the KPI card sheets
   with their three text lines as calculated strings, the band layout at the pixel sizes
   above, the subtitle texts, and the sort order via a computed sort field. Keep it
   deterministic and committed. This is the reproducible half.
2. **Application (one sitting, Sergey or an agent with computer use):** open the `.twbx`,
   apply the registered palettes, set fonts and padding, remove gridlines, add the
   reference tick, the three filters, the highlight action, the drill-down action, the
   phone layout, then sign in and save. This is the half Tableau is built to do with a
   mouse, and it is what he asked for on 2026-09-05.
3. **Close the loop:** update to Tableau Public 2026.2.2 and save a local `.twbx` of the
   polished result beside the generated one, so the published view has a file in the
   repository even though the polish was manual. The generated skeleton remains the
   thing that regenerates when the store changes; the polish is reapplied once.

Order of value if time is short: the KPI cards with context and the red reserved for
overdue (section 4 and 5) fix the five-second test on their own; layout and declutter
come second; interactivity third; the phone layout last.

## Sources added by the build session, 2026-09-05

Read while building, to check the specification against the practice of the two
fields it sits in; nothing in them contradicted sections 2 to 9.

- Freshworks, Incident management KPIs and metrics: lead with severity-weighted
  metrics (MTTA, MTTR, SLA compliance, backlog); a Sev-1 outage carries more weight
  than the rest, which is why the overdue P1 and P2 bars are the only red on the page.
  https://www.freshworks.com/incident-management/kpis-metrics/
- Senturus, Tableau dashboard design: 10 best practices (five-second rule, summary
  on top driving detail below, select / hover / menu as the three navigation types,
  colour to spotlight a threshold rather than to decorate).
  https://senturus.com/blog/tableau-dashboard-design-10-best-practices/
- Qualityze, Top 10 KPIs for nonconformance management (time to close, on-time
  investigation completion, recurrence): the quality-management reading of the same
  overdue and response-time measures. https://www.qualityze.com/blogs/top-kpis-nonconformance
- Ben Moss, How to encode 10,000 colours in one hit within Tableau: the XML form of a
  colour map, and the reason an "Automatic" palette is never persisted.
  https://benjnmoss.wordpress.com/2017/01/05/how-to-encode-10000-colours-to-in-one-hit-within-tableau/

## Sources

Read 2026-09-05. Only these were used; three further pages (a template vendor, a Tableau
Public viz, a PDF whitepaper) could not be fetched and are not cited.

- Tableau help, Best Practices for Effective Dashboards:
  https://help.tableau.com/current/pro/desktop/en-us/dashboards_best_practices.htm
- Tableau Blueprint, Visual Best Practices:
  https://help.tableau.com/current/blueprint/en-us/bp_visual_best_practices.htm
- Tableau help, Create Custom Color Palettes (Preferences.tps):
  https://help.tableau.com/current/pro/desktop/en-us/formatting_create_custom_colors.htm
- phData, Adding Context to KPIs in Tableau:
  https://www.phdata.io/blog/adding-context-to-kpis-in-tableau/
- The Data School, Creating neat KPI cards:
  https://www.thedataschool.co.uk/lisa-hitch/creating-neat-kpi-cards/
- Ann Pregler, Advanced Tableau Color Palettes:
  https://annpregler.com/2024/10/15/advanced-tableau-color-palettes/
- Search-result summaries (not fetched in full) on executive dashboard hierarchy and the
  five-second rule: Domo, Perceptive Analytics, appdeck; and on incident dashboard KPI
  conventions (overdue rate, time to solve, SLA share, by priority): Tableau's ServiceNow
  dashboard starters page.
