from pydantic import BaseModel
from src.app.agents.schemas import Range, Position


class ChunkOutputSchema(BaseModel):
    text: str
    range: Range
    token_count: int
