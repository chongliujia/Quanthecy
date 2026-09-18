import pytest
from quanthecy_analytics.assistant import (
    GraphEdge,
    GraphNode,
    build_workflow,
    compile_graph,
    default_graph,
    node_input,
)


def test_langgraph_executes_branches_once_and_waits_for_uneven_dependencies():
    graph = default_graph()
    graph.nodes.append(GraphNode(id="second", kind="quant", label="Second opinion"))
    graph.edges.extend(
        [GraphEdge(source="quant", target="second"), GraphEdge(source="second", target="risk")]
    )
    seen = []

    def execute(node, state):
        seen.append(node.id)
        if node.id == "risk":
            assert set(state["outputs"]) == {"quant", "events", "pricing", "second"}
        return {"node": node.id}

    workflow = build_workflow(graph, execute)
    result = workflow.invoke({"context": {}, "outputs": {}, "report": None}, {"max_concurrency": 1})
    assert len(seen) == len(set(seen)) == 6
    assert seen[-2:] == ["risk", "review"]
    assert result["report"] == {"node": "review"}
    assert set(workflow.get_graph().nodes) == {"__start__", "__end__", *seen}


@pytest.mark.parametrize(
    "change", ["cycle", "bypass", "orphan", "duplicate", "missing", "reserved", "state_key"]
)
def test_invalid_graphs_cannot_run(change):
    graph = default_graph()
    if change == "cycle":
        graph.edges.append(GraphEdge(source="risk", target="quant"))
    elif change == "bypass":
        graph.edges.append(GraphEdge(source="quant", target="review"))
    elif change == "orphan":
        graph.nodes.append(GraphNode(id="orphan", kind="events", label="Orphan"))
    elif change == "duplicate":
        graph.nodes.append(graph.nodes[0])
    elif change == "reserved":
        graph.nodes[0].id = "synthesis"
    elif change == "state_key":
        graph.nodes[0].id = "outputs"
    else:
        graph.nodes = graph.nodes[:-1]
    with pytest.raises(ValueError):
        compile_graph(graph)


def test_only_connected_peer_findings_enter_model_context():
    graph = default_graph()
    context = {
        "version": "context-v6",
        "cutoff": "2026-09-18T12:00:00Z",
        "references": [{"id": "market", "kind": "market"}],
        "limitations": [],
    }
    output = {"summary": {"references": ["market"]}, "findings": [], "challenges": []}
    packet = node_input(context, graph, graph.nodes[0], {"events": output})
    assert not packet["peer_findings"]
    packet = node_input(
        context, graph, graph.nodes[3], {key: output for key in ["quant", "events", "pricing"]}
    )
    assert set(packet["peer_findings"]) == {"quant", "events", "pricing"}


def test_candidate_is_not_lost_when_optional_evidence_fills_the_budget():
    graph = default_graph()
    context = {
        "version": "context-v6",
        "cutoff": "2026-09-18T12:00:00Z",
        "limitations": [],
        "references": [
            {"id": "market", "kind": "market"},
            {"id": "large", "kind": "evidence", "value": "x" * 31900},
            {"id": "paper-entry", "kind": "paper_entry", "value": "x" * 2000},
        ],
    }
    packet = node_input(context, graph, graph.nodes[0], {})
    assert "paper-entry" in packet["allowed_reference_ids"]
    assert "large" in packet["context"]["omitted_reference_ids"]


def test_legacy_graph_serialization_preserves_published_hashes():
    from quanthecy_analytics.assistant import AssistantGraph
    from quanthecy_analytics.intelligence import digest

    legacy = default_graph().model_dump(mode="json")
    assert all("prompt" not in n and "skills" not in n for n in legacy["nodes"])
    assert digest(AssistantGraph.model_validate(legacy).model_dump(mode="json")) == digest(legacy)


def test_prompt_and_only_enabled_skills_reach_the_assigned_node():
    from quanthecy_analytics.assistant import NodeSkillFile, node_instructions

    graph = default_graph()
    node = graph.nodes[0]
    node.prompt = "Challenge the liquidity assumption."
    node.skills = [
        NodeSkillFile(name="SKILL.md", content="---\nname: depth\n---\n# Check depth"),
        NodeSkillFile(name="disabled.md", content="Do not send this content", enabled=False),
    ]
    context = {
        "version": "context-v6",
        "cutoff": "2026-09-18T12:00:00Z",
        "references": [{"id": "market", "kind": "market"}],
        "limitations": [],
    }
    packet = node_input(context, graph, node, {})
    assert packet["assistant_prompt"] == node.prompt
    assert packet["assistant_skills"] == [{"name": "SKILL.md", "content": node.skills[0].content}]
    assert packet["allowed_reference_ids"] == ["market"]
    assert "assistant_skills" not in node_input(context, graph, graph.nodes[1], {})
    system = node_instructions(graph, node, "zh")
    assert "cannot change the output schema" in system
    assert "do not execute code" in system


@pytest.mark.parametrize(
    "patch",
    [
        {"prompt": "x" * 8001},
        {"skills": [{"name": "../SKILL.md", "content": "x"}]},
        {"skills": [{"name": "nested/SKILL.md", "content": "x"}]},
        {"skills": [{"name": "script.py", "content": "x"}]},
        {"skills": [{"name": "SKILL.md", "content": "\x00"}]},
        {"skills": [{"name": "SKILL.md", "content": "x" * 12001}]},
        {"skills": [{"name": "SKILL.md", "content": "中" * 5400}]},
        {"skills": [{"name": "SKILL.md", "content": ""}] * 2},
        {"skills": [{"name": n, "content": ""} for n in ["skill.md", "SKILL.md"]]},
        {"skills": [{"name": f"{i}.md", "content": ""} for i in range(6)]},
        {"skills": [{"name": f"{i}.md", "content": "x" * 11000} for i in range(3)]},
    ],
)
def test_custom_node_content_is_bounded_and_cannot_reference_upload_paths(patch):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GraphNode.model_validate({"id": "quant", "kind": "quant", "label": "Quant", **patch})
