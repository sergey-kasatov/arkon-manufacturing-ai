"""Render helpers the pages share.

The one that matters is `service_answer`. Everything else here is layout.
"""

import streamlit as st


def page(title, caption=None):
    # No page_icon: Streamlit treats a non-emoji string as a path into its own
    # static directory and answers the request with a 500.
    st.set_page_config(page_title=title + " | Arkon", layout="wide")
    st.title(title)
    if caption:
        st.caption(caption)


def metric_row(pairs, per_row=3):
    """Lay out (label, value) pairs as Streamlit metrics."""
    pairs = list(pairs)
    for start in range(0, len(pairs), per_row):
        for column, (label, value) in zip(st.columns(per_row), pairs[start:start + per_row]):
            column.metric(label, value)


def service_answer(body, empty_message="Nothing matches this query."):
    """Render the status API's four outcomes as four different things, and say
    whether the page may go on.

    This is the one piece of this app that is not presentation. The API separates
    "the store has nothing like that" from "the lookup failed", and a dashboard
    that draws an empty table for both teaches its operator that an outage looks
    like a quiet plant. So a failure gets an error and stops the page, and an
    empty result gets an ordinary note and does not.
    """
    status = body.get("status")
    if status == "ok":
        return True
    if status == "no_match":
        st.info(empty_message)
        return False
    if status == "rejected":
        st.warning("The Steering Cell rejected the query: " + "; ".join(body.get("errors", [])))
        return False
    st.error(
        "The incident lookup failed, so nothing on this page can be read as the state of the "
        "plant. " + str(body.get("message", ""))
    )
    return False


def caveat(text):
    """The sentence that has to travel with a headline number."""
    st.warning(text)


def source_note(*lines):
    st.caption("  \n".join(lines))


def module_page(key):
    """Render one model module. Seven pages, one function, one table row each.

    The numbers come from the tracked metrics file at render time and the live
    incident count comes from the Steering Cell, so nothing on the page is a
    figure somebody typed.
    """
    from utils import api, modules  # imported here so utils.ui stays import-light

    module = modules.MODULES[key]
    page(module["title"], "%s in %s  |  %s" % (module["source_module"], module["business_domain"], module["task"]))

    metric_row(modules.headline(key), per_row=3)
    caveat(module["caveat"])

    facts, live = st.columns([3, 2])
    with facts:
        st.subheader("What it runs on")
        data = modules.meta(key)
        st.markdown("**Dataset.** " + module["dataset"])
        for label, field in (("Architecture", "architecture"), ("Task", "task"), ("Split", "split_note")):
            if data.get(field):
                st.markdown("**%s.** %s" % (label, data[field]))
        st.caption(
            "Full method, limitations and the ablations behind these numbers: `docs/%s`. "
            "The figures below are the ones the notebooks produced." % module["card"]
        )

    with live:
        st.subheader("In the Steering Cell now")
        answer = api.incidents(source_module=module["source_module"], limit=1)
        if api.reachable(answer):
            st.metric("Incidents raised by this module", "{:,}".format(answer["match_count"]))
            st.caption(
                "Counted live. Every module publishes the same event contract into one webhook, "
                "so this page and the Steering Cell page read the same store through the same API."
            )
        else:
            st.error("The Steering Cell did not answer, so this count is unknown.")
        st.caption("Events on disk: `events/out/%s`" % module["events"])

    figures = modules.figures(key)
    st.subheader("Figures (%d)" % len(figures))
    if not figures:
        st.info("No figure is tracked for this module yet.")
        return
    for start in range(0, len(figures), 3):
        for column, path in zip(st.columns(3), figures[start:start + 3]):
            with column:
                st.image(str(path), caption=path.stem.replace("_", " "), width="stretch")
