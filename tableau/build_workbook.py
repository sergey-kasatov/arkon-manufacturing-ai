"""Generate the Arkon executive Tableau workbook from the extract layer.

One command, three artifacts:

    python tableau/build_workbook.py                  # .hyper extracts, .twb, .twbx
    python tableau/build_workbook.py --skip-extracts  # reuse the .hyper files already there

It writes `tableau/Arkon_Executive_View.twb`, wired to `.hyper` extracts built from
the CSVs in `tableau/extracts/`, and `tableau/Arkon_Executive_View.twbx`, the same
workbook packaged with those extracts. A `.twb` is XML, so the workbook is
version-controlled and diffable here rather than a binary the application owns.
The sequence is: run this, open the file in Tableau Public, sign in, save. The
save is the publish and it is Sergey's step.

The `.twb` is deterministic: the same extracts produce a byte-identical file, so
this generator can be checked against its own artifact before it is trusted.
`--skip-extracts` exists because an open workbook holds its `.hyper` files locked;
it lets the XML be regenerated while Tableau still has the previous build open.

Design authority is `tableau/Dashboard_Design.md` (the v2 specification written
2026-09-05 after the first build was judged a Tableau default): one dominant red
metric, KPI cards with a context line, a Z-layout at 1300 x 900, a neutral palette
with one accent and red reserved for a response window that has run out, no
gridlines, three parameter-driven filters, drill-down and cross-filter actions,
and a phone layout.

Schema provenance, because none of it was invented:

- The worksheet, KPI text-mark, palette, dashboard-zone, device-layout, action,
  reference-line, sort, filter and parameter structures were read out of
  `P3_Unicorn_SK_Draft_v2025.2.twbx`, a working 23-sheet workbook Tableau wrote
  at document version 18.1.
- The extract (`hyper`) connection form comes from the same workbook's extract
  block; the `textscan` form from this machine's Tableau logs.
- A categorical color map lives in the DATASOURCE style and names the field by
  its bare instance (`[none:Calculation_102:nk]`), never with the datasource
  prefix. The first build wrote the prefixed form and Tableau silently ignored
  it, which is why v1 shipped with one blue.

Colors are section 9 of `Dashboard_Design_v3.md`: one navy family plus one reserved
red. Priority is an ORDERED category, so its three levels are intensities of a
single hue rather than three unrelated ones, which is Few's rule for ordered
categories and is also what leaves red free to carry exactly one meaning. Red
appears in three places on the whole page - the OVERDUE card, the overdue segment
of an aging band, and a bullet bar past its tick - so if a viewer sees red, a
response window has run out. It is never a series colour and never a highlight.

The context ink moved from v2's `#6b6b66` to `#55555e` because the first measures
about 4.0:1 against the canvas and fails WCAG AA for body text; the replacement is
about 7.3:1.
"""

import argparse
import csv
import datetime
import os
import tempfile
import uuid
import zipfile
from collections import Counter
from pathlib import Path

from tableauhyperapi import (
    Connection,
    CreateMode,
    HyperProcess,
    Inserter,
    SqlType,
    TableDefinition,
    TableName,
    Telemetry,
)

# Paths
TABLEAU_DIR = Path(__file__).resolve().parent
EXTRACT_DIR = TABLEAU_DIR / "extracts"
OUTPUT = TABLEAU_DIR / "Arkon_Executive_View.twb"
OUTPUT_TWBX = TABLEAU_DIR / "Arkon_Executive_View.twbx"

# Palette, section 9 of Dashboard_Design_v3.md. One navy family plus one reserved
# red. Priority is an ORDERED category, so its levels are intensities of a single
# hue rather than three unrelated colours (Few); that is also what leaves red free
# to carry exactly one meaning on the whole page.
COLOR_CANVAS = "#F2F2EF"
COLOR_CARD = "#FFFFFF"
COLOR_INK = "#16161A"
# v2 used #6B6B66 here. Sergey read it as too light on the gray canvas and he was
# right: it measures about 4.0:1 against the canvas, which fails WCAG AA for body
# text. This is about 7.3:1.
COLOR_INK_SOFT = "#55555E"
COLOR_RULE = "#D8D8D2"

# Breach, and nothing else. If a viewer sees red anywhere on this dashboard, a
# response window has run out. Never a series colour, never a highlight.
COLOR_ALERT = "#C0392B"

# The ordered priority ramp. Every step is dark enough to carry a WHITE label,
# which is not a free choice: this is the one chart whose numbers sit inside the
# mark rather than past the end of it, so the segment colour and the label colour
# are one decision. The first ramp was picked for separation alone and its lightest
# step (#8AA6C8) measured about 2.3:1 against white, which is invisible. These are
# 11:1, 7.4:1 and 4.8:1, and the three steps still read as three.
COLOR_P1 = "#15304F"
COLOR_P2 = "#2B5180"
COLOR_P3 = "#46709E"
COLOR_P4 = "#5F86AF"

# Single-series bars take the darkest step of the ramp; card rules that are not
# shouting take the neutral rule colour.
COLOR_BAR = COLOR_P1
COLOR_NEUTRAL = COLOR_RULE

# A color map is honoured only when its encoding names a palette. Under the
# "Automatic" palette Tableau re-assigns colors on every open and the map is
# dead weight, which is why v1 and the first v2 build both came up blue and
# orange (Ben Moss, "How to encode 10,000 colours", 2017, confirmed here).
PALETTE_NAME = "Arkon status"

FONT_MEDIUM = "Tableau Medium"
FONT_BOLD = "Tableau Bold"
FONT_BOOK = "Tableau Book"

# The Tableau build this workbook was verified in. Document version stays 18.1,
# which is what both reference workbooks on this machine carry.
SOURCE_BUILD = "2026.2.0 (20262.26.0819.2015)"

DASHBOARD = "Arkon Executive View"
# 1600 x 900: a presentation screen rather than a laptop, which is what Sergey
# asked for and what buys the number grid of section 3.
DASH_W, DASH_H = 1600, 900
REPO_URL = "github.com/sergey-kasatov/arkon-manufacturing-ai"

# The bullet chart's fixed axis, in multiples of an incident's own window. Four
# puts the window tick at a quarter of the track, where it can be seen.
BULLET_CAP = 4.0

# How many rows the two bounded panels carry. Section 7 caps the bullet chart at
# twelve; the feed is the eight most recent transitions.
# 0.38 of the usable canvas. Stated in pixels because a layout-flow container
# ignores a proportional box: see the comment at the main row.
RIGHT_COLUMN = 600

BULLET_ROWS = 6

# Bar thickness. NOT a fraction of the row, which is the trap: Tableau's mark `size`
# runs to about 2.0, not to 1.0. Measured by dragging the Size slider to maximum on one
# sheet and diffing the save, which wrote `1.9890055656433105`. So the 0.62 this
# dashboard shipped with was about 31 percent of a row and the 0.88 that replaced it
# about 44 percent - both read as thin, and the "misaligned" value labels were a
# symptom of that rather than a placement bug: a 14 pt label beside a 5 px bar cannot
# look centred on it.
#
# 1.7 is about 85 percent of the row: thick enough to survive the compression of a
# shared screen, with a gap left between rows so the bars stay countable.
MARK_SIZE = "1.7"
FEED_ROWS = 6

# Sheet names, used by zones, windows and actions alike
S_KPI_OVERDUE = "KPI Overdue"
S_KPI_OPEN = "KPI Open"
S_KPI_ACK = "KPI Time to acknowledge"
S_KPI_CLOSE = "KPI Time to close"
S_AGING = "Open incidents by age"
S_TIME = "Time to acknowledge"
S_FEED = "Who acted, and when"
S_MODULES = "Incidents by model"
S_DRILL = "Incidents behind this bar"

# Deterministic ids, so the generator reproduces its own artifact
UUID_NS = uuid.UUID("6f2a7c14-0a1e-5f3b-9d47-2c9f1b4e88a0")


def stable_uuid(name):
    return "{%s}" % str(uuid.uuid5(UUID_NS, name)).upper()


