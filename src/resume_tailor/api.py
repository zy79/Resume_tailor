from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from resume_tailor.agent import AgentNotConfigured, ResumeTailoringAgent

load_dotenv()

app = FastAPI(title="Resume Tailor API", version="0.1.0")
agent = ResumeTailoringAgent()


class TailorRequest(BaseModel):
    resume_text: str = Field(min_length=1)
    job_description: str = Field(min_length=1)

    @field_validator("resume_text", "job_description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Input must not be blank.")
        return value


class TailorResponse(BaseModel):
    tailored_resume: str


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/tailor", response_model=TailorResponse)
async def tailor_resume(request: TailorRequest) -> TailorResponse:
    try:
        tailored_resume = await agent.tailor_resume(
            resume_text=request.resume_text,
            job_description=request.job_description,
        )
    except AgentNotConfigured as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return TailorResponse(tailored_resume=tailored_resume)