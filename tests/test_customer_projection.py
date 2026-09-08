"""The Customer Quality Desk's projection: what a customer may know.

`customer_projection.py` is read by the customer status API's generator, by
its checker and by the desk's customer documents. These pin the properties
the three rely on: every lifecycle status has customer words, a finished
notice promises nothing further, the acknowledgement commitment is the
charter's own window, and the served field list shares no name with the
internal incident row, so a customer field can never be a column served by
mistake.
"""

import customer_projection
import lifecycle
import store_schema


def test_the_projection_passes_its_own_check():
    customer_projection.check_projection()


def test_every_lifecycle_status_has_customer_words():
    assert set(customer_projection.CUSTOMER_STAGES) == set(lifecycle.LIFECYCLE)


def test_terminal_statuses_promise_no_next_step():
    for status in lifecycle.TERMINAL_STATUSES:
        assert customer_projection.CUSTOMER_STAGES[status]["next_step"] is None
        assert customer_projection.CUSTOMER_STAGES[status]["stage"] == customer_projection.STAGE_COUNT


def test_every_open_status_has_a_commitment_window():
    for status, stage in customer_projection.CUSTOMER_STAGES.items():
        if stage["next_step"] is not None:
            assert status in customer_projection.COMMITMENT_HOURS


def test_the_acknowledgement_commitment_is_the_charter_window():
    """The customer is promised exactly what the plant is measured on."""
    ack = customer_projection.COMMITMENT_HOURS["new"]
    for priority, minutes in lifecycle.ACK_WINDOW_MINUTES.items():
        assert ack[priority] == minutes / 60.0
    assert "P3" not in ack and "P4" not in ack


def test_served_fields_share_only_the_closing_date_with_the_internal_row():
    """The one name both sides use is `closed_at`, and it means the same date on
    both. Everything else the customer sees has its own name, so a row column
    can never be served by mistake under the customer's name for it."""
    internal = set(store_schema.column_names(store_schema.INCIDENTS_TABLE))
    assert set(customer_projection.SERVED_FIELDS) & internal == {"closed_at"}


def test_internal_names_cover_the_row_columns_that_identify_people_and_evidence():
    """A column that names a person, a record or the model must be on the deny list
    the checker applies to the answer node's code."""
    for column in ("assigned_to", "escalation_contact", "record_id", "evidence_json", "model_version", "risk_score"):
        assert any(column.startswith(name) for name in customer_projection.INTERNAL_NAMES), column


def test_the_projection_js_is_injected_verbatim():
    generated = customer_projection.js_constants()
    assert "const CUSTOMER_STAGES" in generated
    assert "arkonCustomerProjection" in customer_projection.PROJECTION_JS