def esc(text):
    """Escape a string for an XML attribute or text node, single quotes included."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("'", "&apos;")
        .replace('"', "&quot;")
    )


# Read the extracts and infer a Tableau type per column

BOOL_VALUES = {"TRUE", "FALSE"}

# Tableau local type -> the OLE DB remote-type code its metadata records carry
REMOTE_TYPE = {"string": 129, "integer": 20, "real": 5, "boolean": 11}

# Tableau's default aggregation per local type, as written in metadata records
DEFAULT_AGG = {"string": "Count", "integer": "Sum", "real": "Sum", "boolean": "Count"}

# Hyper column type per inferred local type
HYPER_TYPE = {
    "string": SqlType.text,
    "integer": SqlType.big_int,
    "real": SqlType.double,
    "boolean": SqlType.bool,
}


def to_hyper_value(value, datatype):
    """Convert one CSV cell to the Python value the Hyper inserter expects."""
    if value == "":
        return None
    if datatype == "boolean":
        return value == "TRUE"
    if datatype == "integer":
        return int(value)
    if datatype == "real":
        return float(value)
    return value


def infer_type(values):
    """Infer a Tableau datatype from the non-empty values of one CSV column.

    Timestamps stay strings on purpose: no sheet puts one on an axis, so typing
    them as text costs nothing and cannot silently null a column.
    """
    present = [v for v in values if v != ""]
    if not present:
        return "string"
    if all(v in BOOL_VALUES for v in present):
        return "boolean"
    try:
        for v in present:
            int(v)
        return "integer"
    except ValueError:
        pass
    try:
        for v in present:
            float(v)
        return "real"
    except ValueError:
        pass
    return "string"


def read_extract(filename):
    """Return the rows and the (column name, inferred type) pairs of one CSV."""
    path = EXTRACT_DIR / filename
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("%s is empty; run build_extracts.py first" % path)
    fields = list(rows[0].keys())
    return rows, [(f, infer_type([r[f] for r in rows])) for f in fields]


# Datasource construction


class Datasource:
    """One CSV wired as a Tableau federated text connection with a hyper extract."""

    def __init__(self, key, filename, caption):
        self.name = "federated.arkon%s" % key
        self.connection = "textscan.arkon%s" % key
        self.filename = filename
        self.stem = Path(filename).stem
        self.caption = caption
        self.rows, self.columns = read_extract(filename)
        self.hyper = EXTRACT_DIR / ("%s.hyper" % self.stem)
        self.calculations = []  # (name, caption, datatype, role, type, formula)
        self.captions = {}  # raw column -> caption shown on headers and axes
        self.palettes = []  # (bare field instance, [(hex, bucket), ...])
        self.palette_fields = []  # the Field objects behind them

    def add_calculation(self, name, caption, datatype, role, ctype, formula):
        self.calculations.append((name, caption, datatype, role, ctype, formula))

    def add_palette(self, field, mapping):
        """Register a categorical color map for `field` (a Field), bare instance."""
        self.palettes.append((field.instance, mapping))
        self.palette_fields.append(field)

    def type_of(self, column):
        for name, datatype in self.columns:
            if name == column:
                return datatype
        for name, _c, datatype, _r, _t, _f in self.calculations:
            if name == "[%s]" % column or name == column:
                return datatype
        raise KeyError("%s has no column %s" % (self.filename, column))

    def metadata_records(self, parent, indent):
        pad = " " * indent
        out = ["%s<metadata-records>" % pad]
        for ordinal, (name, datatype) in enumerate(self.columns):
            out.append("%s  <metadata-record class='column'>" % pad)
            out.append("%s    <remote-name>%s</remote-name>" % (pad, esc(name)))
            out.append("%s    <remote-type>%d</remote-type>" % (pad, REMOTE_TYPE[datatype]))
            out.append("%s    <local-name>[%s]</local-name>" % (pad, esc(name)))
            out.append("%s    <parent-name>%s</parent-name>" % (pad, esc(parent)))
            out.append("%s    <remote-alias>%s</remote-alias>" % (pad, esc(name)))
            out.append("%s    <ordinal>%d</ordinal>" % (pad, ordinal))
            out.append("%s    <local-type>%s</local-type>" % (pad, datatype))
            out.append("%s    <aggregation>%s</aggregation>" % (pad, DEFAULT_AGG[datatype]))
            out.append("%s    <contains-null>true</contains-null>" % pad)
            out.append("%s  </metadata-record>" % pad)
        out.append("%s</metadata-records>" % pad)
        return out

    def write_hyper(self, hyper):
        """Materialise this CSV as a single-table `.hyper` extract.

        Tableau Public will not open a workbook whose data source is a live
        connection ("Workbooks saved to Tableau Public must use extracts"). The
        table is `Extract.Extract`, the name Tableau itself uses.
        """
        if self.hyper.exists() and not os.access(self.hyper, os.W_OK):
            raise SystemExit(
                "%s is not writable. Close the workbook in Tableau first, or pass "
                "--skip-extracts." % self.hyper
            )
        table = TableDefinition(
            table_name=TableName("Extract", "Extract"),
            columns=[
                TableDefinition.Column(name, HYPER_TYPE[datatype]())
                for name, datatype in self.columns
            ],
        )
        with Connection(
            endpoint=hyper.endpoint,
            database=str(self.hyper),
            create_mode=CreateMode.CREATE_AND_REPLACE,
        ) as connection:
            connection.catalog.create_schema("Extract")
            connection.catalog.create_table(table)
            with Inserter(connection, table) as inserter:
                inserter.add_rows(
                    [to_hyper_value(row[name], datatype)
                     for name, datatype in self.columns]
                    for row in self.rows
                )
                inserter.execute()
        return len(self.rows)

    def extract_xml(self, update_time):
        # No `object-id`: it is only declared when the workbook opts into the
        # VConnDownstreamExtractsWithWarnings feature in its manifest.
        out = ["      <extract count='-1' enabled='true' units='records'>"]
        out.append(
            "        <connection authentication='auth-none' author-locale='en_US' "
            "class='hyper' dbname='%s' default-settings='hyper' schema='Extract' "
            "tablename='Extract' update-time='%s'>"
            % (esc(self.hyper.as_posix()), esc(update_time))
        )
        out.append("          <relation name='Extract' table='[Extract].[Extract]' type='table' />")
        out.extend(self.metadata_records("[Extract]", 10))
        out.append("        </connection>")
        out.append("      </extract>")
        return out

    def xml(self, update_time):
        out = []
        out.append(
            "    <datasource caption='%s' inline='true' name='%s' version='18.1'>"
            % (esc(self.caption), self.name)
        )
        out.append("      <connection class='federated'>")
        out.append("        <named-connections>")
        out.append(
            "          <named-connection caption='%s' name='%s'>"
            % (esc(self.stem), self.connection)
        )
        out.append(
            "            <connection class='textscan' directory='%s' filename='%s' "
            "is-single-table-union='yes' password='' server='' />"
            % (esc(EXTRACT_DIR.as_posix()), esc(self.filename))
        )
        out.append("          </named-connection>")
        out.append("        </named-connections>")
        out.append(
            "        <relation connection='%s' name='%s' table='[%s#csv]' type='table'>"
            % (self.connection, esc(self.filename), esc(self.stem))
        )
        out.append(
            "          <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>"
        )
        for ordinal, (name, datatype) in enumerate(self.columns):
            out.append(
                "            <column datatype='%s' name='%s' ordinal='%d' />"
                % (datatype, esc(name), ordinal)
            )
        out.append("          </columns>")
        out.append("        </relation>")
        out.extend(self.metadata_records("[%s#csv]" % self.stem, 8))
        out.append("      </connection>")
        out.append("      <aliases enabled='yes' />")
        for column, caption in sorted(self.captions.items()):
            datatype = self.type_of(column)
            role = "measure" if datatype in ("integer", "real") else "dimension"
            ctype = "quantitative" if role == "measure" else "nominal"
            out.append(
                "      <column caption='%s' datatype='%s' name='[%s]' role='%s' type='%s' />"
                % (esc(caption), datatype, esc(column), role, ctype)
            )
        for name, caption, datatype, role, ctype, formula in self.calculations:
            out.append(
                "      <column caption='%s' datatype='%s' name='%s' role='%s' type='%s'>"
                % (esc(caption), datatype, name, role, ctype)
            )
            out.append(
                "        <calculation class='tableau' formula='%s' />" % esc(formula)
            )
            out.append("      </column>")
        # A color map is honoured only if the instance it names is DECLARED at
        # datasource level, right here before the extract. Tableau writes exactly
        # this line when a color is assigned in Edit Colors; without it the map
        # below is parsed and ignored, which is why two builds came up blue.
        for field in self.palette_fields:
            out.append(
                "      <column-instance column='%s' derivation='%s' name='%s' "
                "pivot='key' type='%s' />"
                % (field.column, "User" if field.calculated else field.derivation,
                   field.instance, field.instance_type)
            )
        out.extend(self.extract_xml(update_time))
        # dim-percentage and measure-percentage are REQUIRED attributes here;
        # Tableau refuses the whole workbook without them.
        out.append(
            "      <layout dim-ordering='alphabetic' dim-percentage='0.5' "
            "measure-ordering='alphabetic' measure-percentage='0.4' "
            "show-structure='true' />"
        )
        if self.palettes:
            # The datasource style is where Tableau itself keeps categorical
            # color maps, and the field is the BARE instance name.
            out.append("      <style>")
            out.append("        <style-rule element='mark'>")
            for field, mapping in self.palettes:
                out.append(
                    "          <encoding attr='color' field='%s' palette='%s' type='palette'>"
                    % (field, PALETTE_NAME)
                )
                for color, bucket in mapping:
                    out.append("            <map to='%s'>" % color)
                    out.append("              <bucket>&quot;%s&quot;</bucket>" % esc(bucket))
                    out.append("            </map>")
                out.append("          </encoding>")
            out.append("        </style-rule>")
            out.append("      </style>")
        else:
            out.append("      <style />")
        out.append("    </datasource>")
        return out


class Parameter:
    """One string list parameter, a global filter control across datasources."""

    def __init__(self, name, caption, members):
        self.name = name  # "[Parameter 1]"
        self.caption = caption
        self.members = members  # the first member is the default

    @property
    def ref(self):
        return "[Parameters].%s" % self.name

    def column_lines(self, indent):
        pad = " " * indent
        out = [
            "%s<column caption='%s' datatype='string' name='%s' param-domain-type='list' "
            "role='measure' type='nominal' value='&quot;%s&quot;'>"
            % (pad, esc(self.caption), self.name, esc(self.members[0]))
        ]
        out.append(
            "%s  <calculation class='tableau' formula='&quot;%s&quot;' />"
            % (pad, esc(self.members[0]))
        )
        out.append("%s  <members>" % pad)
        for member in self.members:
            out.append("%s    <member value='&quot;%s&quot;' />" % (pad, esc(member)))
        out.append("%s  </members>" % pad)
        out.append("%s</column>" % pad)
        return out


def parameters_xml(params):
    out = [
        "    <datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>",
        "      <aliases enabled='yes' />",
    ]
    for param in params:
        out.extend(param.column_lines(6))
    out.append("    </datasource>")
    return out


# Column-instance helpers
#
# Tableau names an instance by its derivation and its role: `none:` for a raw
# dimension or a ROW-LEVEL calculation, `sum:` for a summed measure, `usr:` for
# an AGGREGATE calculation. The trailing `nk` / `qk` is nominal / quantitative.


def instance(column, derivation):
    bare = column.strip("[]")
    if derivation == "None":
        return "[none:%s:nk]" % bare, "nominal"
    if derivation == "Sum":
        return "[sum:%s:qk]" % bare, "quantitative"
    raise ValueError(derivation)


def user_instance(column, quantitative):
    bare = column.strip("[]")
    suffix = "qk" if quantitative else "nk"
    return "[usr:%s:%s]" % (bare, suffix)


class Field:
    """One field as a worksheet uses it: the base column plus its instance."""

    def __init__(self, ds, column, derivation, datatype, role, ctype, calculated=False):
        self.ds = ds
        self.column = column
        self.derivation = derivation
        self.datatype = datatype
        self.role = role
        self.ctype = ctype
        self.calculated = calculated
        if calculated:
            self.instance = user_instance(column, ctype == "quantitative")
            self.instance_type = ctype
        else:
            self.instance, self.instance_type = instance(column, derivation)

    @property
    def ref(self):
        return "[%s].%s" % (self.ds.name, self.instance)

    def dependency_lines(self):
        lines = [
            "            <column datatype='%s' name='%s' role='%s' type='%s' />"
            % (self.datatype, self.column, self.role, self.ctype)
        ]
        derivation = "User" if self.calculated else self.derivation
        lines.append(
            "            <column-instance column='%s' derivation='%s' name='%s' "
            "pivot='key' type='%s' />"
            % (self.column, derivation, self.instance, self.instance_type)
        )
        return lines


def dimension(ds, column):
    return Field(ds, "[%s]" % column, "None", ds.type_of(column), "dimension", "nominal")


def measure(ds, column):
    return Field(ds, "[%s]" % column, "Sum", ds.type_of(column), "measure", "quantitative")


def calc_measure(ds, column, datatype="integer"):
    """An AGGREGATE numeric calculation (COUNT, SUM, MEDIAN): `usr:...:qk`."""
    return Field(ds, column, "User", datatype, "measure", "quantitative", calculated=True)


def calc_string(ds, column):
    """An AGGREGATE string calculation: `usr:...:nk`, role measure, type nominal.

    That is the form Tableau writes for `IF SUM(...) ... THEN "a" ELSE "b" END`.
    """
    return Field(ds, column, "User", "string", "measure", "nominal", calculated=True)


def calc_dimension(ds, column, datatype="string"):
    """A ROW-LEVEL calculated dimension: `none:` with derivation `None`.

    Not `usr:`. Put a row-level `IF ... END` on `usr:` and the pill comes up red
    as `AGG(field)` and the sheet draws nothing.
    """
    return Field(ds, column, "None", datatype, "dimension", "nominal")


def calc_row_measure(ds, column, datatype="real"):
    """A ROW-LEVEL numeric calculation used as a measure: `sum:...:qk`.

    The counterpart of `calc_dimension` on the measure side. `calc_measure` is for
    a formula that is ITSELF an aggregate (COUNT, MEDIAN); this is for a per-row
    arithmetic result that the shelf then sums. On a view with one row per incident
    the sum is the value, and it is the form a reference line can average per cell,
    which `usr:` cannot.
    """
    return Field(ds, column, "Sum", datatype, "measure", "quantitative")


# Formatted text


def run_xml(text, attrs=None, raw=False):
    joined = "".join(" %s='%s'" % (k, esc(v)) for k, v in sorted((attrs or {}).items()))
    return "<run%s>%s</run>" % (joined, text if raw else esc(text))


def field_run(field, attrs=None):
    """A run that prints a field's value; the reference is wrapped in CDATA."""
    return run_xml("<![CDATA[<%s>]]>" % field.ref, attrs, raw=True)


