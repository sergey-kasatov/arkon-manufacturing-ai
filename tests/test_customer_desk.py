"""The desk agent's prompt and its three tools have to agree with each other.

`customer_desk_prompt.py` names the three tools and states the condition for
each; `build_customer_desk_workflow.py` wires nodes whose NAMES are those tool
names, because n8n derives the name the model sees from the node name at these
type versions. A rename on one side and not the other produces an agent whose
prompt describes tools it does not have, and nothing at run time says so: the
model simply stops calling them. These tests hold the two sides together, and
hold the two settings that fail silently - the retriever's payload key and the
collection it reads.
"""

import json
import pathlib

import pytest

import customer_desk_prompt as prompt
import customer_documents

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW = json.loads((ROOT / "n8n" / "customer_desk_v1.json").read_text(encoding="utf-8"))
NODES = {node["name"]: node for node in WORKFLOW["nodes"]}


def node_tool_name(name):
    """n8n's own derivation, read in the container on 2026-09-08."""
    import re

    return re.sub(r"[^a-zA-Z0-9_-]+", "_", name)[:64]


def test_the_six_elements_appear_in_the_courses_order():
    headings = [
        "1. ROLE AND CONTEXT",
        "2. RETRIEVAL SCOPE",
        "3. NOTICE ACTION BOUNDARY",
        "4. TOOL INVOCATION GUIDANCE",
        "5. FALLBACK BEHAVIOUR",
        "6. TOOL FAILURE FALLBACK",
    ]
    positions = [prompt.SYSTEM_MESSAGE.find(heading) for heading in headings]
    assert all(position >= 0 for position in positions), dict(zip(headings, positions))
    assert positions == sorted(positions), "the elements are out of the guide's order"
    assert len(prompt.ELEMENTS) == 6


def test_the_memory_rules_of_sprint_1_are_carried_unchanged():
    """The coursework's memory policy quotes this block verbatim; a silent edit
    here makes that document wrong about the system it describes."""
    assert prompt.MEMORY_RULES in prompt.SYSTEM_MESSAGE
    assert prompt.CONSENT_QUESTION in prompt.SYSTEM_MESSAGE
    for phrase in ("Remember, for this session only", "Never store or repeat back", "GDPR Article 9"):
        assert phrase in prompt.SYSTEM_MESSAGE, phrase


def test_the_prompt_no_longer_claims_it_cannot_look_a_status_up():
    """Sprint 1 told the customer the desk could not do this. It can now, and a
    leftover sentence would make the agent refuse a tool it holds."""
    for sentence in ("cannot yet look up", "first version of the desk"):
        assert sentence not in prompt.SYSTEM_MESSAGE, sentence


@pytest.mark.parametrize("tool", ["TOOL_DOCUMENTS", "TOOL_CALCULATOR", "TOOL_STATUS"])
def test_every_tool_named_in_the_prompt_is_a_node_of_that_name(tool):
    name = getattr(prompt, tool)
    assert name in prompt.SYSTEM_MESSAGE, "the prompt never names %s" % name
    assert name in NODES, "no node is named %s" % name
    assert node_tool_name(name) == name, "n8n would rename %s for the model" % name


def test_every_tool_is_connected_to_the_agent_as_a_tool():
    for name in (prompt.TOOL_DOCUMENTS, prompt.TOOL_CALCULATOR, prompt.TOOL_STATUS):
        connections = WORKFLOW["connections"].get(name, {}).get("ai_tool", [])
        targets = [entry["node"] for group in connections for entry in group]
        assert targets == ["Desk Agent"], "%s is not wired to the agent: %s" % (name, targets)


def test_the_agent_runs_the_generated_prompt_and_the_documented_ceiling():
    options = NODES["Desk Agent"]["parameters"]["options"]
    assert options["systemMessage"] == prompt.SYSTEM_MESSAGE
    assert options["maxIterations"] == prompt.MAX_ITERATIONS == 6
    assert NODES["Session Memory"]["parameters"]["contextWindowLength"] == prompt.MEMORY_WINDOW


def test_the_retriever_tool_reads_the_desks_own_collection_by_the_key_it_was_written_with():
    """Two silent failures in one node: `arkon-knowledge` is the operators'
    collection and answers plausibly from the wrong documents, and Langflow's
    `page_content` key returns empty passages without an error."""
    node = NODES[prompt.TOOL_DOCUMENTS]
    parameters = node["parameters"]
    assert parameters["mode"] == "retrieve-as-tool"
    assert parameters["qdrantCollection"]["value"] == customer_documents.COLLECTION == "arkon-customer-desk"
    assert parameters["options"]["contentPayloadKey"] == "content"
    assert parameters["options"]["metadataPayloadKey"] == "metadata"
    assert parameters["topK"] == customer_documents.TOP_K
    assert parameters["includeDocumentMetadata"] is True
    assert parameters["toolDescription"] == prompt.TOOL_DOCUMENTS_DESCRIPTION


