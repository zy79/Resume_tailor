from collections.abc import Awaitable, Callable
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

TailoringModel = Callable[[str, str], Awaitable[str]]


class ResumeTailoringState(TypedDict):
    resume_text: str
    job_description: str
    tailored_resume: NotRequired[str]


class AgentNotConfigured(RuntimeError):
    """Raised when no model provider is configured for resume tailoring."""


class ResumeTailoringAgent:
    def __init__(self, model: TailoringModel | None = None) -> None:
        self._model = model
        workflow = StateGraph(ResumeTailoringState)
        workflow.add_node("validate_inputs", self._validate_inputs)
        workflow.add_node("tailor_resume", self._tailor_resume)
        workflow.add_edge(START, "validate_inputs")
        workflow.add_edge("validate_inputs", "tailor_resume")
        workflow.add_edge("tailor_resume", END)
        self._graph = workflow.compile()

    async def tailor_resume(self, *, resume_text: str, job_description: str) -> str:
        result = await self._graph.ainvoke(
            {
                "resume_text": resume_text,
                "job_description": job_description,
            }
        )
        return result["tailored_resume"]

    @staticmethod
    def _validate_inputs(state: ResumeTailoringState) -> dict[str, str]:
        if not state["resume_text"].strip():
            raise ValueError("Resume text cannot be empty.")
        if not state["job_description"].strip():
            raise ValueError("Job description cannot be empty.")
        return {}

    async def _tailor_resume(self, state: ResumeTailoringState) -> dict[str, str]:
        if self._model is None:
            raise AgentNotConfigured(
                "No model provider is configured for the resume tailoring agent."
            )

        tailored_resume = await self._model(
            state["resume_text"],
            state["job_description"],
        )
        return {"tailored_resume": tailored_resume}