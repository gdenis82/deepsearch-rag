from pydantic import BaseModel


class QuestionRequest(BaseModel):
    question: str


class PromptUpdate(BaseModel):
    prompt: str

