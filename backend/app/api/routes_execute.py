from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.schemas import ExecuteRequest
from app.api.serializers import result_json
from app.routing.executor import ExecuteCall

router = APIRouter()


@router.post("/execute")
async def execute(body: ExecuteRequest, request: Request, response: Response) -> dict:
    container = request.app.state.container
    call = ExecuteCall(
        task=body.task,
        messages=[{"role": m.role, "content": m.content} for m in body.messages],
        temperature=body.temperature,
        max_output_tokens=body.max_output_tokens,
        cache_requested=body.cache,
        task_id=body.task_id,
        validation=body.validation,
        model_override=None if body.policy_override is None else body.policy_override.model,
    )
    result = await container.executor.execute(
        call, allow_override=container.settings.allow_policy_override
    )
    if result.cache == "hit":
        response.headers["x-modelmesh-cache"] = "hit"
    return result_json(result)
