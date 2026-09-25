"""泊位计划业务规则：靠泊编排状态机、留痕、改单约束与泊位时段冲突校验。

状态链路：待编排 → 已排定 → 靠泊中 → 已离泊
- 只允许顺序前进（排定 / 确认靠泊 / 确认离泊），也允许逐级退回上一环节，退回必须写原因；
- 每次状态变更与改单都追加一条留痕（动作、时间、经办人、原因、说明），换班的人可据此接续处理；
- 同泊位时段重叠在排定（或已排定后改时间）时当场指出冲突并拒绝，绝不静默覆盖原计划。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "berth"
REQUIRED_FIELDS = ["计划编号", "泊位编号", "靠泊船舶"]
EDITABLE_FIELDS = ["泊位编号", "靠泊船舶", "计划靠泊时间", "计划离泊时间", "船长", "吃水深度"]
# 改靠泊船舶 / 改泊位属于重新编排，必须先退回到待编排。
LOCKED_FIELDS = ["泊位编号", "靠泊船舶"]
STATUS_ORDER = ["待编排", "已排定", "靠泊中", "已离泊"]
# 前进动作：键是动作名，值是动作后必须落到的状态。
FORWARD_ACTIONS = {"排定": "已排定", "确认靠泊": "靠泊中", "确认离泊": "已离泊"}
ROLLBACK_ACTION = "退回上一环节"
# 参与泊位占用的状态：已离泊的泊位已释放，待编排的计划尚未占用泊位。
OCCUPYING_STATUSES = ["已排定", "靠泊中"]

_ACTION_VERB = {
    "已排定": "排定",
    "靠泊中": "确认靠泊",
    "已离泊": "确认离泊",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_dt(value: Any) -> datetime | None:
    """宽容解析计划时间：支持 YYYY-MM-DD 与 YYYY-MM-DD HH:MM[:SS]，解析不了返回 None。"""
    text = str(value or "").strip().replace("/", "-")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_window(entry: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """取计划靠/离泊时间窗；只有日期时按当天 00:00 ~ 23:59:59 处理。"""
    start_text = str(entry.get("计划靠泊时间") or "").strip()
    end_text = str(entry.get("计划离泊时间") or "").strip()
    start = _parse_dt(start_text)
    end = _parse_dt(end_text)
    if end is not None and len(end_text) == 10:
        end = end + timedelta(hours=23, minutes=59, seconds=59)
    if start is not None and end is not None and end < start:
        return None, None
    return start, end


class BerthService:
    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("计划编号", ""))
                or key in str(row.get("靠泊船舶", ""))
                or key in str(row.get("泊位编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记 ----------
    def create_entry(
        self, values: dict[str, Any], operator: str
    ) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        if not operator:
            return None, "经办人未填写，无法登记泊位计划"
        plan_no = str(values.get("计划编号") or "").strip()
        rows = store.rows(MODULE)
        if any(str(row.get("计划编号") or "").strip() == plan_no for row in rows):
            return None, f"计划编号「{plan_no}」已存在，请勿重复登记"

        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        for field in ["计划靠泊时间", "计划离泊时间", "船长", "吃水深度"]:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["计划状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = []
        self._append_history(entry, "登记计划", "", STATUS_ORDER[0], operator, "", "新建泊位计划")
        rows.append(entry)
        return entry, ""

    # ---------- 修改（改船 / 改泊位必须先退回） ----------
    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: str,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        if not operator:
            return None, "经办人未填写，修改无法生效"

        current_status = str(entry.get("status") or "")
        locked_change = [
            field
            for field in LOCKED_FIELDS
            if field in values
            and str(values.get(field) or "").strip()
            and str(values.get(field) or "").strip() != str(entry.get(field) or "")
        ]
        if locked_change and current_status != STATUS_ORDER[0]:
            labels = "、".join(locked_change)
            return (
                None,
                f"当前计划为「{current_status}」，修改{labels}前必须先执行「{ROLLBACK_ACTION}」"
                f"退回上一环节并填写原因，退回至「{STATUS_ORDER[0]}」后才能改单",
            )

        changes: list[str] = []
        for field in EDITABLE_FIELDS:
            if field not in values:
                continue
            new_value = str(values.get(field) or "").strip()
            old_value = str(entry.get(field) or "")
            if new_value != old_value:
                changes.append(f"{field}：{old_value or '空'} → {new_value or '空'}")
                entry[field] = new_value
        if not changes:
            return entry, "内容没有变化"

        # 已占用泊位的状态下改时间窗，要重新做冲突校验，防止改单造出重叠。
        if current_status in OCCUPYING_STATUSES:
            conflict = self._find_conflict(entry)
            if conflict is not None:
                return None, conflict
        self._append_history(entry, "修改编排", current_status, current_status, operator, "", "；".join(changes))
        return entry, "泊位计划已修改"

    # ---------- 状态流转 ----------
    def run_action(
        self,
        entry_id: int,
        action: str,
        operator: str,
        reason: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"泊位计划 {entry_id} 不存在或已归档"
        action = str(action or "").strip()
        operator = str(operator or "").strip()
        reason = str(reason or "").strip()
        if not operator:
            return None, "经办人未填写，状态无法流转"

        current = str(entry.get("status") or STATUS_ORDER[0])
        try:
            current_index = STATUS_ORDER.index(current)
        except ValueError:
            return None, f"当前状态「{current}」不在编排状态序列里，请联系管理员核对数据"

        if action == ROLLBACK_ACTION:
            if not reason:
                return None, "退回上一环节必须写明退回原因，便于接班人员了解情况"
            if current_index == 0:
                return None, "计划已经处于「待编排」，没有上一环节可退"
            target = STATUS_ORDER[current_index - 1]
            self._apply_status(entry, current, target, action, operator, reason)
            return entry, f"已退回至「{target}」，请按原因调整后重新编排"

        if action not in FORWARD_ACTIONS:
            return None, f"动作「{action}」不属于泊位计划可执行范围"
        target = FORWARD_ACTIONS[action]
        expected = STATUS_ORDER[current_index + 1] if current_index + 1 < len(STATUS_ORDER) else None
        if target != expected:
            return (
                None,
                f"当前为「{current}」，只能先到「{expected}」，不能直接{action}为「{target}」",
            )

        if target == "已排定":
            start, end = _parse_window(entry)
            if start is None or end is None:
                return (
                    None,
                    "计划靠泊时间或计划离泊时间缺失/无法识别（格式如 2026-09-26 08:00），暂不能排定",
                )
            conflict = self._find_conflict(entry)
            if conflict is not None:
                # 关键：当场指出冲突且不改动任何数据，杜绝静默覆盖。
                return None, conflict

        self._apply_status(entry, current, target, action, operator, reason)
        return entry, f"泊位计划已{_ACTION_VERB.get(target, action)}，当前状态「{target}」"

    # ---------- 内部规则 ----------
    def _find_conflict(self, entry: dict[str, Any]) -> str | None:
        """同泊位、时段重叠且处于占用状态的另一条计划即冲突；返回可读说明，无冲突返回 None。"""
        start, end = _parse_window(entry)
        if start is None or end is None:
            return None
        berth = str(entry.get("泊位编号") or "").strip()
        self_id = int(entry.get("id", 0))
        for other in store.rows(MODULE):
            if int(other.get("id", 0)) == self_id:
                continue
            if other.get("status") not in OCCUPYING_STATUSES:
                continue
            if str(other.get("泊位编号") or "").strip() != berth:
                continue
            other_start, other_end = _parse_window(other)
            if other_start is None or other_end is None:
                continue
            # 首尾相接（一端离泊 == 另一端靠泊）不算冲突，区间交叉才算。
            if start < other_end and other_start < end:
                return (
                    f"泊位「{berth}」在 {start.strftime('%Y-%m-%d %H:%M')}~"
                    f"{end.strftime('%Y-%m-%d %H:%M')} 的时段已排有计划"
                    f"「{other.get('计划编号')}」（{other.get('靠泊船舶')}，"
                    f"{other_start.strftime('%Y-%m-%d %H:%M')}~"
                    f"{other_end.strftime('%Y-%m-%d %H:%M')}，状态：{other.get('status')}），"
                    "存在时段冲突，请换泊位或调整时间，原有计划保持不变"
                )
        return None

    def _apply_status(
        self,
        entry: dict[str, Any],
        from_status: str,
        to_status: str,
        action: str,
        operator: str,
        reason: str,
    ) -> None:
        entry["status"] = to_status
        entry["计划状态"] = to_status
        entry["pending"] = to_status != STATUS_ORDER[-1]
        entry["abnormal"] = False
        self._append_history(entry, action, from_status, to_status, operator, reason, "")

    def _append_history(
        self,
        entry: dict[str, Any],
        action: str,
        from_status: str,
        to_status: str,
        operator: str,
        reason: str,
        detail: str,
    ) -> None:
        history = entry.setdefault("history", [])
        history.append({
            "序号": len(history) + 1,
            "动作": action,
            "原状态": from_status,
            "新状态": to_status,
            "经办人": operator,
            "原因": reason or "",
            "时间": _now(),
            "说明": detail or "",
        })
