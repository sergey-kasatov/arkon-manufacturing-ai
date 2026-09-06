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

Colors come from the `dataviz` skill's reference palette and were checked with its
validator rather than by eye: critical `#d03b3b` for a window that has run out,
neutral `#898781` for the rest of a status pair, and one accent blue `#2a78d6`
for bars that carry no state. The gray is deliberately gray (the validator's
chroma floor flags it, as it flags every neutral): an untouched incident that is
merely still inside its window is not a good outcome and must not be painted as
one.
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

# Palette (dataviz reference palette; see the module docstring)
COLOR_BAR = "#2a78d6"
COLOR_ALERT = "#d03b3b"
COLOR_NEUTRAL = "#898781"
COLOR_CANVAS = "#f5f5f3"
COLOR_CARD = "#ffffff"
COLOR_INK = "#1f1f1d"
COLOR_INK_SOFT = "#6b6b66"

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
DASH_W, DASH_H = 1300, 900
REPO_URL = "github.com/sergey-kasatov/arkon-manufacturing-ai"

# Sheet names, used by zones, windows and actions alike
S_KPI_OVERDUE = "KPI Overdue"
S_KPI_OPEN = "KPI Open"
S_KPI_ACK = "KPI Acknowledged in window"
S_KPI_MEDIAN = "KPI Median time to acknowledge"
S_PRIORITY = "Open incidents by priority"
S_TIME = "Time to acknowledge"
S_MODULES = "Incidents by module"
S_TRANSITIONS = "Lifecycle transitions"
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
    runs = [run_xml(title, {"fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "12"})]
    if subtitle:
        runs.append(NEWLINE)
        runs.append(run_xml(subtitle, {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "9"}))
    return runs


def kpi_runs(label, number_field, context_field, alert=False):
    """The three lines of a KPI card: label, number, context."""
    soft = {"fontalignment": "1", "fontcolor": COLOR_INK_SOFT, "fontname": FONT_MEDIUM, "fontsize": "9"}
    number = {"bold": "true", "fontalignment": "1", "fontcolor": COLOR_ALERT if alert else COLOR_INK,
              "fontname": FONT_BOLD, "fontsize": "30"}
    context = {"fontalignment": "1", "fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "10"}
    center_newline = run_xml("\u00c6&#10;", {"fontalignment": "1"}, raw=True)
    return [
        run_xml(label, soft), center_newline,
        field_run(number_field, number), center_newline,
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
              show_labels=False, label_font_size=None, mark_size=None):
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
            "            <reference-line axis-column='%s' enable-instant-analytics='false' "
            "formula='average' id='refline%d' label-type='value' probability='95' "
            "scope='per-cell' value-column='%s' z-order='%d' />"
            % (line["axis"].ref, index, line["value"].ref, index + 1)
        )
    if label_runs:
        out.append("            <customized-label>")
        out.extend(formatted_text(label_runs, 14))
        out.append("            </customized-label>")
    if tooltip_runs:
        out.append("            <customized-tooltip>")
        out.extend(formatted_text(tooltip_runs, 14))
        out.append("            </customized-tooltip>")
    pane_rules = []
    if label_font_size:
        pane_rules.append("              <style-rule element='datalabel'>")
        pane_rules.append("                <format attr='color-mode' value='auto' />")
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
    return "windows: " + ", ".join(parts) if parts else "no response windows recorded"


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
        "[Calculation_102]", "Response state", "string", "dimension", "nominal",
        'IF [overdue] THEN "Overdue" ELSE "Within window" END',
    )
    incidents.add_calculation(
        "[Calculation_103]", "Open?", "string", "dimension", "nominal",
        'IF [is_open] THEN "Open" ELSE "Closed" END',
    )
    incidents.add_calculation(
        "[Calculation_104]", "Has acknowledge time", "string", "dimension", "nominal",
        'IF ISNULL([minutes_to_acknowledge]) THEN "no" ELSE "yes" END',
    )
    incidents.add_calculation(
        "[Calculation_105]", "Acknowledge state", "string", "dimension", "nominal",
        'IF [minutes_to_acknowledge] > [acknowledge_due_minutes] THEN "Late" ELSE "In window" END',
    )
    incidents.add_calculation(
        "[Calculation_106]", "Open incidents", "integer", "measure", "quantitative",
        "SUM(IF [is_open] THEN 1 ELSE 0 END)",
    )
    incidents.add_calculation(
        "[Calculation_107]", "Open by priority", "string", "measure", "nominal",
        " + ".join(
            'STR(SUM(IF [is_open] AND [priority] = "%s" THEN 1 ELSE 0 END)) + " %s%s"'
            % (p, p, "" if i == len(priorities) - 1 else ", ")
            for i, p in enumerate(priorities)
        ),
    )
    incidents.add_calculation(
        "[Calculation_108]", "Age (hours)", "string", "measure", "nominal",
        'STR(ROUND(SUM([age_minutes]) / 60, 1)) + " h"',
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
    incidents.add_calculation(
        "[Calculation_122]", "Acknowledged incidents", "integer", "measure", "quantitative",
        "SUM(IF ISNULL([minutes_to_acknowledge]) THEN 0 ELSE 1 END)",
    )
    incidents.add_calculation(
        "[Calculation_123]", "Acknowledged within window", "integer", "measure", "quantitative",
        "SUM(IF [minutes_to_acknowledge] <= [acknowledge_due_minutes] THEN 1 ELSE 0 END)",
    )
    incidents.add_calculation(
        "[Calculation_124]", "Acknowledged context", "string", "measure", "nominal",
        '"of " + STR([Calculation_122]) + " acknowledged, " + '
        'STR([Calculation_122] - [Calculation_123]) + " late"',
    )
    incidents.add_calculation(
        "[Calculation_125]", "Median minutes to acknowledge", "real", "measure", "quantitative",
        "MEDIAN([minutes_to_acknowledge])",
    )
    incidents.add_calculation(
        "[Calculation_126]", "Median hours to acknowledge", "string", "measure", "nominal",
        'IF ISNULL([Calculation_125]) THEN "none yet" ELSE '
        'STR(ROUND([Calculation_125] / 60, 1)) + " h" END',
    )
    incidents.add_calculation(
        "[Calculation_127]", "Response windows", "string", "measure", "nominal",
        'MAX("%s")' % acknowledge_windows(incidents),
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

    # Fields
    count = calc_measure(incidents, "[Calculation_101]")
    response_state = calc_dimension(incidents, "[Calculation_102]")
    open_state = calc_dimension(incidents, "[Calculation_103]")
    has_ack = calc_dimension(incidents, "[Calculation_104]")
    ack_state = calc_dimension(incidents, "[Calculation_105]")
    open_count = calc_measure(incidents, "[Calculation_106]")
    open_by_priority = calc_string(incidents, "[Calculation_107]")
    age_hours = calc_string(incidents, "[Calculation_108]")
    inc_filters = [calc_dimension(incidents, "[Calculation_%d]" % n, "boolean") for n in (110, 111, 112)]
    overdue_count = calc_measure(incidents, "[Calculation_120]")
    overdue_context = calc_string(incidents, "[Calculation_121]")
    ack_in_window = calc_measure(incidents, "[Calculation_123]")
    ack_context = calc_string(incidents, "[Calculation_124]")
    median_text = calc_string(incidents, "[Calculation_126]")
    windows_text = calc_string(incidents, "[Calculation_127]")
    priority = dimension(incidents, "priority")
    module = dimension(incidents, "source_module")
    domain = dimension(incidents, "business_domain")
    incident_id = dimension(incidents, "incident_id")
    status = dimension(incidents, "status")
    assignee = dimension(incidents, "assigned_to")
    created_at = dimension(incidents, "created_at")
    summary_text = dimension(incidents, "summary")
    minutes_to_ack = measure(incidents, "minutes_to_acknowledge")
    due_minutes = measure(incidents, "acknowledge_due_minutes")
    t_count = calc_measure(transitions, "[Calculation_301]")
    t_to = dimension(transitions, "to_status")
    t_filters = [calc_dimension(transitions, "[Calculation_%d]" % n, "boolean") for n in (310, 311)]

    # Color maps: red only where a response window has run out
    incidents.add_palette(response_state, [(COLOR_ALERT, "Overdue"), (COLOR_NEUTRAL, "Within window")])
    incidents.add_palette(ack_state, [(COLOR_ALERT, "Late"), (COLOR_NEUTRAL, "In window")])

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

    soft = {"fontcolor": COLOR_INK_SOFT}
    bold = {"bold": "true", "fontcolor": COLOR_INK}
    sheets = []

    # KPI cards: label, number, context. Recomputed from the rows so the cards
    # follow the filters; cross_check() has already proved they equal the API.
    sheets.append(worksheet(
        S_KPI_OVERDUE, incidents, params, mark="Text",
        texts=[overdue_count, overdue_context], bool_filters=inc_filters,
        label_runs=kpi_runs("OVERDUE", overdue_count, overdue_context, alert=True),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_OPEN, incidents, params, mark="Text",
        texts=[open_count, open_by_priority], bool_filters=inc_filters,
        label_runs=kpi_runs("OPEN INCIDENTS", open_count, open_by_priority),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_ACK, incidents, params, mark="Text",
        texts=[ack_in_window, ack_context], bool_filters=inc_filters,
        label_runs=kpi_runs("ACKNOWLEDGED IN WINDOW", ack_in_window, ack_context),
        show_labels=True,
    ))
    sheets.append(worksheet(
        S_KPI_MEDIAN, incidents, params, mark="Text",
        texts=[median_text, windows_text], bool_filters=inc_filters,
        label_runs=kpi_runs("MEDIAN TIME TO ACKNOWLEDGE", median_text, windows_text),
        show_labels=True,
    ))

    # Main view: open incidents by priority, red where the window has run out
    sheets.append(worksheet(
        S_PRIORITY, incidents, params,
        title="Open incidents by priority",
        subtitle="Red bars are past their response window. Click a bar to filter the module "
                 "view; the tooltip menu opens the incidents behind it.",
        rows=[priority, response_state], cols=[count], mark="Bar",
        color=response_state,
        filters=[(open_state, ["Open"])], bool_filters=inc_filters,
        manual_sorts=[(response_state, ["Overdue", "Within window"])],
        hide_axes=[count], gridlines_off=True, show_labels=True, label_font_size="10",
        mark_size="0.55",
        tooltip_runs=[
            field_run(count, bold), run_xml(" open incidents at ", soft), field_run(priority, bold),
            run_xml(", ", soft), field_run(response_state, bold), run_xml(".", soft),
        ],
    ))

    # Time to acknowledge against the allowed window, per acknowledged incident
    sheets.append(worksheet(
        S_TIME, incidents, params,
        title="Time to acknowledge",
        subtitle="Minutes from raise to acknowledgement, one bar per acknowledged incident. "
                 "The tick is the window the SOP allows; red means it was missed.",
        rows=[incident_id], cols=[minutes_to_ack], mark="Bar",
        color=ack_state, lods=[due_minutes, priority, assignee, created_at],
        filters=[(has_ack, ["yes"])], bool_filters=inc_filters,
        reference_lines=[{"axis": minutes_to_ack, "value": due_minutes}],
        gridlines_off=True, show_labels=True, label_font_size="10", mark_size="0.6",
        tooltip_runs=[
            field_run(incident_id, bold), run_xml(", ", soft), field_run(priority, bold),
            run_xml(", raised ", soft), field_run(created_at, bold),
            run_xml(": acknowledged after ", soft), field_run(minutes_to_ack, bold),
            run_xml(" minutes against a ", soft), field_run(due_minutes, bold),
            run_xml(" minute window, ", soft), field_run(assignee, bold), run_xml(".", soft),
        ],
    ))

    # Detail strip: composition by module, and what the lifecycle has recorded
    sheets.append(worksheet(
        S_MODULES, incidents, params,
        title="Incidents by module",
        subtitle="All incidents, one event per inspected object, except nhtsa_nlp whose "
                 "events are already trends over an aggregate. Click a bar to filter by module.",
        rows=[module], cols=[count], mark="Bar",
        mark_color=COLOR_BAR, lods=[domain], bool_filters=inc_filters,
        shelf_sorts=[(module, count)],
        hide_axes=[count], gridlines_off=True, show_labels=True, label_font_size="10",
        tooltip_runs=[
            field_run(module, bold), run_xml(" raised ", soft), field_run(count, bold),
            run_xml(" incidents in ", soft), field_run(domain, bold), run_xml(".", soft),
        ],
    ))
    sheets.append(worksheet(
        S_TRANSITIONS, transitions, params,
        title="Lifecycle transitions",
        subtitle="Recorded transitions by destination state. One incident was driven back from "
                 "resolved to containment on purpose, which is why the count exceeds the incidents that moved.",
        rows=[t_to], cols=[t_count], mark="Bar",
        mark_color=COLOR_BAR, bool_filters=t_filters,
        shelf_sorts=[(t_to, t_count)],
        hide_axes=[t_count], gridlines_off=True, show_labels=True, label_font_size="10",
        tooltip_runs=[
            field_run(t_count, bold), run_xml(" transitions ended in ", soft),
            field_run(t_to, bold), run_xml(".", soft),
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

    dashboard_sheets = [S_KPI_OVERDUE, S_KPI_OPEN, S_KPI_ACK, S_KPI_MEDIAN,
                        S_PRIORITY, S_TIME, S_MODULES, S_TRANSITIONS]
    sheet_names = dashboard_sheets + [S_DRILL]

    # Dashboard layout: six bands in pixels, Z reading order
    b_title, b_filters, b_kpi, b_main, b_detail, b_footer = bands([76, 60, 130, 364, 220, 50])

    heading = [
        run_xml("Arkon Quality Steering Cell", {"fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "20"}),
        run_xml("   Executive view", {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "20"}),
        NEWLINE,
        run_xml("Are we on top of the open incidents? Seven models raise them; red always means "
                "a response window has run out.",
                {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "10"}),
    ]
    stamp = [
        run_xml("as of %s" % as_of_text,
                {"fontalignment": "2", "fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "10"}),
        NEWLINE,
        run_xml("status API extract: %s incidents, %s transitions" % (summary["total_incidents"], summary["total_transitions"]),
                {"fontalignment": "2", "fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "9"}),
    ]
    footer = [
        run_xml("What this store is. ", {"bold": "true", "fontcolor": COLOR_INK, "fontname": FONT_MEDIUM, "fontsize": "9"}),
        run_xml("%s incidents raised over deliberately small demo slices, so every rate here is a rate "
                "over a sample chosen to be small; the response times are real measurements of real delays. "
                "Source: the n8n incident status API, refreshed by tableau/build_extracts.py. Repository: %s"
                % (summary["total_incidents"], REPO_URL),
                {"fontcolor": COLOR_INK_SOFT, "fontname": FONT_BOOK, "fontsize": "9"}),
    ]

    t_left, t_right = split(b_title, [900, 400])
    f_space, f1, f2, f3 = split(b_filters, [640, 200, 260, 200])
    cards = split(b_kpi, [1, 1, 1, 1])
    m_left, m_right = split(b_main, [780, 520])
    d_left, d_right = split(b_detail, [780, 520])

    def card(container_id, stripe_id, sheet_id, box, sheet, stripe_color):
        stripe_box, sheet_box = split(box, [6, 319])
        return flow_zone(container_id, box, "horz", [
            text_zone(stripe_id, stripe_box, [run_xml(" ")], fixed_px=6, color=stripe_color, margin=0, padding=0),
            sheet_zone(sheet_id, sheet_box, sheet, kpi=True, margin=0, padding=8),
        ], color=COLOR_CARD, margin=6)

    zones = []
    zones.extend(flow_zone(12, b_title, "horz", [
        text_zone(13, t_left, heading),
        text_zone(14, t_right, stamp, fixed_px=400),
    ], fixed_px=76))
    zones.extend(flow_zone(15, b_filters, "horz", [
        text_zone(16, f_space, [run_xml(" ")]),
        param_zone(17, f1, p_priority, fixed_px=200),
        param_zone(18, f2, p_module, fixed_px=260),
        param_zone(19, f3, p_status, fixed_px=200),
    ], fixed_px=60))
    zones.extend(flow_zone(20, b_kpi, "horz", [
        card(21, 31, 41, cards[0], S_KPI_OVERDUE, COLOR_ALERT),
        card(22, 32, 42, cards[1], S_KPI_OPEN, COLOR_NEUTRAL),
        card(23, 33, 43, cards[2], S_KPI_ACK, COLOR_NEUTRAL),
        card(24, 34, 44, cards[3], S_KPI_MEDIAN, COLOR_NEUTRAL),
    ], fixed_px=130, even=True))
    zones.extend(flow_zone(50, b_main, "horz", [
        sheet_zone(51, m_left, S_PRIORITY, color=COLOR_CARD, margin=6, padding=8),
        sheet_zone(52, m_right, S_TIME, color=COLOR_CARD, margin=6, padding=8),
    ]))
    zones.extend(flow_zone(60, b_detail, "horz", [
        sheet_zone(61, d_left, S_MODULES, color=COLOR_CARD, margin=6, padding=8),
        sheet_zone(62, d_right, S_TRANSITIONS, color=COLOR_CARD, margin=6, padding=8),
    ], fixed_px=220))
    zones.extend(text_zone(70, b_footer, footer, fixed_px=50))

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
            sheet_zone(51, p_priority_box, S_PRIORITY, fixed_px=300, color=COLOR_CARD, padding=0),
            sheet_zone(42, p_open, S_KPI_OPEN, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
            sheet_zone(43, p_ack, S_KPI_ACK, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
            sheet_zone(44, p_median, S_KPI_MEDIAN, kpi=True, fixed_px=90, color=COLOR_CARD, padding=0),
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
        action_lines.extend(action(1, "Priority selection filters the module view", S_PRIORITY, S_MODULES, "on-select"))
        action_lines.extend(action(2, "Module selection filters the priority view", S_MODULES, S_PRIORITY, "on-select"))
        action_lines.extend(action(3, "Incidents behind this bar", S_PRIORITY, S_DRILL, "explicit"))
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
    for color in (COLOR_ALERT, COLOR_NEUTRAL):
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