def test_the_retriever_tool_has_the_same_embedding_model_the_store_was_built_with():
    """A different embedding model retrieves nothing useful and reports success."""
    embeddings = NODES["Desk Query Embeddings"]
    assert embeddings["parameters"]["modelName"] == customer_documents.EMBEDDING_MODEL
    wired = WORKFLOW["connections"]["Desk Query Embeddings"]["ai_embedding"]
    assert [entry["node"] for group in wired for entry in group] == [prompt.TOOL_DOCUMENTS]


def test_the_status_tool_is_the_base_node_used_as_a_tool():
    """`@n8n/n8n-nodes-langchain.toolHttpRequest` is hidden in n8n 2.29 and has
    no execute method: the engine refuses it the moment the agent calls it, and
    the desk reports an outage that is not one. Measured 2026-09-08."""
    node = NODES[prompt.TOOL_STATUS]
    assert node["type"] == "n8n-nodes-base.httpRequestTool"
    assert node["typeVersion"] == 4.4


def test_the_status_tool_requires_the_reference_from_the_model():
    parameters = NODES[prompt.TOOL_STATUS]["parameters"]
    assert parameters["method"] == "GET"
    assert parameters["url"].endswith("/webhook/arkon-customer-status")
    assert parameters["sendQuery"] is True and parameters["specifyQuery"] == "keypair"
    values = parameters["queryParameters"]["parameters"]
    assert len(values) == 1, "one parameter, one reference per call"
    assert values[0]["name"] == prompt.STATUS_PARAMETER
    # `$fromAI` makes it a required argument of the generated tool schema.
    assert values[0]["value"].startswith("={{ $fromAI('%s'," % prompt.STATUS_PARAMETER)
    assert customer_documents.REFERENCE_FORMAT in values[0]["value"]
    assert parameters["toolDescription"] == prompt.TOOL_STATUS_DESCRIPTION


def test_the_status_tool_hands_all_four_endpoint_answers_to_the_model():
    """Found, no match, a rejected reference and the 503 are four different
    things to say. Without `neverError` the last two arrive as one exception."""
    parameters = NODES[prompt.TOOL_STATUS]["parameters"]
    assert parameters["options"]["response"]["response"]["neverError"] is True
    for status in ("ok", "no_match", "rejected", "unavailable"):
        assert "`%s`" % status in prompt.ELEMENT_6_TOOL_FAILURE, status


def test_the_status_tool_promises_only_what_the_projection_serves():
    """The tool description is read by the model as the contract of the endpoint.
    It must not promise a field the customer projection does not serve."""
    description = prompt.TOOL_STATUS_DESCRIPTION
    for forbidden in ("assignee", "priority", "evidence", "engineer", "owner"):
        assert forbidden not in description.lower(), forbidden
    assert "no Arkon employee" in description


def test_the_three_verbatim_sentences_are_in_the_prompt_once_each():
    for sentence in (prompt.FALLBACK_SENTENCE, prompt.TOOL_FAILURE_SENTENCE, prompt.BOUNDARY_SENTENCE):
        assert prompt.SYSTEM_MESSAGE.count(sentence) == 1, sentence[:40]


def test_no_simulated_employee_is_named_in_the_prompt():
    names = customer_documents.roster_names()
    assert names, "the roster is empty"
    for name in names:
        assert name not in prompt.SYSTEM_MESSAGE, name


def test_no_internal_field_name_appears_in_the_prompt():
    assert customer_documents.internal_name_hits(prompt.SYSTEM_MESSAGE) == []


def test_the_failure_fixture_differs_from_the_desk_in_exactly_three_places():
    """The fixture exists to prove element 6 through the agent. If it drifted
    from the desk in anything but its id, its chat path and the failure switch,
    the answer it produces would not be the desk's answer."""
    fixture = json.loads((ROOT / "n8n" / "customer_desk_failtest_v1.json").read_text(encoding="utf-8"))
    assert fixture["id"] == "arkonCustDesk03" != WORKFLOW["id"]
    assert "tool-failure fixture" in fixture["name"]

    fixture_nodes = {node["name"]: node for node in fixture["nodes"]}
    assert set(fixture_nodes) == set(NODES)
    assert fixture["connections"] == WORKFLOW["connections"]
    assert fixture["settings"] == WORKFLOW["settings"]

    for name, node in fixture_nodes.items():
        if name == "Customer Chat":
            assert node["webhookId"] == "arkon-customer-desk-failtest"
            assert {k: v for k, v in node.items() if k != "webhookId"} == {
                k: v for k, v in NODES[name].items() if k != "webhookId"
            }
        elif name == prompt.TOOL_STATUS:
            parameters = node["parameters"]["queryParameters"]["parameters"]
            assert len(parameters) == 2
            assert parameters[1] == {"name": "simulate_failure", "value": "true"}
        else:
            assert node == NODES[name], name


def test_the_shipped_desk_carries_no_failure_switch():
    query = json.dumps(NODES[prompt.TOOL_STATUS]["parameters"]["queryParameters"])
    assert "simulate_failure" not in query


def test_the_reference_format_is_the_one_the_documents_and_the_endpoint_use():
    assert customer_documents.REFERENCE_FORMAT in prompt.SYSTEM_MESSAGE
    assert "ARK-INC-00000" not in prompt.SYSTEM_MESSAGE, "a second spelling of the format"
    assert customer_documents.REFERENCE_FORMAT in prompt.GREETING
