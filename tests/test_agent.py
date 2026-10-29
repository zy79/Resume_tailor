import asyncio

from resume_tailor.agent import ResumeTailoringAgent


def test_langgraph_passes_documents_to_model() -> None:
    received: list[tuple[str, str]] = []

    async def model(resume_text: str, job_description: str) -> str:
        received.append((resume_text, job_description))
        return "Tailored resume"

    agent = ResumeTailoringAgent(model=model)
    result = asyncio.run(
        agent.tailor_resume(
            resume_text="Resume contents",
            job_description="Job description contents",
        )
    )

    assert result == "Tailored resume"
    assert received == [("Resume contents", "Job description contents")]