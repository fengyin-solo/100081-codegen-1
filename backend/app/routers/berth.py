"""泊位计划接口：登记、修改、靠泊编排状态流转与冲突拦截。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.berth import BerthService, STATUS_ORDER

router = APIRouter(prefix="/api/berth", tags=["泊位计划"])

service = BerthService()

LIST_FIELDS = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度", "计划状态"]
STATUSES = STATUS_ORDER  # 待编排、已排定、靠泊中、已离泊


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出泊位计划清单：返回当前全量数据，供接班人员核对。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "berth", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号检索"),
    status: str | None = Query(default=None, description="待编排、已排定、靠泊中、已离泊"),
    berth: str | None = Query(default=None, description="按泊位编号检索"),
    vessel: str | None = Query(default=None, description="按靠泊船舶检索"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按计划编号、泊位、船舶与状态过滤泊位计划列表；没有数据时返回空页，不报错。

    编排看板与计划列表都从本接口取数，保证两处状态口径一致。
    """
    if size > 500:
        raise HTTPException(status_code=400, detail="每页最多 500 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, berth=berth, vessel=vessel, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条泊位计划明细（含每一步操作痕迹）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"泊位计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条泊位计划，缺字段、时间格式不对或编号重复时说明原因，而不是静默丢弃。"""
    operator = str(payload.values.get("operator") or "").strip()
    entry, message = service.create_entry(payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.patch("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修改泊位/船舶/计划时段等字段；非待编排状态改船改泊会被要求先退回并写明原因。"""
    operator = str(payload.values.pop("operator", "") or "").strip()
    payload.values.pop("action", None)
    entry, message = service.update_entry(entry_id, payload.values, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """执行确认排定、确认靠泊、确认离泊及逐档退回；不允许的动作、缺原因、时段冲突都会被拦下。"""
    action = str(payload.values.get("action") or "").strip()
    operator = str(payload.values.get("operator") or "").strip()
    reason = str(payload.values.get("reason") or payload.remark or "").strip()
    entry, message = service.run_action(entry_id, action, operator, reason)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
