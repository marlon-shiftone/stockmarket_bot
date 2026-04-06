from pydantic import BaseModel


class RuleResult(BaseModel):
    name: str
    passed: bool
    reason: str