# A paragraph break is the run `Æ&#10;` (U+00C6 followed by the entity), which is
# how Tableau itself serialises one. A run holding only `&#10;` is ignored.
NEWLINE = run_xml("\u00c6&#10;", None, raw=True)


def formatted_text(runs, indent):
    pad = " " * indent
    return [pad + "<formatted-text>"] + [pad + "  " + r for r in runs] + [pad + "</formatted-text>"]


def title_runs(title, subtitle=None):
    """Section 10: chart title 13 Medium on ink, its caption 11 Book on context."""
    runs = [run_xml(title, {"fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "15"})]
    if subtitle:
        runs.append(NEWLINE)
        runs.append(run_xml(subtitle, {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "13"}))
    return runs


def kpi_runs(label, number_field, context_field, alert=False):
    """The three lines of a KPI card: label, number, context.

    All three are LEFT-aligned, which is the point Sergey made most sharply and the
    one that separates a dashboard that looks designed from one that looks
    assembled. v2 centred them, and a centred number moves as its digit count
    changes, so a row of four centred BANs has no vertical line anywhere in it.

    Alignment is stated EXPLICITLY on every run including the paragraph breaks, and
    omitting it is not the same thing. Measured: with the attribute absent, Tableau
    aligned the two cards whose number is a numeric field to the RIGHT and the two
    whose number is a string to the left, so the row had two alignments in it. The
    default follows the field's datatype, not the page.

    One font size for all four numbers whatever their digits, so the row shares one
    baseline (section 3).
    """
    left = {"fontalignment": "0"}
    soft = dict(left, fontcolor=COLOR_INK_SOFT, fontname=FONT_MEDIUM, fontsize="11")
    number = dict(left, bold="true", fontcolor=COLOR_ALERT if alert else COLOR_INK,
                  fontname=FONT_BOLD, fontsize="38")
    context = dict(left, fontcolor=COLOR_INK_SOFT, fontname=FONT_BOOK, fontsize="13")
    left_newline = run_xml("Æ&#10;", left, raw=True)
    return [
        run_xml(label.upper(), soft), left_newline,
        field_run(number_field, number), left_newline,
        field_run(context_field, context),
    ]


# Worksheet construction


def shelf(fields):
    """Build a shelf expression: right-associative and parenthesised, as Tableau
    writes it. A bare concatenation parses as one malformed reference."""
    if not fields:
        return ""
    if len(fields) == 1:
        return fields[0].ref
    return "(%s / %s)" % (fields[0].ref, shelf(fields[1:]))


def worksheet(name, ds, params=(), title=None, subtitle=None, rows=(), cols=(), mark="Bar",
              color=None, mark_color=None, texts=(), lods=(), label_runs=None,
              tooltip_runs=None, filters=(), bool_filters=(), manual_sorts=(),
              shelf_sorts=(), reference_lines=(), hide_axes=(), gridlines_off=False,
              show_labels=False, label_font_size=None, mark_size=None, label_color=None):
    """Emit one worksheet.

    `filters` are (Field, [members]) keep-only categorical filters; `bool_filters`
    are boolean row-level calculations kept at `true`; `manual_sorts` are
    (Field, [ordered members]); `shelf_sorts` are (dimension, measure) descending;
    `reference_lines` are dicts with `axis` and `value` Fields (a per-cell average
    of `value` drawn on the `axis` measure); `hide_axes` are measure Fields whose
    axis is switched off because the marks carry their labels.
    """
    used = list(rows) + list(cols) + list(texts) + list(lods)
    if color is not None:
        used.append(color)
    used.extend(field for field, _members in filters)
    used.extend(bool_filters)
    used.extend(field for field, _order in manual_sorts)
    for dim, meas in shelf_sorts:
        used.extend([dim, meas])
    for line in reference_lines:
        used.extend([line["axis"], line["value"]])
    seen = set()
    unique = []
    for field in used:
        if field.instance not in seen:
            seen.add(field.instance)
            unique.append(field)

    out = ["    <worksheet name='%s'>" % esc(name)]
    if title:
        out.append("      <layout-options>")
        out.append("        <title>")
        out.extend(formatted_text(title_runs(title, subtitle), 10))
        out.append("        </title>")
        out.append("      </layout-options>")
    out.append("      <table>")
    out.append("        <view>")
    out.append("          <datasources>")
    out.append("            <datasource caption='%s' name='%s' />" % (esc(ds.caption), ds.name))
    if params:
        out.append("            <datasource name='Parameters' />")
    out.append("          </datasources>")
    if params:
        out.append("          <datasource-dependencies datasource='Parameters'>")
        for param in params:
            out.extend(param.column_lines(12))
        out.append("          </datasource-dependencies>")
    out.append("          <datasource-dependencies datasource='%s'>" % ds.name)
    for field in unique:
        out.extend(field.dependency_lines())
    out.append("          </datasource-dependencies>")
    slices = []
    for field, members in filters:
        out.append("          <filter class='categorical' column='%s'>" % field.ref)
        if len(members) == 1:
            out.append(
                "            <groupfilter function='member' level='%s' member='&quot;%s&quot;' "
                "user:ui-domain='database' user:ui-enumeration='inclusive' "
                "user:ui-marker='enumerate' />" % (field.instance, esc(members[0]))
            )
        else:
            out.append(
                "            <groupfilter function='union' user:ui-domain='database' "
                "user:ui-enumeration='inclusive' user:ui-marker='enumerate'>"
            )
            for member in members:
                out.append(
                    "              <groupfilter function='member' level='%s' "
                    "member='&quot;%s&quot;' />" % (field.instance, esc(member))
                )
            out.append("            </groupfilter>")
        out.append("          </filter>")
        slices.append(field.ref)
    for field in bool_filters:
        out.append("          <filter class='categorical' column='%s'>" % field.ref)
        out.append(
            "            <groupfilter function='member' level='%s' member='true' "
            "user:ui-domain='relevant' user:ui-enumeration='inclusive' "
            "user:ui-marker='enumerate' />" % field.instance
        )
        out.append("          </filter>")
        slices.append(field.ref)
    for field, order in manual_sorts:
        out.append("          <manual-sort column='%s' direction='ASC'>" % field.ref)
        out.append("            <dictionary>")
        for member in order:
            out.append("              <bucket>&quot;%s&quot;</bucket>" % esc(member))
        out.append("            </dictionary>")
        out.append("          </manual-sort>")
    if shelf_sorts:
        out.append("          <shelf-sorts>")
        for dim, meas in shelf_sorts:
            out.append(
                "            <shelf-sort-v2 dimension-to-sort='%s' direction='DESC' "
                "is-on-innermost-dimension='true' measure-to-sort-by='%s' shelf='rows' />"
                % (dim.ref, meas.ref)
            )
        out.append("          </shelf-sorts>")
    if slices:
        out.append("          <slices>")
        for column in slices:
            out.append("            <column>%s</column>" % column)
        out.append("          </slices>")
    out.append("          <aggregation value='true' />")
    out.append("        </view>")

    rules = []
    if gridlines_off:
        for element in ("gridline", "zeroline"):
            rules.append("          <style-rule element='%s'>" % element)
            rules.append("            <format attr='line-visibility' value='off' />")
            rules.append("          </style-rule>")
    if hide_axes:
        rules.append("          <style-rule element='axis'>")
        for field in hide_axes:
            rules.append(
                "            <format attr='display' class='0' field='%s' scope='cols' "
                "value='false' />" % field.ref
            )
        rules.append("          </style-rule>")
    if reference_lines:
        rules.append("          <style-rule element='refline'>")
        for index, _line in enumerate(reference_lines):
            rid = "refline%d" % index
            for attr, value in (
                ("fill-above", "#00000000"), ("fill-below", "#00000000"),
                ("line-visibility", "on"), ("stroke-size", "2"),
                ("stroke-color", "#ff1f1f1d"), ("vertical-align", "center"),
                ("text-align", "right"), ("font-size", "9"), ("font-family", FONT_BOOK),
            ):
                rules.append(
                    "            <format attr='%s' id='%s' value='%s' />" % (attr, rid, esc(value))
                )
        rules.append("          </style-rule>")
    if rules:
        out.append("        <style>")
        out.extend(rules)
        out.append("        </style>")
    else:
        out.append("        <style />")

    out.append("        <panes>")
    out.append("          <pane selection-relaxation-option='selection-relaxation-allow'>")
    out.append("            <view>")
    out.append("              <breakdown value='auto' />")
    out.append("            </view>")
    out.append("            <mark class='%s' />" % mark)
    encodings = []
    if color is not None:
        encodings.append("              <color column='%s' />" % color.ref)
    for field in lods:
        encodings.append("              <lod column='%s' />" % field.ref)
    for field in texts:
        encodings.append("              <text column='%s' />" % field.ref)
    if encodings:
        out.append("            <encodings>")
        out.extend(encodings)
        out.append("            </encodings>")
    for index, line in enumerate(reference_lines):
        out.append(
            # label-type is none, not value: on a ratio axis the tick printed
            # "1.0000" beside every row, which is the number the axis already
            # carries. Few's comparative measure is a mark, not an annotation.
            "            <reference-line axis-column='%s' enable-instant-analytics='false' "
            "formula='average' id='refline%d' label-type='none' probability='95' "
            "scope='per-cell' value-column='%s' z-order='%d' />"
            % (line["axis"].ref, index, line["value"].ref, index + 1)
        )
    # Tooltip BEFORE label, which is not the intuitive order and is not negotiable.
    # Tableau states the content model when it refuses the file:
    #   (view, mark, mark-sizing?, encodings?, label-data?, dropline?, trendline?,
    #    reference-line, customized-tooltip, customized-label, style)
    # v2 never hit this because no sheet carried both at once; the v3 bullet chart is
    # the first with a reference line, a custom label and a custom tooltip together.
    if tooltip_runs:
        out.append("            <customized-tooltip>")
        out.extend(formatted_text(tooltip_runs, 14))
        out.append("            </customized-tooltip>")
    if label_runs:
        out.append("            <customized-label>")
        out.extend(formatted_text(label_runs, 14))
        out.append("            </customized-label>")
    pane_rules = []
    if label_font_size:
        pane_rules.append("              <style-rule element='datalabel'>")
        # `auto` was not enough: it left dark ink on a navy segment, which is the one
        # place on this dashboard where the label sits INSIDE the mark rather than past
        # the end of it. Where a caller states a colour, state it.
        pane_rules.append("                <format attr='color-mode' value='auto' />")
        if label_color:
            pane_rules.append("                <format attr='color' value='%s' />" % label_color)
        pane_rules.append("                <format attr='font-family' value='%s' />" % FONT_BOOK)
        pane_rules.append("                <format attr='font-size' value='%s' />" % label_font_size)
        pane_rules.append("              </style-rule>")
    mark_rules = []
    if mark_color:
        mark_rules.append("                <format attr='mark-color' value='%s' />" % mark_color)
    if mark_size:
        mark_rules.append("                <format attr='size' value='%s' />" % mark_size)
    if show_labels:
        mark_rules.append("                <format attr='mark-labels-show' value='true' />")
        mark_rules.append("                <format attr='mark-labels-cull' value='false' />")
    if mark_rules:
        pane_rules.append("              <style-rule element='mark'>")
        pane_rules.extend(mark_rules)
        pane_rules.append("              </style-rule>")
    if pane_rules:
        out.append("            <style>")
        out.extend(pane_rules)
        out.append("            </style>")
    out.append("          </pane>")
    out.append("        </panes>")
    out.append("        <rows>%s</rows>" % shelf(rows) if rows else "        <rows />")
    out.append("        <cols>%s</cols>" % shelf(cols) if cols else "        <cols />")
    out.append("      </table>")
    out.append("      <simple-id uuid='%s' />" % stable_uuid(name))
    out.append("    </worksheet>")
    return out


def window(name, is_dashboard=False, sheets=()):
    out = []
    if is_dashboard:
        # `device-preview` must be left out even though Tableau's content model
        # lists it; `viewpoints` needs one entry per placed sheet.
        out.append("    <window class='dashboard' maximized='true' name='%s'>" % esc(name))
        out.append("      <viewpoints>")
        for sheet in sheets:
            out.append("        <viewpoint name='%s'>" % esc(sheet))
            out.append("          <zoom type='entire-view' />")
            out.append("        </viewpoint>")
        out.append("      </viewpoints>")
        out.append("      <active id='-1' />")
        out.append("      <simple-id uuid='%s' />" % stable_uuid("win:" + name))
        out.append("    </window>")
        return out
    out.append("    <window class='worksheet' name='%s'>" % esc(name))
    out.append("      <cards>")
    out.append("        <edge name='left'>")
    out.append("          <strip size='160'>")
    out.append("            <card type='pages' />")
    out.append("            <card type='filters' />")
    out.append("            <card type='marks' />")
    out.append("          </strip>")
    out.append("        </edge>")
    out.append("        <edge name='top'>")
    out.append("          <strip size='2147483647'>")
    out.append("            <card type='columns' />")
    out.append("          </strip>")
    out.append("          <strip size='2147483647'>")
    out.append("            <card type='rows' />")
    out.append("          </strip>")
    out.append("          <strip size='31'>")
    out.append("            <card type='title' />")
    out.append("          </strip>")
    out.append("        </edge>")
    out.append("      </cards>")
    # Fit: Entire View, and the dashboard's own <viewpoints> block above is NOT
    # enough on its own. Measured: with only the dashboard viewpoints every sheet
    # rendered at the default Standard fit, so seven model bars used 32 px of a
    # 140 px card and their row labels overlapped into an unreadable stack. The
    # setting that binds lives on the WORKSHEET's window, and this is the element
    # Tableau writes there when the toolbar dropdown is changed by hand - found by
    # setting it on one sheet in the application and diffing the saved file.
    out.append("      <viewpoint>")
    out.append("        <zoom type='entire-view' />")
    out.append("      </viewpoint>")
    out.append("      <simple-id uuid='%s' />" % stable_uuid("win:" + name))
    out.append("    </window>")
    return out


def action(number, caption, source_sheet, target, activation):
    """A dashboard action. `tsc:tsl-filter` with all fields is "use as filter".

    Activation is one of `on-select`, `on-hover` and `explicit`; the last is what
    the GUI calls "Menu" (a link in the tooltip). The enumeration was read out of
    `tabwbfileformat.dll`, because `on-menu` is what the name suggests and it is
    refused."""
    name = "[Action%d_%s]" % (number, uuid.uuid5(UUID_NS, "action:" + caption).hex.upper())
    return [
        "    <action caption='%s' name='%s'>" % (esc(caption), name),
        "      <activation auto-clear='true' type='%s' />" % activation,
        "      <source dashboard='%s' type='sheet' worksheet='%s' />" % (esc(DASHBOARD), esc(source_sheet)),
        "      <command command='tsc:tsl-filter'>",
        "        <param name='special-fields' value='all' />",
        "        <param name='target' value='%s' />" % esc(target),
        "      </command>",
        "    </action>",
    ]


# Dashboard zones
#
# The tree mirrors a dashboard Tableau itself wrote: a VERTICAL `layout-flow`
# root, horizontal `layout-flow` rows, every leaf with a `layout-cache`.
# Coordinates are absolute within the dashboard in a 0..100000 space on both
# axes. A zone that keeps its size in a flow carries `is-fixed` and a
# `fixed-size` in PIXELS along the flow's axis.


class Box:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h


def xs(px):
    return int(round(px / DASH_W * 100000))


def ys(px):
    return int(round(px / DASH_H * 100000))


def bands(heights_px, total=100000):
    """Stack full-width boxes top to bottom; the last one absorbs rounding."""
    out = []
    y_px = 0
    for index, height in enumerate(heights_px):
        y = ys(y_px)
        h = total - y if index == len(heights_px) - 1 else ys(height)
        out.append(Box(0, y, 100000, h))
        y_px += height
    return out


def split(box, weights):
    """Split a box left to right by weights; the last part absorbs rounding."""
    out = []
    x = box.x
    total = float(sum(weights))
    for index, weight in enumerate(weights):
        w = (box.x + box.w - x) if index == len(weights) - 1 else int(round(box.w * weight / total))
        out.append(Box(x, box.y, w, box.h))
        x += w
    return out


def zone_open(zone_id, box, extra):
    attrs = {"h": box.h, "id": zone_id, "w": box.w, "x": box.x, "y": box.y}
    attrs.update(extra)
    return "<zone %s>" % " ".join("%s='%s'" % (k, esc(v)) for k, v in sorted(attrs.items()))


def zone_style(margin=4, color=None, padding=None):
    out = [
        "<zone-style>",
        "  <format attr='border-color' value='#000000' />",
        "  <format attr='border-style' value='none' />",
        "  <format attr='border-width' value='0' />",
        "  <format attr='margin' value='%d' />" % margin,
    ]
    if padding is not None:
        out.append("  <format attr='padding' value='%d' />" % padding)
    if color:
        out.append("  <format attr='background-color' value='%s' />" % color)
    out.append("</zone-style>")
    return out


def fixed(px):
    return {"fixed-size": px, "is-fixed": "true"} if px else {}


def indent(lines, n=2):
    return [" " * n + line for line in lines]


def sheet_zone(zone_id, box, sheet, kpi=False, fixed_px=None, color=None, margin=4, padding=None):
    extra = {"name": sheet}
    if kpi:
        extra["show-title"] = "false"
    extra.update(fixed(fixed_px))
    if kpi:
        cache = "<layout-cache cell-count-h='1' cell-count-w='1' type-h='cell' type-w='cell' />"
    else:
        cache = "<layout-cache minheight='100' minwidth='100' type-h='scalable' type-w='scalable' />"
    return [zone_open(zone_id, box, extra), "  " + cache] + indent(zone_style(margin, color, padding)) + ["</zone>"]


def text_zone(zone_id, box, runs, fixed_px=None, color=None, margin=4, padding=None):
    extra = {"forceUpdate": "true", "type-v2": "text"}
    extra.update(fixed(fixed_px))
    return ([zone_open(zone_id, box, extra)] + formatted_text(runs, 2)
            + indent(zone_style(margin, color, padding)) + ["</zone>"])


def flow_zone(zone_id, box, direction, children, fixed_px=None, even=False, color=None,
              margin=4, padding=None):
    extra = {"param": direction, "type-v2": "layout-flow"}
    extra.update(fixed(fixed_px))
    if even:
        extra["layout-strategy-id"] = "distribute-evenly"
    out = [zone_open(zone_id, box, extra)]
    for child in children:
        out.extend(indent(child))
    out.extend(indent(zone_style(margin, color, padding)))
    out.append("</zone>")
    return out


def param_zone(zone_id, box, parameter, fixed_px=None):
    extra = {"mode": "dropdown", "param": parameter.ref, "type-v2": "paramctrl"}
    extra.update(fixed(fixed_px))
    return [zone_open(zone_id, box, extra)] + indent(zone_style(4)) + ["</zone>"]


# Facts read from the extracts at build time


def load_summary():
    with (EXTRACT_DIR / "store_summary.csv").open(encoding="utf-8", newline="") as handle:
        return next(csv.DictReader(handle))


def extract_update_time(summary):
    """Tableau's extract timestamp, taken from the store's own `as_of`."""
    stamp = datetime.datetime.strptime(summary["as_of"], "%Y-%m-%dT%H:%M:%S.%fZ")
    return stamp.strftime("%m/%d/%Y %I:%M:%S %p"), stamp.strftime("%d %b %Y %H:%M UTC")


def cross_check(incidents, summary):
    """The workbook recomputes its KPIs from the incident rows so they respond to
    the filters; this refuses to build if that recomputation disagrees with the
    summary the status API computed independently."""
    rows = incidents.rows
    recomputed = {
        "open_incidents": sum(r["is_open"] == "TRUE" for r in rows),
        "overdue_incidents": sum(r["overdue"] == "TRUE" for r in rows),
        "acknowledged_incidents": sum(r["minutes_to_acknowledge"] != "" for r in rows),
        "acknowledged_within_window": sum(
            r["minutes_to_acknowledge"] != "" and r["acknowledge_due_minutes"] != ""
            and float(r["minutes_to_acknowledge"]) <= float(r["acknowledge_due_minutes"])
            for r in rows
        ),
    }
    for key, value in recomputed.items():
        if int(summary[key]) != value:
            raise SystemExit(
                "incidents.csv gives %s = %d but store_summary.csv says %s; the extracts "
                "disagree with each other, rerun build_extracts.py" % (key, value, summary[key])
            )
    return recomputed


def acknowledge_windows(incidents):
    """The response windows the store actually carries, per priority, as text."""
    windows = {}
    for row in incidents.rows:
        if row["acknowledge_due_minutes"] != "":
            windows[row["priority"]] = int(float(row["acknowledge_due_minutes"]))
    parts = ["%d min %s" % (windows[p], p) for p in sorted(windows)]
    return "median, window " + " / ".join(parts) if parts else "no response windows recorded"


# Section 6. The bands open at the hour scale because this Steering Cell measures
# P1 in fifteen minutes; the ITSM convention of five-day buckets would collapse the
# whole live stream into one bar. Identical to AGE_BANDS in app/pages/00_executive.py,
# because two executive views of one plant must not band the same incident differently.
AGE_BANDS = [
    ("under 1 h", 0, 60),
    ("1 to 4 h", 60, 240),
    ("4 to 24 h", 240, 1440),
    ("1 to 3 d", 1440, 4320),
    ("over 3 d", 4320, float("inf")),
]


def band_of(minutes):
    for name, low, high in AGE_BANDS:
        if low <= minutes < high:
            return name
    return AGE_BANDS[-1][0]


def _number(row, key):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def status_sentence(incidents):
    """Section 5: one generated sentence, stating a relationship rather than a number.

    Deliberately a sentence and not a fifth KPI card. A card holds a number; what an
    executive wants first is what two numbers mean TOGETHER, and only prose can say
    that. Two clauses, the oldest open band and the freshest, collapsing to one when
    they would say the same thing twice.

    Mirrors `status_sentence` in app/pages/00_executive.py. The two surfaces are
    checked against each other by reading one number off each on the same minute, so
    the rule that produces this string has to be the same rule.
    """
    openi = [r for r in incidents.rows if r["is_open"] == "TRUE"]
    if not openi:
        return "Nothing is open. Every incident in the store has been closed or dismissed."

    by_band = {}
    for row in openi:
        by_band.setdefault(band_of(_number(row, "age_minutes") or 0.0), []).append(row)

    names = [n for n, _, _ in AGE_BANDS]
    oldest = next((n for n in reversed(names) if by_band.get(n)), None)
    newest = next((n for n in names if by_band.get(n)), None)
    old_group = by_band.get(oldest, [])
    never = [r for r in old_group if not r.get("acknowledged_at")]

    first = "%d of %d open incidents have been open %s%s." % (
        len(old_group), len(openi),
        "more than three days" if oldest == "over 3 d" else "for " + oldest,
        ", none of them ever acknowledged" if never and len(never) == len(old_group) else "",
    )
    if newest == oldest:
        return first

    fresh = by_band[newest]
    late = [r for r in fresh if r["overdue"] == "TRUE"]
    second = " The %d raised %s %s." % (
        len(fresh),
        "in the last hour" if newest == "under 1 h" else "in the last " + newest,
        "are being worked inside window" if not late
        else "include %d already past window" % len(late),
    )
    return first + second


def bullet_threshold(incidents, rows=BULLET_ROWS):
    """The cut that keeps the bullet chart to its `rows` slowest acknowledgements.

    Section 7 caps the chart at twelve rows, and Tableau expresses "top N" as either
    a table-calculation filter or a threshold. A threshold is used here for the same
    reason section 5's sentence is generated: this workbook ships WITH the extract it
    describes, so a number derived from that extract is exactly as fresh as the data
    beside it. Both are rebuilt by one command and neither can drift from the other.

    Returns None when the store holds fewer rows than the cap, in which case no
    filter is written at all rather than one that happens to keep everything.
    """
    values = sorted(
        (_number(r, "minutes_to_acknowledge") for r in incidents.rows
         if r["minutes_to_acknowledge"] != "" and r["acknowledge_due_minutes"] not in ("", "0")),
        reverse=True,
    )
    values = [v for v in values if v is not None]
    return values[rows - 1] if len(values) > rows else None


def feed_cutoff(transitions, rows=FEED_ROWS):
    """The recorded_at of the `rows`-th most recent transition, or None.

    The stamps are ISO-8601 UTC, which sorts lexicographically, so no parsing is
    needed and no timezone can get into the comparison.
    """
    stamps = sorted((r["recorded_at"] for r in transitions.rows if r["recorded_at"]), reverse=True)
    return stamps[rows - 1] if len(stamps) > rows else None


def build(skip_extracts=False, phone=True, actions=True):
    incidents = Datasource("incidents", "incidents.csv", "Arkon incidents")
    transitions = Datasource("transitions", "transitions.csv", "Arkon lifecycle transitions")
    summary = load_summary()
    facts = cross_check(incidents, summary)
    update_time, as_of_text = extract_update_time(summary)

    # Filters: three list parameters, members read from the data
    priorities = sorted({r["priority"] for r in incidents.rows})
    modules = sorted({r["source_module"] for r in incidents.rows})
    statuses = sorted({r["status"] for r in incidents.rows})
    p_priority = Parameter("[Parameter 1]", "Priority", ["All"] + priorities)
    p_module = Parameter("[Parameter 2]", "Model", ["All"] + modules)
    p_status = Parameter("[Parameter 3]", "Status", ["All"] + statuses)
    params = (p_priority, p_module, p_status)

    incidents.captions.update({
        "priority": "Priority", "source_module": "Model", "business_domain": "Domain",
        "incident_id": "Incident", "status": "Status", "assigned_to": "Assignee",
        "created_at": "Raised at", "summary": "Summary",
        "minutes_to_acknowledge": "Minutes to acknowledge",
        "acknowledge_due_minutes": "Window (minutes)",
    })
    transitions.captions.update({"to_status": "State"})

    # Calculations, incidents
    incidents.add_calculation(
        "[Calculation_101]", "Incidents", "integer", "measure", "quantitative",
        "COUNT([incident_id])",
    )
    incidents.add_calculation(
        "[Calculation_103]", "Open?", "string", "dimension", "nominal",
        'IF [is_open] THEN "Open" ELSE "Closed" END',
    )
    incidents.add_calculation(
        "[Calculation_106]", "Open incidents", "integer", "measure", "quantitative",
        "SUM(IF [is_open] THEN 1 ELSE 0 END)",
    )
    incidents.add_calculation(
        "[Calculation_108]", "Age (hours)", "string", "measure", "nominal",
        'STR(ROUND(SUM([age_minutes]) / 60, 1)) + " h"',
    )

    # Section 6: the age band, generated from AGE_BANDS so the workbook and the
    # cockpit page cannot band the same incident differently.
    band_formula = " ".join(
        '%s [age_minutes] < %d THEN "%s"' % ("IF" if i == 0 else "ELSEIF", high, name)
        for i, (name, _low, high) in enumerate(AGE_BANDS[:-1])
    ) + ' ELSE "%s" END' % AGE_BANDS[-1][0]
    incidents.add_calculation(
        "[Calculation_130]", "Age band", "string", "dimension", "nominal", band_formula,
    )

    # The stack of the aging chart, and the shape of this one line is the finding
    # that took three attempts. Colouring a band red only when EVERY incident in it
    # is past its window fails, because P3 carries no response window and can never
    # be overdue: a band holding 11 breaches beside a few P3 came out entirely navy.
    # Counting the overdue into their OWN segment cannot be defeated by a mixture -
    # the red is exactly as long as the number of breaches in that row.
    incidents.add_calculation(
        "[Calculation_131]", "Aging segment", "string", "dimension", "nominal",
        'IF [overdue] THEN "Overdue" ELSE [priority] END',
    )

    # Section 7, the bullet chart. The bar is the RATIO to each incident's own
    # window, never the raw minutes: this store holds acknowledgements from 0 to
    # about 9,000 minutes against windows of 15 and 60, so on a minutes axis a
    # 600-fold range puts every window tick within a pixel of the left edge and the
    # comparison Few designed the bullet graph to make disappears. On the ratio
    # scale the tick is always at 1.0, a quarter of the way along a fixed axis of 4.
    incidents.add_calculation(
        "[Calculation_140]", "Window", "real", "measure", "quantitative",
        "[acknowledge_due_minutes] / [acknowledge_due_minutes]",
    )
    incidents.add_calculation(
        "[Calculation_141]", "Acknowledge ratio", "real", "measure", "quantitative",
        "MIN([minutes_to_acknowledge] / [acknowledge_due_minutes], %.1f)" % BULLET_CAP,
    )
    incidents.add_calculation(
        "[Calculation_142]", "Acknowledge segment", "string", "dimension", "nominal",
        'IF [minutes_to_acknowledge] > [acknowledge_due_minutes] THEN "Late" ELSE [priority] END',
    )
    incidents.add_calculation(
        "[Calculation_143]", "Incident", "string", "dimension", "nominal",
        'REPLACE([incident_id], "ARK-INC-", "") + " / " + [priority]',
    )
    # P3 and P4 have no window, so they have no row. A zero would be a lie.
    incidents.add_calculation(
        "[Calculation_144]", "Has window", "boolean", "dimension", "nominal",
        "NOT ISNULL([minutes_to_acknowledge]) AND [acknowledge_due_minutes] > 0",
    )
    incidents.add_calculation(
        "[Calculation_145]", "Minutes to acknowledge", "string", "measure", "nominal",
        'IF SUM([minutes_to_acknowledge]) < 1 THEN "under 1 min" '
        'ELSE STR(INT(ROUND(SUM([minutes_to_acknowledge]), 0))) + " min" END',
    )
    # A bar that ran off the fixed axis says so, rather than looking like a bar that
    # merely reaches the end. The number column keeps the real figure either way, so
    # the cap costs resolution and never costs the fact.
    incidents.add_calculation(
        "[Calculation_146]", "Ratio to window", "string", "measure", "nominal",
        'IF SUM([minutes_to_acknowledge]) / SUM([acknowledge_due_minutes]) > %.1f '
        'THEN ">%dx" ELSE "" END' % (BULLET_CAP, BULLET_CAP),
    )
    incidents.add_calculation(
        "[Calculation_110]", "Priority filter", "boolean", "dimension", "nominal",
        '%s = "All" OR [priority] = %s' % (p_priority.ref, p_priority.ref),
    )
    incidents.add_calculation(
        "[Calculation_111]", "Model filter", "boolean", "dimension", "nominal",
        '%s = "All" OR [source_module] = %s' % (p_module.ref, p_module.ref),
    )
    incidents.add_calculation(
        "[Calculation_112]", "Status filter", "boolean", "dimension", "nominal",
        '%s = "All" OR [status] = %s' % (p_status.ref, p_status.ref),
    )
    incidents.add_calculation(
        "[Calculation_120]", "Overdue incidents", "integer", "measure", "quantitative",
        "SUM(IF [overdue] THEN 1 ELSE 0 END)",
    )
    incidents.add_calculation(
        "[Calculation_121]", "Overdue context", "string", "measure", "nominal",
        'IF [Calculation_106] > 0 THEN "of " + STR([Calculation_106]) + " open, " + '
        'STR(INT(ROUND([Calculation_120] / [Calculation_106] * 100))) + " percent" '
        'ELSE "no open incidents" END',
    )
    # Card 2, OPEN. Its context line carries what the number leaves out: how much
    # has come through the plant, and how much is sitting resolved but not closed.
    # `resolved` is deliberately NOT counted as open - the status API's own
    # open_incidents is new + acknowledged + in_containment, and a workbook that
    # defined it otherwise would disagree with the cockpit and the assistant, which
    # is worse than being slightly conservative. So it is surfaced here instead.
    incidents.add_calculation(
        "[Calculation_122]", "Closed or dismissed", "integer", "measure", "quantitative",
        'SUM(IF [status] = "closed" OR [status] = "false_positive" THEN 1 ELSE 0 END)',
    )
    incidents.add_calculation(
        "[Calculation_123]", "Resolved awaiting closure", "integer", "measure", "quantitative",
        'SUM(IF [status] = "resolved" THEN 1 ELSE 0 END)',
    )
    incidents.add_calculation(
        "[Calculation_124]", "Open context", "string", "measure", "nominal",
        'STR([Calculation_101]) + " raised, " + STR([Calculation_122]) + " closed"'
        ' + IF [Calculation_123] > 0 THEN ", " + STR([Calculation_123]) + '
        '" resolved" ELSE "" END',
    )
    # Cards 3 and 4 are MTTA and MTTR under their plant names, which is the pair the
    # incident-management field leads with (PagerDuty), beside the breach count and
    # the backlog that cards 1 and 2 carry.
    incidents.add_calculation(
        "[Calculation_125]", "Median minutes to acknowledge", "real", "measure", "quantitative",
        "MEDIAN([minutes_to_acknowledge])",
    )
    incidents.add_calculation(
        "[Calculation_126]", "Time to acknowledge", "string", "measure", "nominal",
        'IF ISNULL([Calculation_125]) THEN "none yet" ELSE '
        'STR(ROUND([Calculation_125], 1)) + " min" END',
    )
    incidents.add_calculation(
        "[Calculation_127]", "Response windows", "string", "measure", "nominal",
        'MAX("%s")' % acknowledge_windows(incidents),
    )
    incidents.add_calculation(
        "[Calculation_128]", "Median minutes to close", "real", "measure", "quantitative",
        "MEDIAN([minutes_to_close])",
    )
    incidents.add_calculation(
        "[Calculation_129]", "Time to close", "string", "measure", "nominal",
        'IF ISNULL([Calculation_128]) THEN "none yet" ELSE '
        'STR(ROUND([Calculation_128], 1)) + " min" END',
    )
    incidents.add_calculation(
        "[Calculation_133]", "Closed context", "string", "measure", "nominal",
        '"median over " + STR(SUM(IF ISNULL([minutes_to_close]) THEN 0 ELSE 1 END)) + " closed"',
    )

    # Section 7: keep the chart to its twelve slowest rows. See bullet_threshold().
    cut = bullet_threshold(incidents)
    if cut is not None:
        incidents.add_calculation(
            "[Calculation_147]", "Slowest acknowledgements", "boolean", "dimension", "nominal",
            "[minutes_to_acknowledge] >= %r" % cut,
        )

    # Calculations, transitions
    transitions.add_calculation(
        "[Calculation_301]", "Transitions", "integer", "measure", "quantitative",
        "COUNT([transition_id])",
    )
    transitions.add_calculation(
        "[Calculation_310]", "Priority filter", "boolean", "dimension", "nominal",
        '%s = "All" OR [priority] = %s' % (p_priority.ref, p_priority.ref),
    )
    transitions.add_calculation(
        "[Calculation_311]", "Model filter", "boolean", "dimension", "nominal",
        '%s = "All" OR [source_module] = %s' % (p_module.ref, p_module.ref),
    )
    # Section 8. This panel is the transition log, which is a real audit trail with
    # an actor and a timestamp on every row. It is NOT a notification log: whether a
    # Telegram card was delivered lives only in an n8n execution record and no store
    # holds it, so a panel headed "who was told" would be inferring from the rule
    # that P1 and P2 alert. This project does not put inferred facts on dashboards.
    transitions.add_calculation(
        "[Calculation_320]", "Move", "string", "measure", "nominal",
        'MAX([from_status] + " to " + [to_status])',
    )
    transitions.add_calculation(
        "[Calculation_321]", "Incident", "string", "dimension", "nominal",
        'REPLACE([incident_id], "ARK-INC-", "")',
    )
    since = feed_cutoff(transitions)
    if since is not None:
        transitions.add_calculation(
            "[Calculation_322]", "Recent", "boolean", "dimension", "nominal",
            '[recorded_at] >= "%s"' % since,
        )

    # Fields
    count = calc_measure(incidents, "[Calculation_101]")
    open_state = calc_dimension(incidents, "[Calculation_103]")
    open_count = calc_measure(incidents, "[Calculation_106]")
    age_hours = calc_string(incidents, "[Calculation_108]")
    inc_filters = [calc_dimension(incidents, "[Calculation_%d]" % n, "boolean") for n in (110, 111, 112)]
    overdue_count = calc_measure(incidents, "[Calculation_120]")
    overdue_context = calc_string(incidents, "[Calculation_121]")
    open_context = calc_string(incidents, "[Calculation_124]")
    mtta_text = calc_string(incidents, "[Calculation_126]")
    windows_text = calc_string(incidents, "[Calculation_127]")
    mttc_text = calc_string(incidents, "[Calculation_129]")
    closed_context = calc_string(incidents, "[Calculation_133]")
    age_band = calc_dimension(incidents, "[Calculation_130]")
    aging_segment = calc_dimension(incidents, "[Calculation_131]")
    window_line = calc_row_measure(incidents, "[Calculation_140]")
    ack_ratio = calc_row_measure(incidents, "[Calculation_141]")
    ack_segment = calc_dimension(incidents, "[Calculation_142]")
    ack_label = calc_dimension(incidents, "[Calculation_143]")
    has_window = calc_dimension(incidents, "[Calculation_144]", "boolean")
    minutes_text = calc_string(incidents, "[Calculation_145]")
    overflow_text = calc_string(incidents, "[Calculation_146]")
    slowest = (calc_dimension(incidents, "[Calculation_147]", "boolean")
               if cut is not None else None)
    priority = dimension(incidents, "priority")
    module = dimension(incidents, "source_module")
    domain = dimension(incidents, "business_domain")
    incident_id = dimension(incidents, "incident_id")
    status = dimension(incidents, "status")
    assignee = dimension(incidents, "assigned_to")
    created_local = dimension(incidents, "created_local")
    summary_text = dimension(incidents, "summary")
    minutes_to_ack = measure(incidents, "minutes_to_acknowledge")
    due_minutes = measure(incidents, "acknowledge_due_minutes")
    t_move = calc_string(transitions, "[Calculation_320]")
    t_incident = calc_dimension(transitions, "[Calculation_321]")
    t_actor = dimension(transitions, "actor")
    t_when = dimension(transitions, "recorded_local")
    t_recent = (calc_dimension(transitions, "[Calculation_322]", "boolean")
                if since is not None else None)
    t_filters = [calc_dimension(transitions, "[Calculation_%d]" % n, "boolean") for n in (310, 311)]

    # Section 9. Priority is an ORDERED category, so its levels are three intensities
    # of one navy; breach is the only other ink on the page and it is never a series
    # colour. Both stacks put the breach segment first so that the red always starts
    # at the axis, where its length is read against a common baseline.
    ramp = [(COLOR_P1, "P1"), (COLOR_P2, "P2"), (COLOR_P3, "P3"), (COLOR_P4, "P4")]
    incidents.add_palette(aging_segment, [(COLOR_ALERT, "Overdue")] + ramp)
    incidents.add_palette(ack_segment, [(COLOR_ALERT, "Late")] + ramp)

    # Extracts
    hyper_parameters = {"log_dir": tempfile.gettempdir()}
    if skip_extracts:
        for ds in (incidents, transitions):
            if not ds.hyper.exists():
                raise SystemExit("%s is missing; run without --skip-extracts" % ds.hyper)
        print("  extracts    : reused (--skip-extracts)")
    else:
        with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU,
                          parameters=hyper_parameters) as hyper:
            for ds in (incidents, transitions):
                print("  extract     : %s, %d rows" % (ds.hyper.name, ds.write_hyper(hyper)))

    soft = {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "11"}
    bold = {"bold": "true", "fontcolor": COLOR_INK, "fontname": FONT_BOOK, "fontsize": "11"}
    sheets = []

    # Section 4, the KPI row: four BANs, each three left-aligned lines. A BAN without
    # context is a number without a claim, so every card carries one. Card 1 is the
    # only one with red ink and the only one whose left rule is red, which is what
    # makes four identical objects read as one shouting and three answering.
    #
    # Every figure is recomputed from the incident rows rather than read off the
    # snapshot, so the cards follow the filters; cross_check() has already proved that
    # recomputation equals what the status API computed independently.
    sheets.append(worksheet(
        S_KPI_OVERDUE, incidents, params, mark="Text",
        texts=[overdue_count, overdue_context], bool_filters=inc_filters,
        label_runs=kpi_runs("Overdue", overdue_count, overdue_context, alert=True),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_OPEN, incidents, params, mark="Text",
        texts=[open_count, open_context], bool_filters=inc_filters,
        label_runs=kpi_runs("Open", open_count, open_context),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_ACK, incidents, params, mark="Text",
        texts=[mtta_text, windows_text], bool_filters=inc_filters,
        label_runs=kpi_runs("Time to acknowledge", mtta_text, windows_text),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_CLOSE, incidents, params, mark="Text",
        texts=[mttc_text, closed_context], bool_filters=inc_filters,
        label_runs=kpi_runs("Time to close", mttc_text, closed_context),
        show_labels=True,
    ))

    # Section 6, the dominant view. This is the chart neither v1 nor v2 had, and it
    # is where the store's bimodality shows: a live stream being worked inside window
    # beside an aged batch nobody ever touched. "26 open, 16 overdue" states a number;
    # an aging profile states what is wrong with the process.
    #
    # A SNAPSHOT and never a trend. The extracts hold current state only, so a trend
    # over them reconstructs today's backlog and calls it history - section 6 of the
    # specification, and the comment in build_extracts.py.
    band_order = [name for name, _low, _high in AGE_BANDS]
    sheets.append(worksheet(
        S_AGING, incidents, params,
        title="Where the backlog is",
        subtitle="Open incidents by age, stacked by priority. Red is the part already past "
                 "its response window.",
        rows=[age_band], cols=[count], mark="Bar",
        color=aging_segment,
        filters=[(open_state, ["Open"])], bool_filters=inc_filters,
        manual_sorts=[(age_band, band_order),
                      (aging_segment, ["P4", "P3", "P2", "P1", "Overdue"])],
        hide_axes=[count], gridlines_off=True, show_labels=True, label_font_size="14",
        mark_size=MARK_SIZE, label_color="#FFFFFF",
        tooltip_runs=[
            field_run(count, bold), run_xml(" open ", soft), field_run(aging_segment, bold),
            run_xml(" incidents, open ", soft), field_run(age_band, bold), run_xml(".", soft),
        ],
    ))

    # Section 7, the bullet chart. Few designed it to replace the gauges dashboards
    # accumulate: a featured measure, one comparative measure as a perpendicular tick,
    # and two qualitative ranges - inside the window and past it - encoded as
    # intensities of one hue rather than distinct ones, so the chart survives colour
    # blindness. The bar is the ratio to each incident's own window; see Calculation_141.
    bullet_filters = list(inc_filters) + [has_window] + ([slowest] if slowest else [])
    sheets.append(worksheet(
        S_TIME, incidents, params,
        title="How late is late",
        subtitle="As a multiple of the window that incident was allowed.",
        rows=[ack_label], cols=[ack_ratio], mark="Bar",
        # `window_line` is on Detail deliberately. A reference line whose value column
        # sits on no shelf is written into the file and silently not drawn: v2's tick
        # worked because its value field was already on Detail for the tooltip, and
        # this one had nothing else to put it there.
        color=ack_segment,
        lods=[priority, assignee, created_local, due_minutes, window_line],
        texts=[minutes_text, overflow_text],
        bool_filters=bullet_filters,
        shelf_sorts=[(ack_label, ack_ratio)],
        manual_sorts=[(ack_segment, ["P4", "P3", "P2", "P1", "Late"])],
        reference_lines=[{"axis": ack_ratio, "value": window_line}],
        gridlines_off=True, show_labels=True, label_font_size="14",
        mark_size=MARK_SIZE,
        label_runs=[field_run(minutes_text, bold), run_xml("  ", soft),
                    field_run(overflow_text, soft)],
        tooltip_runs=[
            field_run(ack_label, bold), run_xml(", raised ", soft),
            field_run(created_local, bold), run_xml(", acknowledged after ", soft),
            field_run(minutes_text, bold), run_xml(" against a ", soft),
            field_run(due_minutes, bold), run_xml(" minute window, by ", soft),
            field_run(assignee, bold), run_xml(".", soft),
        ],
    ))

    # Section 8, demoted to the strip: who acted, and when.
    feed_filters = list(t_filters) + ([t_recent] if t_recent else [])
    feed_order = []
    if t_recent is not None:
        seen_stamps = set()
        for row in sorted(transitions.rows, key=lambda r: r["recorded_at"], reverse=True):
            if row["recorded_at"] >= since and row["recorded_local"] not in seen_stamps:
                seen_stamps.add(row["recorded_local"])
                feed_order.append(row["recorded_local"])
    sheets.append(worksheet(
        S_FEED, transitions, params,
        title="Who acted, and when",
        subtitle="The %d most recent transitions, newest first, on the plant clock. "
                 "An audit trail, not a notification log." % FEED_ROWS,
        rows=[t_when, t_actor, t_incident], texts=[t_move], mark="Text",
        bool_filters=feed_filters,
        manual_sorts=[(t_when, feed_order)] if feed_order else (),
    ))

    sheets.append(worksheet(
        S_MODULES, incidents, params,
        title="Which models raise the work",
        subtitle="All incidents, one event per inspected object.",
        rows=[module], cols=[count], mark="Bar",
        mark_color=COLOR_BAR, lods=[domain], bool_filters=inc_filters,
        shelf_sorts=[(module, count)],
        hide_axes=[count], gridlines_off=True, show_labels=True, label_font_size="14",
        mark_size=MARK_SIZE,
        tooltip_runs=[
            field_run(module, bold), run_xml(" raised ", soft), field_run(count, bold),
            run_xml(" incidents in ", soft), field_run(domain, bold), run_xml(".", soft),
        ],
    ))

    # Drill-down, reached from the tooltip menu of the two bar charts
    sheets.append(worksheet(
        S_DRILL, incidents, params,
        title="Incidents behind this bar",
        subtitle="Filtered by the bar you came from. Age is hours since the incident was raised.",
        rows=[incident_id, priority, status, module, assignee, summary_text],
        texts=[age_hours], mark="Text", bool_filters=inc_filters,
    ))

    dashboard_sheets = [S_KPI_OVERDUE, S_KPI_OPEN, S_KPI_ACK, S_KPI_CLOSE,
                        S_AGING, S_TIME, S_FEED, S_MODULES]
    sheet_names = dashboard_sheets + [S_DRILL]

    # Section 3, the layout. White space is planned arithmetically rather than
    # nudged: the bands are pixel heights that MUST sum to DASH_H, because bands()
    # normalises whatever it is given, so a budget that does not add up rescales
    # every box silently. The assertion below is the guard.
    #
    # The specification's own arithmetic slipped here: it subtracts a gap and margin
    # budget from 984 and lands on 352 where the subtraction gives 316. The numbers
    # are therefore solved in code, and Dashboard_Design_v3.md is corrected to match
    # what this builds rather than the other way round.
    band_heights = [84, 44, 150, 330, 236, 56]
    if sum(band_heights) != DASH_H:
        raise SystemExit("the band budget is %d px and the canvas is %d px"
                         % (sum(band_heights), DASH_H))
    b_title, b_filters, b_kpi, b_main, b_detail, b_footer = bands(band_heights)

    heading = [
        run_xml("Arkon Quality Steering Cell",
                {"fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "22"}),
        run_xml("    Executive view",
                {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "22"}),
        NEWLINE,
        # Section 5: generated, not typed. A sentence states the relationship between
        # two numbers, which is the thing a fifth KPI card cannot do.
        run_xml(status_sentence(incidents),
                {"fontcolor": COLOR_INK, "fontname": FONT_BOOK, "fontsize": "13"}),
    ]
    stamp = [
        run_xml("as of %s" % summary["as_of_local"],
                {"fontalignment": "2", "fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "11"}),
        NEWLINE,
        run_xml("%s incidents, %s transitions, plant clock"
                % (summary["total_incidents"], summary["total_transitions"]),
                {"fontalignment": "2", "fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "11"}),
    ]
    footer = [
        run_xml("What this store is. ",
                {"bold": "true", "fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "11"}),
        run_xml("%s incidents raised by seven models on public datasets. Every timestamp is "
                "real. The operational context - people, lines, shifts - is simulated, and so "
                "are the response times: a demo crew inside the live plant acknowledges and "
                "closes on a schedule, so cards 3 and 4 measure that emitter, not a workforce. "
                "Source: the n8n incident status API. %s"
                % (summary["total_incidents"], REPO_URL),
                {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "11"}),
    ]

    t_left, t_right = split(b_title, [1120, 432])
    f_space, f1, f2, f3 = split(b_filters, [772, 240, 300, 240])
    cards = split(b_kpi, [1, 1, 1, 1])
    # 0.62 of the usable width, which puts the dominant chart on the left and gives
    # both rows the same vertical line down the page.
    m_left, m_right = split(b_main, [62, 38])
    d_left, d_right = split(b_detail, [62, 38])

    def card(container_id, stripe_id, sheet_id, box, sheet, stripe_color):
        stripe_box, sheet_box = split(box, [6, 382])
        return flow_zone(container_id, box, "horz", [
            text_zone(stripe_id, stripe_box, [run_xml(" ")], fixed_px=6, color=stripe_color, margin=0, padding=0),
            sheet_zone(sheet_id, sheet_box, sheet, kpi=True, margin=0, padding=10),
        ], color=COLOR_CARD, margin=8)

    zones = []
    zones.extend(flow_zone(12, b_title, "horz", [
        text_zone(13, t_left, heading),
        text_zone(14, t_right, stamp, fixed_px=432),
    ], fixed_px=84))
    zones.extend(flow_zone(15, b_filters, "horz", [
        text_zone(16, f_space, [run_xml(" ")]),
        param_zone(17, f1, p_priority, fixed_px=240),
        param_zone(18, f2, p_module, fixed_px=300),
        param_zone(19, f3, p_status, fixed_px=240),
    ], fixed_px=44))
    zones.extend(flow_zone(20, b_kpi, "horz", [
        card(21, 31, 41, cards[0], S_KPI_OVERDUE, COLOR_ALERT),
        card(22, 32, 42, cards[1], S_KPI_OPEN, COLOR_RULE),
        card(23, 33, 43, cards[2], S_KPI_ACK, COLOR_RULE),
        card(24, 34, 44, cards[3], S_KPI_CLOSE, COLOR_RULE),
    ], fixed_px=150, even=True))
    zones.extend(flow_zone(50, b_main, "horz", [
        sheet_zone(51, m_left, S_AGING, color=COLOR_CARD, margin=8, padding=10),
        sheet_zone(52, m_right, S_TIME, color=COLOR_CARD, margin=8, padding=10,
                   fixed_px=RIGHT_COLUMN),
    ]))
    zones.extend(flow_zone(60, b_detail, "horz", [
        sheet_zone(61, d_left, S_FEED, color=COLOR_CARD, margin=8, padding=10),
        sheet_zone(62, d_right, S_MODULES, color=COLOR_CARD, margin=8, padding=10,
                   fixed_px=RIGHT_COLUMN),
    ], fixed_px=236))
    zones.extend(text_zone(70, b_footer, footer, fixed_px=56))

    # Content model, as Tableau states it when it refuses a file:
    # ((layout-options? | repository-location?), style, size?, datasources,
    #  datasource-dependencies*, zones, devicelayouts, simple-id).
    dashboard = ["    <dashboard name='%s'>" % esc(DASHBOARD), "      <style />"]
    dashboard.append(
        "      <size maxheight='%d' maxwidth='%d' minheight='%d' minwidth='%d' />"
        % (DASH_H, DASH_W, DASH_H, DASH_W)
    )
    dashboard.append("      <datasources>")
    for ds in (incidents, transitions):
        dashboard.append("        <datasource caption='%s' name='%s' />" % (esc(ds.caption), ds.name))
    dashboard.append("        <datasource name='Parameters' />")
    dashboard.append("      </datasources>")
    dashboard.append("      <datasource-dependencies datasource='Parameters'>")
    for param in params:
        dashboard.extend(param.column_lines(8))
    dashboard.append("      </datasource-dependencies>")
    dashboard.append("      <zones>")
    dashboard.extend(indent(flow_zone(1, Box(0, 0, 100000, 100000), "vert", [zones],
                                      color=COLOR_CANVAS, margin=8), 8))
    dashboard.append("      </zones>")
    if phone:
        # Phone: title, the overdue card alone, the priority view, the other
        # three cards. The detail strip is desktop-only. Leaf zones keep their
        # desktop ids; the containers are the layout's own.
        # One card per row: a phone is too narrow for two three-line cards side
        # by side (the label of the narrower one came out as asterisks).
        p_title, p_overdue, p_priority_box, p_open, p_ack, p_median = bands([70, 110, 300, 90, 90, 90])
        phone_zones = [
            text_zone(13, p_title, heading, fixed_px=70, padding=0),
            sheet_zone(41, p_overdue, S_KPI_OVERDUE, kpi=True, fixed_px=110, color=COLOR_CARD, padding=0),
            sheet_zone(51, p_priority_box, S_AGING, fixed_px=300, color=COLOR_CARD, padding=0),
            sheet_zone(42, p_open, S_KPI_OPEN, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
            sheet_zone(43, p_ack, S_KPI_ACK, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
            sheet_zone(44, p_median, S_KPI_CLOSE, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
        ]
        dashboard.append("      <devicelayouts>")
        dashboard.append("        <devicelayout name='Phone'>")
        dashboard.append("          <size maxheight='800' minheight='800' sizing-mode='vscroll' />")
        dashboard.append("          <zones>")
        root = [zone_open(100, Box(0, 0, 100000, 100000), {"type-v2": "layout-basic"})]
        root.extend(indent(flow_zone(101, Box(0, 0, 100000, 100000), "vert", phone_zones,
                                     color=COLOR_CANVAS, margin=8)))
        root.extend(indent(zone_style(8)))
        root.append("</zone>")
        dashboard.extend(indent(root, 12))
        dashboard.append("          </zones>")
        dashboard.append("        </devicelayout>")
        dashboard.append("      </devicelayouts>")
    dashboard.append("      <simple-id uuid='%s' />" % stable_uuid(DASHBOARD))
    dashboard.append("    </dashboard>")

    action_lines = []
    if actions:
        action_lines.append("  <actions>")
        action_lines.extend(action(1, "Age selection filters the model view", S_AGING, S_MODULES, "on-select"))
        action_lines.extend(action(2, "Model selection filters the age view", S_MODULES, S_AGING, "on-select"))
        action_lines.extend(action(3, "Incidents behind this bar", S_AGING, S_DRILL, "explicit"))
        action_lines.extend(action(4, "Incidents behind this module", S_MODULES, S_DRILL, "explicit"))
        action_lines.append("  </actions>")

    out = []
    out.append("<?xml version='1.0' encoding='utf-8' ?>")
    out.append("")
    # `source-build` is a required attribute; without it Tableau refuses the file.
    out.append(
        "<workbook original-version='18.1' source-build='%s' source-platform='win' "
        "version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>" % SOURCE_BUILD
    )
    out.append("  <document-format-change-manifest>")
    # IntuitiveSorting is what admits `manual-sort` and `shelf-sorts` inside a
    # view; without it the 18.1 content model knows only `sort`.
    out.append("    <AnimationOnByDefault />")
    out.append("    <IntuitiveSorting />")
    out.append("    <IntuitiveSorting_SP2 />")
    out.append("    <SortTagCleanup />")
    out.append("    <MarkAnimation />")
    out.append("    <SheetIdentifierTracking />")
    out.append("    <WindowsPersistSimpleIdentifiers />")
    out.append("    <WorksheetBackgroundTransparency />")
    out.append("    <ZoneBackgroundTransparency />")
    out.append("  </document-format-change-manifest>")
    # The named palette is embedded, which is what Tableau does on save, so the
    # published workbook does not depend on a Preferences.tps on any machine.
    out.append("  <preferences>")
    out.append("    <color-palette custom='true' name='%s' type='regular'>" % PALETTE_NAME)
    for color in (COLOR_ALERT, COLOR_P1, COLOR_P2, COLOR_P3, COLOR_P4):
        out.append("      <color>%s</color>" % color)
    out.append("    </color-palette>")
    out.append("  </preferences>")
    out.append("  <datasources>")
    out.extend(parameters_xml(params))
    for ds in (incidents, transitions):
        out.extend(ds.xml(update_time))
    out.append("  </datasources>")
    out.extend(action_lines)
    out.append("  <worksheets>")
    for sheet in sheets:
        out.extend(sheet)
    out.append("  </worksheets>")
    out.append("  <dashboards>")
    out.extend(dashboard)
    out.append("  </dashboards>")
    out.append("  <windows>")
    out.extend(window(DASHBOARD, is_dashboard=True, sheets=dashboard_sheets))
    for name in sheet_names:
        out.extend(window(name))
    out.append("  </windows>")
    out.append("</workbook>")

    text = "\n".join(out) + "\n"
    OUTPUT.write_text(text, encoding="utf-8")
    print("wrote %s" % OUTPUT)
    print("  worksheets  : %d (%d on the dashboard)" % (len(sheet_names), len(dashboard_sheets)))
    print("  dashboard   : %s, %d x %d%s" % (DASHBOARD, DASH_W, DASH_H, ", phone layout" if phone else ""))
    print("  facts       : open %d, overdue %d, acknowledged %d (%d in window), as of %s" % (
        facts["open_incidents"], facts["overdue_incidents"], facts["acknowledged_incidents"],
        facts["acknowledged_within_window"], as_of_text))

    # Packaged copy: each extract's dbname turns from the absolute path into
    # Data/Extracts/<file>; every replacement is counted. Not byte-reproducible,
    # because Hyper stamps its files.
    packaged = text
    for ds in (incidents, transitions):
        absolute = "dbname='%s'" % esc(ds.hyper.as_posix())
        relative = "dbname='Data/Extracts/%s'" % esc(ds.hyper.name)
        if packaged.count(absolute) != 1:
            raise SystemExit("expected exactly one %s in the workbook" % absolute)
        packaged = packaged.replace(absolute, relative)
    with zipfile.ZipFile(OUTPUT_TWBX, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(OUTPUT.name, packaged)
        for ds in (incidents, transitions):
            archive.write(ds.hyper, "Data/Extracts/%s" % ds.hyper.name)
    print("wrote %s" % OUTPUT_TWBX)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--skip-extracts", action="store_true",
                        help="reuse the .hyper files in tableau/extracts/ instead of rewriting them")
    parser.add_argument("--no-phone", action="store_true", help="omit the phone device layout")
    parser.add_argument("--no-actions", action="store_true", help="omit the dashboard actions")
    args = parser.parse_args()
    build(skip_extracts=args.skip_extracts, phone=not args.no_phone, actions=not args.no_actions)
