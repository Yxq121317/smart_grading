from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.core.config import Settings
from app.graph.nodes.apply_corrections import make_apply_corrections_node
from app.graph.nodes.build_report import make_build_report_node
from app.graph.nodes.collect_results import collect_results_node
from app.graph.nodes.finalize import make_finalize_node
from app.graph.nodes.grade_question import make_grade_question_node
from app.graph.nodes.human_review import human_review_node
from app.graph.nodes.load_submission import make_load_submission_node
from app.graph.nodes.persist_report import make_persist_report_node
from app.graph.nodes.persist_results import make_persist_results_node
from app.graph.nodes.prepare_questions import make_prepare_questions_node
from app.graph.nodes.review_gate import review_gate
from app.graph.state import GradingState
from app.graph.subgraphs.grade_question import build_question_subgraph
from app.graph.subgraphs.rubric import build_rubric_subgraph


def build_grading_graph(llm, session_factory, settings: Settings, checkpointer):
    rubric_graph = build_rubric_subgraph(llm)
    question_graph = build_question_subgraph(llm, settings)

    def fan_out(state: GradingState):
        return [
            Send(
                "grade_question",
                {
                    "context": context,
                    "grading_run_id": state["grading_run_id"],
                },
            )
            for context in state["question_contexts"]
        ]

    graph = StateGraph(GradingState)
    graph.add_node(
        "load_submission",
        make_load_submission_node(session_factory, settings),
    )
    graph.add_node(
        "prepare_questions",
        make_prepare_questions_node(rubric_graph, session_factory),
    )
    graph.add_node(
        "grade_question",
        make_grade_question_node(question_graph, session_factory),
    )
    graph.add_node("collect_results", collect_results_node)
    graph.add_node(
        "persist_results",
        make_persist_results_node(session_factory),
    )
    graph.add_node("human_review", human_review_node)
    graph.add_node(
        "apply_corrections",
        make_apply_corrections_node(session_factory),
    )
    graph.add_node("build_report", make_build_report_node(llm))
    graph.add_node(
        "persist_report",
        make_persist_report_node(session_factory),
    )
    graph.add_node("finalize", make_finalize_node(session_factory))

    graph.add_edge(START, "load_submission")
    graph.add_edge("load_submission", "prepare_questions")
    graph.add_conditional_edges("prepare_questions", fan_out, ["grade_question"])
    graph.add_edge("grade_question", "collect_results")
    graph.add_edge("collect_results", "persist_results")
    graph.add_conditional_edges(
        "persist_results",
        review_gate,
        {"human_review": "human_review", "build_report": "build_report"},
    )
    graph.add_edge("human_review", "apply_corrections")
    graph.add_edge("apply_corrections", "build_report")
    graph.add_edge("build_report", "persist_report")
    graph.add_edge("persist_report", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)
