"""泊位计划业务规则：靠泊编排状态流转、操作留痕、改船改泊约束与泊位时段冲突检测。

状态主线：待编排 → 已排定 → 靠泊中 → 已离泊，只能逐档前进；
除待编排外，改靠泊船舶或改泊位前必须逐档退回上一环节并写清原因。
同泊位时段重叠在排定当场判冲突，直接拦下，不覆盖已有计划。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "berth"
REQUIRED_FIELDS = ["计划编号", "泊位编号", "靠泊船舶"]
OPTIONAL_FIELDS = ["计划靠泊时间", "计划离泊时间", "船长", "吃水深度"]
EDITABLE_FIELDS = ["泊位编号", "靠泊船舶", *OPTIONAL_FIELDS]
WINDOW_FIELDS = ["计划靠泊时间", "计划离泊时间"]

STATUS_ORDER = ["待编排", "已排定", "靠泊中", "已离泊"]
# 已占用泊位时段的状态：排定未靠与正在靠泊都算占位
ACTIVE_STATUSES = {"已排定", "靠泊中"}
# 动作 -> (前置状态, 目标状态)
FORWARD_ACTIONS = {
    "确认排定": ("待编排", "已排定"),
    "确认靠泊": ("已排定", "靠泊中"),
    "确认离泊": ("靠泊中", "已离泊"),
}
ROLLBACK_ACTIONS = {
    "退回待编排": ("已排定", "待编排"),
    "退回排定": ("靠泊中", "已排定"),
}
# 目标状态 -> 退回动作名，用于拼接改船改泊时的引导提示
ROLLBACK_TO_ACTION = {target: name for name, (_, target) in ROLLBACK_ACTIONS.items()}

_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_time(value: Any) -> datetime | None:
    """把界面传入的日期/日期时间解析成可比较的时刻；认不出就返回 None。"""
    if value is None:
        return None
    text = str(value).strip().replace("/", "-").replace("T", " ")
    if not text:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _display_time(value: Any) -> str:
    """历史与列表里统一展示口径，认不出的原样返回。"""
    text = str(value or "").strip()
    parsed = _parse_time(text)
    if parsed is None:
        return text
    if len(text) in (10,):
        return parsed.strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d %H:%M")


class BerthService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        berth: str | None = None,
        vessel: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("计划编号", ""))]
        if berth:
            rows = [row for row in rows if berth in str(row.get("泊位编号", ""))]
        if vessel:
            rows = [row for row in rows if vessel in str(row.get("靠泊船舶", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 看板与列表共用同一份数据与排序：计划编号靠前、新排定的也能稳定找到
        rows = sorted(rows, key=lambda row: (STATUS_ORDER.index(row.get("status")) if row.get("status") in STATUS_ORDER else 99, str(row.get("计划编号", ""))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self, values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        if not operator:
            return None, "请填写经办人，登记计划必须留痕"
        plan_no = str(values["计划编号"]).strip()
        if any(str(row.get("计划编号", "")).strip() == plan_no for row in store.rows(MODULE)):
            return None, f"计划编号「{plan_no}」已存在，不能重复登记"
        window_error = self._window_error(values)
        if window_error:
            return None, window_error

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in [*REQUIRED_FIELDS, *OPTIONAL_FIELDS]:
            text = str(values.get(field) or "").strip()
            entry[field] = _display_time(text) if field in WINDOW_FIELDS and text else (text or None)
        entry["status"] = STATUS_ORDER[0]
        entry["计划状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = []
        self._append_trace(entry, operator=operator, action="登记计划", to=STATUS_ORDER[0])
        rows.append(entry)
        return entry, "泊位计划已登记，等待编排"

    def run_action(
        self, entry_id: int, action: str, operator: str, reason: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        if not operator:
            return None, "请填写经办人，状态变更必须留痕"
        action = (action or "").strip()
        current = str(entry.get("status", ""))

        if action in FORWARD_ACTIONS:
            expected, target = FORWARD_ACTIONS[action]
            if current != expected:
                return None, self._forward_reject(action, current)
            # 排定/靠泊前校验计划时段：缺时间、时间倒置、同泊位重叠都当场拦下
            conflict = self._schedule_conflict(entry)
            if conflict:
                return None, conflict
            entry["status"] = target
            entry["计划状态"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            self._append_trace(entry, operator=operator, action=action, frm=current, to=target)
            return entry, f"泊位计划已{action}：{entry.get('靠泊船舶')} / 泊位 {entry.get('泊位编号')}"

        if action in ROLLBACK_ACTIONS:
            expected, target = ROLLBACK_ACTIONS[action]
            if current != expected:
                return None, f"「{action}」只能在「{expected}」状态下执行，当前为「{current}」"
            if not reason.strip():
                return None, f"执行「{action}」必须写清退回原因，供接班人员核查"
            entry["status"] = target
            entry["计划状态"] = target
            entry["pending"] = True
            self._append_trace(
                entry, operator=operator, action=action, frm=current, to=target, reason=reason.strip()
            )
            return entry, f"已退回「{target}」，原因已记录：{reason.strip()}"

        known = ", ".join([*FORWARD_ACTIONS.keys(), *ROLLBACK_ACTIONS.keys()])
        return None, f"动作「{action}」不属于泊位计划可执行范围，可选动作：{known}"

    def update_entry(
        self, entry_id: int, values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        if not operator:
            return None, "请填写经办人，修改计划必须留痕"

        changes = {
            field: str(values[field]).strip()
            for field in EDITABLE_FIELDS
            if field in values and str(values[field] or "").strip()
        }
        if not changes:
            return None, "没有需要更新的字段"
        current = str(entry.get("status", ""))

        # 改船、改泊是重新分配资源：不在待编排状态，一律先退回
        guarded = {"靠泊船舶", "泊位编号"} & changes.keys()
        if guarded and current != STATUS_ORDER[0]:
            return None, self._guarded_field_reject(current, guarded)

        # 先在草稿副本上校验时段，校验不过绝不动原记录
        draft = dict(entry)
        for field, value in changes.items():
            draft[field] = _display_time(value) if field in WINDOW_FIELDS else value
        window_error = self._window_error(draft)
        if window_error:
            return None, window_error
        if current in ACTIVE_STATUSES and (set(changes) & set(WINDOW_FIELDS)):
            conflict = self._schedule_conflict(draft, exclude=entry)
            if conflict:
                return None, conflict

        notes = []
        for field in EDITABLE_FIELDS:
            if field not in changes:
                continue
            old_value = entry.get(field)
            new_value = changes[field]
            if field in WINDOW_FIELDS:
                new_value = _display_time(new_value)
            if str(old_value or "") != str(new_value or ""):
                notes.append(f"{field}：{old_value or '空'} → {new_value or '空'}")
            entry[field] = new_value
        if not notes:
            return entry, "提交内容与现状一致，未产生变更"
        entry["计划状态"] = current
        self._append_trace(
            entry,
            operator=operator,
            action="修改计划",
            frm=current,
            to=current,
            note="；".join(notes),
        )
        return entry, "计划已修改，变更内容已留痕"

    # ---- 内部校验 -------------------------------------------------

    def _forward_reject(self, action: str, current: str) -> str:
        expected, _ = FORWARD_ACTIONS[action]
        if current == STATUS_ORDER[-1]:
            return f"计划已「{STATUS_ORDER[-1]}」，靠泊流程结束，不能再执行「{action}」"
        if current == FORWARD_ACTIONS[action][1]:
            return f"计划当前已是「{current}」，请勿重复执行「{action}」"
        return f"「{action}」只能从「{expected}」执行，当前为「{current}」，请按待编排→已排定→靠泊中→已离泊逐档推进"

    def _guarded_field_reject(self, current: str, fields: set[str]) -> str:
        labels = "、".join(sorted(fields))
        if current not in STATUS_ORDER:
            return f"计划状态「{current}」无法识别，不能修改{labels}，请联系管理员核对"
        index = STATUS_ORDER.index(current)
        if current == STATUS_ORDER[-1]:
            return f"计划已「{STATUS_ORDER[-1]}」，不能再修改{labels}；如需调整请新建泊位计划"
        prev_status = STATUS_ORDER[index - 1]
        rollback = ROLLBACK_TO_ACTION[prev_status]
        guide = f"请先执行「{rollback}」退回「{prev_status}」并写清原因"
        if prev_status != STATUS_ORDER[0]:
            guide += f"，再继续退回至「{STATUS_ORDER[0]}」"
        return f"当前为「{current}」，不允许直接修改{labels}。{guide}后才能改{labels}"

    def _window_error(self, data: dict[str, Any]) -> str:
        start_text = str(data.get("计划靠泊时间") or "").strip()
        end_text = str(data.get("计划离泊时间") or "").strip()
        if not start_text and not end_text:
            return ""
        start = _parse_time(start_text)
        end = _parse_time(end_text)
        if start_text and start is None:
            return "计划靠泊时间格式无法识别，请使用 YYYY-MM-DD HH:MM"
        if end_text and end is None:
            return "计划离泊时间格式无法识别，请使用 YYYY-MM-DD HH:MM"
        if start and end and end <= start:
            return "计划离泊时间必须晚于计划靠泊时间，请检查时段"
        return ""

    def _schedule_conflict(
        self, data: dict[str, Any], exclude: dict[str, Any] | None = None
    ) -> str:
        """同泊位、计划时段重叠且处于占位状态时，返回冲突说明；无冲突返回空串。"""
        berth = str(data.get("泊位编号") or "").strip()
        start = _parse_time(data.get("计划靠泊时间"))
        end = _parse_time(data.get("计划离泊时间"))
        if not berth or start is None or end is None:
            return ("排定前必须先补齐可识别的计划靠泊时间与计划离泊时间"
                    "（格式 YYYY-MM-DD HH:MM），否则无法判定泊位时段")
        if end <= start:
            return "计划离泊时间必须晚于计划靠泊时间，请检查时段"
        for other in store.rows(MODULE):
            if other is (exclude or data) or int(other.get("id", 0)) == int(data.get("id", 0)):
                continue
            if other.get("status") not in ACTIVE_STATUSES:
                continue
            if str(other.get("泊位编号") or "").strip() != berth:
                continue
            other_start = _parse_time(other.get("计划靠泊时间"))
            other_end = _parse_time(other.get("计划离泊时间"))
            if other_start is None or other_end is None:
                continue
            # 半开区间：首尾相接（一条离泊、另一条靠泊）不算冲突
            if start < other_end and other_start < end:
                return (
                    f"泊位时段冲突：泊位「{berth}」在 {_display_time(start)}~{_display_time(end)} "
                    f"已被计划「{other.get('计划编号')}」（{other.get('靠泊船舶')}，"
                    f"{_display_time(other_start)}~{_display_time(other_end)}，状态 {other.get('status')}）占用，"
                    "不允许重复排定，请更换泊位或调整时段"
                )
        return ""

    def _append_trace(
        self,
        entry: dict[str, Any],
        *,
        operator: str,
        action: str,
        frm: str = "",
        to: str = "",
        reason: str = "",
        note: str = "",
    ) -> None:
        entry.setdefault("history", []).append(
            {
                "时间": _now_text(),
                "经办人": operator.strip(),
                "动作": action,
                "从状态": frm,
                "到状态": to,
                "原因": reason,
                "说明": note,
            }
        )
