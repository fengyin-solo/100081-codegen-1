"""泊位计划接口：登记、改单与靠泊编排状态流转（排定 / 靠泊 / 离泊 / 退回上一环节）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    BerthActionPayload,
    BerthCreatePayload,
    BerthUpdatePayload,
    PageResult,
)
from app.services.berth import STATUS_ORDER, BerthService

router = APIRouter(prefix="/api/berth", tags=["泊位计划"])

service = BerthService()

LIST_FIELDS = ["计划编号", "泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度", "计划状态"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按计划编号、泊位编号或靠泊船舶检索"),
    status: str | None = Query(default=None, description="待编排、已排定、靠泊中、已离泊"),
    page: int = 1,
    size: int = 200,
) -> PageResult[dict]:
    """按关键字与状态过滤泊位计划；看板与列表共用这一份数据，保证两处口径一致。"""
    if size > 1000:
        raise HTTPException(status_code=400, detail="每页最多 1000 条，请缩小分页范围")
    if status and status not in STATUS_ORDER:
        raise HTTPException(status_code=400, detail=f"状态只支持：{'、'.join(STATUS_ORDER)}")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export/all")
def export_entries() -> dict[str, Any]:
    """导出泊位计划清单（含留痕）：返回全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "berth", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条泊位计划明细（含完整留痕）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"泊位计划 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: BerthCreatePayload) -> ActionResult:
    """登记一条泊位计划，缺字段或编号重复时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values, str(payload.operator or "").strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message="泊位计划已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: BerthUpdatePayload) -> ActionResult:
    """修改编排字段；改靠泊船舶/泊位必须先退回上一环节，服务层会拦下并说明。"""
    entry, message = service.update_entry(entry_id, payload.values, str(payload.operator or "").strip())
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: BerthActionPayload) -> ActionResult:
    """执行排定、确认靠泊、确认离泊或退回上一环节；不允许的动作当场拦下并说明原因。"""
    entry, message = service.run_action(
        entry_id,
        payload.action,
        str(payload.operator or "").strip(),
        payload.reason,
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
