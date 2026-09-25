<template>
  <section class="page" data-module="berth">
    <header class="page-head">
      <div>
        <h2>泊位计划 · 靠泊编排</h2>
        <p class="page-desc">
          计划沿 待编排 → 已排定 → 靠泊中 → 已离泊 流转，每步留经办人、时间与原因；
          改船改泊位须先退回上一环节；同泊位时段冲突当场拦截，不覆盖原计划。
        </p>
      </div>
      <div class="page-actions">
        <label class="operator-box">
          <span>当班经办人</span>
          <input v-model="operator" @change="persistOperator" placeholder="输入姓名后操作" />
        </label>
        <button class="btn primary" type="button" @click="openCreate">登记泊位计划</button>
        <button class="btn" type="button" @click="exportRows">导出清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="() => reload()">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="keyword" placeholder="计划编号 / 泊位编号 / 船名" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
      <div class="view-switch" role="tablist">
        <button
          type="button"
          :class="{ active: viewMode === 'board' }"
          @click="setView('board')"
        >编排看板</button>
        <button
          type="button"
          :class="{ active: viewMode === 'list' }"
          @click="setView('list')"
        >计划列表</button>
      </div>
    </form>

    <span v-if="errorMessage" class="error-banner">{{ errorMessage }}</span>

    <!-- 编排看板：与列表共用 rows，同一接口同一口径 -->
    <div v-if="viewMode === 'board'" class="kanban">
      <section v-for="s in statuses" :key="s" class="kanban-col">
        <header class="kanban-head" :class="`st-${statuses.indexOf(s)}`">
          <span>{{ s }}</span>
          <em>{{ boardGroups[s]?.length ?? 0 }}</em>
        </header>
        <div class="kanban-body">
          <article
            v-for="row in boardGroups[s] ?? []"
            :key="String(row.id)"
            class="plan-card"
            :class="{ selected: selectedId === row.id }"
            @click="openDetail(row.id)"
          >
            <div class="card-title">
              <strong>{{ row['靠泊船舶'] }}</strong>
              <span class="berth-tag">{{ row['泊位编号'] }}</span>
            </div>
            <div class="card-no">{{ row['计划编号'] }}</div>
            <div class="card-time">靠 {{ row['计划靠泊时间'] || '—' }}</div>
            <div class="card-time">离 {{ row['计划离泊时间'] || '—' }}</div>
            <div v-if="lastTrace(row)" class="card-trace">
              <span>{{ lastTrace(row)!.动作 }} · {{ lastTrace(row)!.经办人 }}</span>
              <span>{{ lastTrace(row)!.时间 }}</span>
            </div>
            <div class="card-actions" @click.stop>
              <button
                v-if="nextAction(row)"
                class="link"
                type="button"
                @click="openAction(nextAction(row)!, row)"
              >{{ nextAction(row) }}</button>
              <button class="link danger" type="button" @click="openAction('退回上一环节', row)">
                退回
              </button>
              <button class="link" type="button" @click="openEdit(row)">改单</button>
              <button class="link" type="button" @click="openDetail(row.id)">留痕</button>
            </div>
          </article>
          <p v-if="!(boardGroups[s]?.length)" class="kanban-empty">暂无计划</p>
        </div>
      </section>
    </div>

    <!-- 计划列表 -->
    <table v-else class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>最近一步</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :class="{ selected: selectedId === row.id }"
          @click="openDetail(row.id)"
        >
          <td v-for="column in columns" :key="column">
            <span v-if="column === '计划状态'" class="status-badge" :class="badgeClass(row.status)">
              {{ row[column] ?? '—' }}
            </span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="trace-cell">
            <template v-if="lastTrace(row)">
              <div>{{ lastTrace(row)!.动作 }}（{{ lastTrace(row)!.经办人 }}）</div>
              <div class="muted">{{ lastTrace(row)!.时间 }}</div>
              <div v-if="lastTrace(row)!.原因" class="reason-text">原因：{{ lastTrace(row)!.原因 }}</div>
            </template>
            <span v-else>—</span>
          </td>
          <td class="row-actions" @click.stop>
            <button
              v-if="nextAction(row)"
              class="link"
              type="button"
              @click="openAction(nextAction(row)!, row)"
            >{{ nextAction(row) }}</button>
            <button class="link danger" type="button" @click="openAction('退回上一环节', row)">退回</button>
            <button class="link" type="button" @click="openEdit(row)">改单</button>
            <button class="link" type="button" @click="openDetail(row.id)">留痕</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无泊位计划数据，可先登记泊位计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条泊位计划记录 · 看板与列表数据同源，刷新后停留在最近视图</span>
      <span v-if="loading" class="muted">加载中…</span>
    </footer>

    <!-- 状态流转弹窗（排定/靠泊/离泊/退回；退回必填原因） -->
    <div v-if="dialog.kind === 'action' && dialog.plan" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.action }}</h3>
        <p class="muted">
          {{ dialog.plan['计划编号'] }} · {{ dialog.plan['靠泊船舶'] }} · {{ dialog.plan['泊位编号'] }}
          ：{{ dialog.plan.status }}
          <template v-if="dialog.action !== '退回上一环节'">
            → {{ targetStatus(dialog.action) }}
          </template>
        </p>
        <label class="form-row">
          <span>经办人</span>
          <input v-model="dialog.operator" placeholder="接班经办人姓名" />
        </label>
        <label v-if="dialog.action === '退回上一环节'" class="form-row">
          <span>退回原因 <em class="required">*</em></span>
          <textarea
            v-model="dialog.reason"
            rows="3"
            placeholder="必须写清退回原因，接班人员据此继续处理，例如：船方推迟到港、泊位临时占用"
          ></textarea>
        </label>
        <label v-else class="form-row">
          <span>备注</span>
          <textarea v-model="dialog.reason" rows="2" placeholder="可选"></textarea>
        </label>
        <p v-if="dialog.error" class="error-banner">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.saving" @click="submitAction">
            {{ dialog.saving ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 登记 / 改单弹窗 -->
    <div v-if="dialog.kind === 'edit'" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.isCreate ? '登记泊位计划' : '修改泊位计划' }}</h3>
        <p v-if="!dialog.isCreate && dialog.plan && dialog.plan.status !== '待编排'" class="warn-banner">
          当前状态「{{ dialog.plan.status }}」：靠泊船舶、泊位编号已锁定，需先退回至「待编排」再修改；
          船长、吃水与计划时间可直接调整（改时间若与同泊位其他计划冲突会被拦截）。
        </p>
        <div class="form-grid">
          <label v-for="f in editFields" :key="f.key" class="form-row">
            <span>{{ f.label }}<em v-if="f.required" class="required">*</em></span>
            <input
              v-model="dialog.form![f.key]"
              :placeholder="f.placeholder"
              :disabled="!dialog.isCreate && f.locked && dialog.plan?.status !== '待编排'"
            />
          </label>
        </div>
        <p v-if="dialog.error" class="error-banner">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.saving" @click="submitEdit">
            {{ dialog.saving ? '提交中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 留痕明细弹窗：换班接续时看上一步痕迹 -->
    <div v-if="dialog.kind === 'detail' && dialog.plan" class="modal-mask" @click.self="closeDialog">
      <div class="modal modal-wide">
        <h3>编排留痕 · {{ dialog.plan['计划编号'] }}</h3>
        <p class="muted">
          {{ dialog.plan['靠泊船舶'] }} · 泊位 {{ dialog.plan['泊位编号'] }} ·
          靠 {{ dialog.plan['计划靠泊时间'] || '—' }} / 离 {{ dialog.plan['计划离泊时间'] || '—' }}
        </p>
        <ol class="timeline">
          <li v-for="item in (dialog.plan.history ?? [])" :key="item['序号']">
            <div class="timeline-head">
              <strong>{{ item['动作'] }}</strong>
              <span class="muted">{{ item['时间'] }}</span>
            </div>
            <div class="timeline-body">
              <span v-if="item['原状态']">{{ item['原状态'] }} → {{ item['新状态'] }}</span>
              <span v-else>登记入库，状态：{{ item['新状态'] }}</span>
              <span>经办人：{{ item['经办人'] }}</span>
            </div>
            <div v-if="item['原因']" class="reason-text">退回/操作原因：{{ item['原因'] }}</div>
            <div v-if="item['说明']" class="detail-text">{{ item['说明'] }}</div>
          </li>
        </ol>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDialog">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { request } from '@/api/client'

interface HistoryRecord {
  序号: number
  动作: string
  原状态: string
  新状态: string
  经办人: string
  原因: string
  时间: string
  说明: string
}
type Row = Record<string, string | number | null>
type Plan = Row & { id: number; status: string; history?: HistoryRecord[] }

const ENDPOINT = '/api/berth'
const statuses = ['待编排', '已排定', '靠泊中', '已离泊']
const NEXT_ACTION: Record<string, string> = {
  待编排: '排定',
  已排定: '确认靠泊',
  靠泊中: '确认离泊',
}
const ACTION_TARGET: Record<string, string> = {
  排定: '已排定',
  确认靠泊: '靠泊中',
  确认离泊: '已离泊',
}
const columns = [
  '计划编号', '泊位编号', '靠泊船舶', '计划靠泊时间', '计划离泊时间',
  '船长', '吃水深度', '计划状态',
]
const editFields: Array<{ key: string; label: string; required?: boolean; placeholder: string; locked: boolean }> = [
  { key: '计划编号', label: '计划编号', required: true, placeholder: 'BERT-YYYYMMDD-XX', locked: false },
  { key: '泊位编号', label: '泊位编号', required: true, placeholder: '如 B-01', locked: true },
  { key: '靠泊船舶', label: '靠泊船舶', required: true, placeholder: '船名', locked: true },
  { key: '计划靠泊时间', label: '计划靠泊时间', placeholder: '2026-09-26 08:00', locked: false },
  { key: '计划离泊时间', label: '计划离泊时间', placeholder: '2026-09-26 20:00', locked: false },
  { key: '船长', label: '船长(米)', placeholder: '可选', locked: false },
  { key: '吃水深度', label: '吃水深度(米)', placeholder: '可选', locked: false },
]

const LS_VIEW = 'berth.viewMode'
const LS_OPERATOR = 'berth.operator'
const LS_SELECTED = 'berth.selectedId'

const rows = ref<Plan[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const viewMode = ref<'board' | 'list'>(
  localStorage.getItem(LS_VIEW) === 'list' ? 'list' : 'board',
)
const operator = ref(localStorage.getItem(LS_OPERATOR) || '值班管理员')
const selectedId = ref<number | null>(
  (() => {
    const v = localStorage.getItem(LS_SELECTED)
    return v ? Number(v) : null
  })(),
)

interface DialogState {
  kind: '' | 'action' | 'edit' | 'detail'
  action: string
  reason: string
  operator: string
  error: string
  saving: boolean
  isCreate: boolean
  plan: Plan | null
  form: Record<string, string> | null
}
const dialog = reactive<DialogState>({
  kind: '',
  action: '',
  reason: '',
  operator: '',
  error: '',
  saving: false,
  isCreate: false,
  plan: null,
  form: null,
})

const boardGroups = computed<Record<string, Plan[]>>(() => {
  const groups: Record<string, Plan[]> = {}
  for (const s of statuses) groups[s] = []
  for (const row of rows.value) {
    if (groups[row.status]) groups[row.status].push(row)
  }
  return groups
})

const stats = computed(() => [
  { label: '待编排计划', value: boardGroups.value['待编排'].length },
  { label: '已排定计划', value: boardGroups.value['已排定'].length },
  { label: '在泊船舶数', value: boardGroups.value['靠泊中'].length },
  { label: '今日已离泊', value: boardGroups.value['已离泊'].length },
])

watch(viewMode, (v) => localStorage.setItem(LS_VIEW, v))
watch(selectedId, (v) => {
  if (v === null) localStorage.removeItem(LS_SELECTED)
  else localStorage.setItem(LS_SELECTED, String(v))
})

function setView(v: 'board' | 'list') {
  viewMode.value = v
}

function persistOperator() {
  localStorage.setItem(LS_OPERATOR, operator.value)
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export/all`, '_blank')
}

function nextAction(row: Plan): string | null {
  return NEXT_ACTION[row.status] ?? null
}

function targetStatus(action: string): string {
  return ACTION_TARGET[action] ?? ''
}

function lastTrace(row: Plan): HistoryRecord | null {
  const h = row.history
  return h && h.length ? h[h.length - 1] : null
}

function badgeClass(status: string): string {
  return `st-${statuses.indexOf(status)}`
}

async function reload(keepSelected = false) {
  loading.value = true
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (keyword.value.trim()) params.set('keyword', keyword.value.trim())
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload?.detail || '泊位计划列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (keepSelected && selectedId.value !== null) {
      const fresh = rows.value.find((r) => Number(r.id) === selectedId.value)
      if (fresh && dialog.kind === 'detail') dialog.plan = fresh
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '泊位计划列表读取失败'
  } finally {
    loading.value = false
  }
}

function closeDialog() {
  dialog.kind = ''
  dialog.plan = null
  dialog.form = null
  dialog.error = ''
  dialog.reason = ''
  dialog.action = ''
}

function openAction(action: string, row: Plan) {
  dialog.kind = 'action'
  dialog.plan = row
  dialog.action = action
  dialog.reason = ''
  dialog.operator = operator.value
  dialog.error = ''
}

async function submitAction() {
  if (!dialog.plan) return
  if (!dialog.operator.trim()) {
    dialog.error = '请填写经办人，每一步流转都要留下经办人'
    return
  }
  if (dialog.action === '退回上一环节' && !dialog.reason.trim()) {
    dialog.error = '退回上一环节必须写清原因，接班人员才能接续处理'
    return
  }
  dialog.saving = true
  dialog.error = ''
  try {
    operator.value = dialog.operator.trim()
    persistOperator()
    const response = await request(`${ENDPOINT}/${dialog.plan.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        action: dialog.action,
        operator: dialog.operator.trim(),
        reason: dialog.reason.trim() || null,
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 冲突、跳步、缺原因等错误原样呈现，数据未被改动
      dialog.error = payload?.message || payload?.detail || '操作未生效'
      return
    }
    closeDialog()
    await reload(true)
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '泊位计划操作失败'
  } finally {
    dialog.saving = false
  }
}

function emptyForm(): Record<string, string> {
  return Object.fromEntries(editFields.map((f) => [f.key, '']))
}

function openCreate() {
  dialog.kind = 'edit'
  dialog.isCreate = true
  dialog.plan = null
  dialog.form = emptyForm()
  dialog.error = ''
}

function openEdit(row: Plan) {
  dialog.kind = 'edit'
  dialog.isCreate = false
  dialog.plan = row
  dialog.form = Object.fromEntries(
    editFields.map((f) => [f.key, String(row[f.key] ?? '')]),
  )
  dialog.error = ''
}

async function submitEdit() {
  if (!dialog.form) return
  if (!operator.value.trim()) {
    dialog.error = '请先在右上角填写当班经办人'
    return
  }
  const form = dialog.form
  if (dialog.isCreate) {
    const missing = editFields
      .filter((f) => f.required && !form[f.key].trim())
      .map((f) => f.label)
    if (missing.length) {
      dialog.error = `缺少必填字段：${missing.join('、')}`
      return
    }
  }
  dialog.saving = true
  dialog.error = ''
  try {
    persistOperator()
    if (dialog.isCreate) {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: form, operator: operator.value.trim() }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        dialog.error = payload?.message || payload?.detail || '登记失败'
        return
      }
      selectedId.value = Number((payload.entry as Plan).id)
    } else if (dialog.plan) {
      const values = Object.fromEntries(
        Object.entries(form).filter(([key]) => key !== '计划编号'),
      )
      const response = await request(`${ENDPOINT}/${dialog.plan.id}`, {
        method: 'PUT',
        body: JSON.stringify({ values, operator: operator.value.trim() }),
      })
      const payload = await response.json()
      if (!response.ok || !payload.ok) {
        // 改船改泊位未退回、改时间撞冲突：原样提示，不静默处理
        dialog.error = payload?.message || payload?.detail || '修改失败'
        return
      }
    }
    closeDialog()
    await reload(true)
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '泊位计划保存失败'
  } finally {
    dialog.saving = false
  }
}

