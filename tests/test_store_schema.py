"""Charter 7.5, the queryable store's schema.

Three workflows read `store_schema.py`: the sync writes rows with these column
names, the status API reads them back, and a column renamed in one place would
be a null served with a 200 in the other. These pin the properties the two
sides rely on rather than repeating the column list.
"""

import json

import store_schema


def test_every_table_passes_its_own_check():
    store_schema.check_schema()


def test_table_names_do_not_contain_each_other():
    """The data table node resolves a table by a name match; two names where one
    contains the other could resolve to the wrong table."""
    names = list(store_schema.TABLES)
    for a in names:
        for b in names:
            if a != b:
                assert a not in b


def test_no_column_shadows_an_n8n_system_column():
    for columns in store_schema.TABLES.values():
        for name, _ in columns:
            assert name not in store_schema.SYSTEM_COLUMNS


def test_the_incident_row_carries_every_field_the_api_serves():
    """The API's decoder reads these row columns; each must exist on the row."""
    columns = set(store_schema.column_names(store_schema.INCIDENTS_TABLE))
    for needed in (
        "incident_id", "created_at", "priority", "status", "raised_as", "is_terminal",
        "transition_count", "acknowledged_at", "resolved_at", "closed_at",
        "minutes_to_acknowledge", "minutes_to_resolve", "minutes_to_close",
        "acknowledge_due_minutes", "unit", "record_id", "summary", "recommended_action",
        "source_module", "business_domain", "assigned_to", "assigned_role",
        "escalation_contact", "event_id", "risk_score", "evidence_json", "predicted_rul",
        "priority_threshold", "model_version", "data_origin", "operational_context_origin",
        "history_json",
    ):
        assert needed in columns, needed
        assert "row.%s" % needed in store_schema.ROW_TO_API_JS, "the decoder never reads %s" % needed


def test_the_summary_row_carries_the_counters_the_sync_resumes_from():
    columns = set(store_schema.column_names(store_schema.SUMMARY_TABLE))
    assert {"key", "incidents_lines", "transitions_lines", "synced_at", "sync_mode"} <= columns


def test_js_column_lists_round_trip():
    declarations = store_schema.js_column_lists()
    for label, table in (("INCIDENT", store_schema.INCIDENTS_TABLE),
                         ("TRANSITION", store_schema.TRANSITIONS_TABLE),
                         ("SUMMARY", store_schema.SUMMARY_TABLE)):
        line = next(l for l in declarations.splitlines() if l.startswith("const %s_COLUMNS = " % label))
        assert json.loads(line.split(" = ", 1)[1].rstrip(";")) == store_schema.column_names(table)