async function openDetail(id: number) {
  selectedId.value = id
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) throw new Error('明细读取失败')
    const plan = (await response.json()) as Plan
    dialog.kind = 'detail'
    dialog.plan = plan
    dialog.error = ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '留痕读取失败'
  }
}

onMounted(() => {
  persistOperator()
  void reload()
})
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; align-items: flex-end; }
.operator-box { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
.operator-box input { width: 150px; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.view-switch { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin-left: 8px; }
.view-switch button { border: none; background: #fff; padding: 6px 14px; cursor: pointer; font-size: 13px; }
.view-switch button.active { background: var(--brand); color: #fff; }
.error-banner { display: block; background: #fef3f2; border: 1px solid #fda29b; color: #b42318; border-radius: 6px; padding: 8px 10px; font-size: 13px; margin-bottom: 10px; }
.warn-banner { background: #fffaeb; border: 1px solid #fedf89; color: #b54708; border-radius: 6px; padding: 8px 10px; font-size: 12px; margin: 0 0 10px; }
.muted { color: var(--muted); font-size: 12px; }
.required { color: #b42318; font-style: normal; }

.kanban { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.kanban-col { background: #eef2f7; border: 1px solid var(--border); border-radius: 8px; display: flex; flex-direction: column; min-height: 320px; }
.kanban-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; border-radius: 8px 8px 0 0; font-weight: 600; font-size: 13px; color: #fff; }
.kanban-head em { font-style: normal; background: rgba(255,255,255,.25); border-radius: 10px; padding: 0 8px; font-size: 12px; }
.st-0 { background: #64748b; }
.st-1 { background: #1f6feb; }
.st-2 { background: #b54708; }
.st-3 { background: #067647; }
.kanban-body { padding: 10px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.kanban-empty { text-align: center; color: var(--muted); font-size: 12px; }
.plan-card { background: #fff; border: 1px solid var(--border); border-left: 3px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; cursor: pointer; font-size: 12px; }
.plan-card:hover { box-shadow: 0 1px 6px rgba(16,24,40,.12); }
.plan-card.selected { outline: 2px solid var(--brand); }
.card-title { display: flex; justify-content: space-between; align-items: center; }
.berth-tag { background: #e0eaff; color: #1d4ed8; border-radius: 4px; padding: 1px 6px; font-size: 11px; }
.card-no { color: var(--muted); margin: 2px 0 4px; }
.card-time { color: #334155; }
.card-trace { margin-top: 6px; padding-top: 6px; border-top: 1px dashed var(--border); display: flex; justify-content: space-between; color: var(--muted); gap: 6px; }
.card-actions { display: flex; gap: 10px; margin-top: 8px; flex-wrap: wrap; }
.link.danger { color: #b42318; }

.status-badge { border-radius: 10px; padding: 2px 8px; font-size: 12px; color: #fff; white-space: nowrap; }
.status-badge.st-0 { background: #64748b; }
.status-badge.st-1 { background: #1f6feb; }
.status-badge.st-2 { background: #b54708; }
.status-badge.st-3 { background: #067647; }
.trace-cell { font-size: 12px; }
.reason-text { color: #b54708; font-size: 12px; margin-top: 2px; }
.detail-text { color: #334155; font-size: 12px; margin-top: 2px; }
tr.selected { background: #f0f6ff; }

.modal-mask { position: fixed; inset: 0; background: rgba(16,24,40,.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 460px; max-height: 86vh; overflow-y: auto; }
.modal-wide { width: 620px; }
.modal h3 { margin: 0 0 8px; font-size: 16px; }
.form-row { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); margin-bottom: 10px; }
.form-row input, .form-row textarea { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; color: #1f2937; font-family: inherit; }
.form-row input:disabled { background: #f2f4f7; color: #98a2b3; cursor: not-allowed; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
.timeline { list-style: none; margin: 8px 0 0; padding: 0; }
.timeline li { border-left: 2px solid var(--brand); padding: 0 0 12px 12px; position: relative; }
.timeline li::before { content: ''; position: absolute; left: -5px; top: 4px; width: 8px; height: 8px; border-radius: 50%; background: var(--brand); }
.timeline-head { display: flex; justify-content: space-between; }
.timeline-body { display: flex; gap: 12px; font-size: 12px; color: #334155; margin-top: 2px; }
</style>
