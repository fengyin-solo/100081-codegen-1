<template>
  <section class="page berth-page" data-module="berth">
    <header class="page-head">
      <div>
        <h2>泊位计划管理</h2>
        <p class="page-desc">靠泊编排流程：待编排 → 已排定 → 靠泊中 → 已离泊；每步变更都留操作时间与经办人，改船改泊须先退回并写明原因。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记泊位计划</button>
        <button class="btn" type="button" @click="exportRows">导出泊位计划清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="view-tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        type="button"
        role="tab"
        :class="['tab', { active: viewMode === tab.key }]"
        @click="switchView(tab.key)"
      >
        {{ tab.label }}
        <span class="tab-count">{{ tab.count }}</span>
      </button>
    </div>

    <form class="filter-bar" @submit.prevent="() => reload()">
      <label class="filter-item">
        <span>计划编号</span>
        <input v-model="filters.keyword" placeholder="按计划编号检索" />
      </label>
      <label class="filter-item">
        <span>泊位编号</span>
        <input v-model="filters.berth" placeholder="按泊位编号检索" />
      </label>
      <label class="filter-item">
        <span>靠泊船舶</span>
        <input v-model="filters.vessel" placeholder="按靠泊船舶检索" />
      </label>
      <label v-if="viewMode === 'list'" class="filter-item">
        <span>计划状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 编排看板：与列表同一份数据，列即状态主线 -->
    <div v-if="viewMode === 'board'" class="kanban">
      <section v-for="status in statuses" :key="status" class="kanban-col">
        <header class="kanban-col-head" :class="`is-${statusClass(status)}`">
          <span>{{ status }}</span>
          <em>{{ grouped[status]?.length ?? 0 }}</em>
        </header>
        <div class="kanban-col-body">
          <article
            v-for="row in grouped[status]"
            :key="String(row.id)"
            :class="['plan-card', { active: selectedId === row.id }]"
            @click="openDetail(Number(row.id))"
          >
            <div class="plan-card-top">
              <strong>{{ row['靠泊船舶'] }}</strong>
              <span class="berth-tag">{{ row['泊位编号'] }}</span>
            </div>
            <p class="plan-card-no">{{ row['计划编号'] }}</p>
            <p class="plan-card-window">{{ formatWindow(row) }}</p>
            <p class="plan-card-trace" v-if="lastTrace(row)">
              {{ nextActionLabel(status) }}留痕：{{ lastTrace(row)?.['经办人'] }} · {{ lastTrace(row)?.['时间'] }}
            </p>
            <div class="plan-card-actions" @click.stop>
              <button
                v-for="action in actionsFor(status)"
                :key="action.name"
                type="button"
                :class="['link', action.kind === 'back' ? 'warn' : '']"
                @click="openAction(action.name, row)"
              >
                {{ action.name }}
              </button>
            </div>
          </article>
          <p v-if="!(grouped[status]?.length)" class="kanban-empty">暂无计划</p>
        </div>
      </section>
    </div>

    <!-- 计划列表 -->
    <table v-else class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态</th>
          <th>最近操作</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ selected: selectedId === row.id }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td><span :class="['status-badge', `is-${statusClass(row.status)}`]">{{ row.status }}</span></td>
          <td>
            <template v-if="lastTrace(row)">
              {{ lastTrace(row)?.['动作'] }} · {{ lastTrace(row)?.['经办人'] }}<br />
              <span class="muted-text">{{ lastTrace(row)?.['时间'] }}</span>
            </template>
            <span v-else class="muted-text">—</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(Number(row.id))">明细</button>
            <button
              v-for="action in actionsFor(String(row.status))"
              :key="action.name"
              :class="['link', action.kind === 'back' ? 'warn' : '']"
              type="button"
              @click="openAction(action.name, row)"
            >
              {{ action.name }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无符合条件的泊位计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条泊位计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 动作弹窗：经办人必填，退回必须写原因 -->
    <div v-if="dialog.open" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.action }}</h3>
        <p v-if="dialog.target" class="muted-text">
          {{ dialog.target['计划编号'] }} · {{ dialog.target['靠泊船舶'] }} · 泊位 {{ dialog.target['泊位编号'] }}
        </p>
        <div class="flow-line">
          <span :class="['status-badge', `is-${statusClass(dialog.from)}`]">{{ dialog.from }}</span>
          <b>→</b>
          <span :class="['status-badge', `is-${statusClass(dialog.to)}`]">{{ dialog.to }}</span>
        </div>
        <label class="modal-field">
          <span>经办人<em>*</em></span>
          <input v-model="dialog.operator" list="operator-options" placeholder="换班时请填写本人姓名" />
          <datalist id="operator-options">
            <option value="值班管理员"></option>
            <option value="计划员李岚"></option>
            <option value="夜班周涛"></option>
          </datalist>
        </label>
        <label v-if="dialog.needReason" class="modal-field">
          <span>退回原因<em>*</em></span>
          <textarea v-model="dialog.reason" rows="3" placeholder="写清退回原因，接班人员可在操作痕迹中看到"></textarea>
        </label>
        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="button" :disabled="dialog.busy" @click="submitAction">
            {{ dialog.busy ? '提交中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 登记弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记泊位计划</h3>
        <div class="form-grid">
          <label v-for="field in createFields" :key="field.key" class="modal-field" :class="{ wide: field.wide }">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <input
              v-if="field.type !== 'datetime-local'"
              v-model="createForm[field.key]"
              :placeholder="field.placeholder ?? `请输入${field.label}`"
            />
            <input v-else type="datetime-local" v-model="createForm[field.key]" />
          </label>
        </div>
        <label class="modal-field">
          <span>经办人<em>*</em></span>
          <input v-model="createForm.operator" placeholder="登记人留痕" />
        </label>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" :disabled="creating" @click="submitCreate">
            {{ creating ? '提交中…' : '登记' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 明细抽屉：基本信息、改船改泊、操作痕迹（换班接续看这里） -->
    <div v-if="detail" class="drawer-mask" @click.self="detail = null">
      <aside class="drawer">
        <header class="drawer-head">
          <div>
            <h3>{{ detail['计划编号'] }}</h3>
            <p class="muted-text">{{ detail['靠泊船舶'] }} · 泊位 {{ detail['泊位编号'] }}</p>
          </div>
          <span :class="['status-badge', `is-${statusClass(detail.status)}`]">{{ detail.status }}</span>
        </header>

        <div class="drawer-section">
          <h4>计划信息</h4>
          <dl class="info-grid">
            <div v-for="item in infoItems(detail)" :key="item.label">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value || '—' }}</dd>
            </div>
          </dl>
          <div class="edit-box">
            <p class="muted-text">
              改靠泊船舶或改泊位：当前「{{ detail.status }}」
              <template v-if="detail.status === '待编排'">，可直接修改并留痕。</template>
              <template v-else-if="detail.status === '已离泊'">，流程已结束，不能再改船改泊。</template>
              <template v-else>，须先退回上一环节并写清原因，回到「待编排」后才能修改。</template>
            </p>
            <div class="edit-row">
              <label><span>泊位编号</span><input v-model="editForm['泊位编号']" /></label>
              <label><span>靠泊船舶</span><input v-model="editForm['靠泊船舶']" /></label>
            </div>
            <div class="edit-row">
              <label><span>计划靠泊时间</span><input v-model="editForm['计划靠泊时间']" placeholder="YYYY-MM-DD HH:MM" /></label>
              <label><span>计划离泊时间</span><input v-model="editForm['计划离泊时间']" placeholder="YYYY-MM-DD HH:MM" /></label>
            </div>
            <div class="edit-row">
              <label><span>船长</span><input v-model="editForm['船长']" /></label>
              <label><span>吃水深度</span><input v-model="editForm['吃水深度']" /></label>
            </div>
            <div class="edit-foot">
              <input class="operator-input" v-model="editForm.operator" placeholder="经办人姓名（必填）" />
              <button class="btn primary" type="button" :disabled="saving" @click="submitEdit">
                {{ saving ? '保存中…' : '保存修改' }}
              </button>
            </div>
          </div>
        </div>

        <div class="drawer-section">
          <h4>操作痕迹</h4>
          <ol class="trace-list">
            <li v-for="(trace, index) in traceList(detail)" :key="index" :class="{ latest: index === 0 }">
              <div class="trace-dot"></div>
              <div class="trace-body">
                <p class="trace-title">
                  <strong>{{ trace['动作'] }}</strong>
                  <span v-if="trace['从状态'] || trace['到状态']" class="muted-text">
                    {{ trace['从状态'] || '—' }} → {{ trace['到状态'] || '—' }}
                  </span>
                </p>
                <p class="trace-meta">{{ trace['经办人'] }} · {{ trace['时间'] }}</p>
                <p v-if="trace['原因']" class="trace-reason">原因：{{ trace['原因'] }}</p>
                <p v-if="trace['说明']" class="trace-reason">{{ trace['说明'] }}</p>
              </div>
            </li>
          </ol>
        </div>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, string | number | null | Record<string, unknown>[]>
type Trace = Record<string, string>

const session = useSessionStore()

const ENDPOINT = '/api/berth'
const columns = ['计划编号', '泊位编号', '靠泊船舶', '计划靠泊时间', '计划离泊时间', '船长', '吃水深度']
const statuses = ['待编排', '已排定', '靠泊中', '已离泊'] as const
type Status = (typeof statuses)[number]

const VIEW_KEY = 'berth.viewMode'
const SELECT_KEY = 'berth.selectedId'

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const viewMode = ref<'board' | 'list'>(localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'board')
const selectedId = ref<number | null>(Number(localStorage.getItem(SELECT_KEY)) || null)
const detail = ref<Row | null>(null)

const filters = reactive<Record<string, string>>({ keyword: '', berth: '', vessel: '', status: '' })

const createFields: { key: string; label: string; required?: boolean; placeholder?: string; type?: string; wide?: boolean }[] = [
  { key: '计划编号', label: '计划编号', required: true, placeholder: '如 BERT-0006' },
  { key: '泊位编号', label: '泊位编号', required: true, placeholder: '如 B-01' },
  { key: '靠泊船舶', label: '靠泊船舶', required: true, placeholder: '船舶名称' },
  { key: '计划靠泊时间', label: '计划靠泊时间', type: 'datetime-local' },
  { key: '计划离泊时间', label: '计划离泊时间', type: 'datetime-local' },
  { key: '船长', label: '船长（米）', placeholder: '如 200' },
  { key: '吃水深度', label: '吃水深度（米）', placeholder: '如 10.5' },
]

const tabs = computed(() => [
  { key: 'board' as const, label: '编排看板', count: total.value },
  { key: 'list' as const, label: '计划列表', count: total.value },
])

const stats = computed(() => [
  { label: '在泊船舶数（靠泊中）', value: rows.value.filter((r) => r.status === '靠泊中').length },
  { label: '待编排计划', value: rows.value.filter((r) => r.status === '待编排').length },
  { label: '已排定待靠泊', value: rows.value.filter((r) => r.status === '已排定').length },
  { label: '今日靠泊计划', value: rows.value.length },
])

const grouped = computed<Record<Status, Row[]>>(() => {
  const result = { 待编排: [], 已排定: [], 靠泊中: [], 已离泊: [] } as Record<Status, Row[]>
  for (const row of rows.value) {
    const key = String(row.status) as Status
    if (key in result) result[key].push(row)
  }
  return result
})

const dialog = reactive({
  open: false,
  busy: false,
  action: '',
  from: '',
  to: '',
  needReason: false,
  reason: '',
  operator: session.operator,
  target: null as Row | null,
  error: '',
})

const createOpen = ref(false)
const creating = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({
  计划编号: '', 泊位编号: '', 靠泊船舶: '',
  计划靠泊时间: '', 计划离泊时间: '', 船长: '', 吃水深度: '',
  operator: session.operator,
})

const editForm = reactive<Record<string, string>>({
  泊位编号: '', 靠泊船舶: '', 计划靠泊时间: '', 计划离泊时间: '', 船长: '', 吃水深度: '', operator: session.operator,
})
const saving = ref(false)

function statusClass(status: unknown): string {
  return { 待编排: 'pending', 已排定: 'scheduled', 靠泊中: 'berthed', 已离泊: 'left' }[String(status)] ?? 'pending'
}

function traces(row: Row): Trace[] {
  return Array.isArray(row.history) ? (row.history as Trace[]) : []
}

function traceText(row: Row, key: string): string {
  const value = row[key]
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function lastTrace(row: Row): Trace | null {
  const list = traces(row)
  return list.length ? list[list.length - 1] : null
}

function traceList(row: Row): Trace[] {
  return traces(row).slice().reverse()
}

function nextActionLabel(status: string): string {
  return { 待编排: '登记', 已排定: '排定', 靠泊中: '靠泊', 已离泊: '离泊' }[status] ?? ''
}

function actionsFor(status: string): { name: string; kind: 'forward' | 'back' }[] {
  switch (status) {
    case '待编排':
      return [{ name: '确认排定', kind: 'forward' }]
    case '已排定':
      return [{ name: '确认靠泊', kind: 'forward' }, { name: '退回待编排', kind: 'back' }]
    case '靠泊中':
      return [{ name: '确认离泊', kind: 'forward' }, { name: '退回排定', kind: 'back' }]
    default:
      return []
  }
}

function formatWindow(row: Row): string {
  const start = traceText(row, '计划靠泊时间') || '未排时间'
  const end = traceText(row, '计划离泊时间')
  return end ? `${start} ~ ${end}` : start
}

function infoItems(row: Row) {
  return [
    { label: '计划靠泊时间', value: traceText(row, '计划靠泊时间') },
    { label: '计划离泊时间', value: traceText(row, '计划离泊时间') },
    { label: '船长（米）', value: traceText(row, '船长') },
    { label: '吃水深度（米）', value: traceText(row, '吃水深度') },
  ]
}

function switchView(mode: 'board' | 'list') {
  viewMode.value = mode
  localStorage.setItem(VIEW_KEY, mode)
}

function resetFilters() {
  filters.keyword = ''
  filters.berth = ''
  filters.vessel = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function readFailure(response: Response, fallback: string): Promise<string> {
  try {
    const payload = await response.json()
    return payload?.message || payload?.detail || fallback
  } catch {
    return fallback
  }
}

async function reload(keepDetail = true) {
  errorMessage.value = ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim()) params.set(key, value.trim())
  }
  // 看板需要全部状态列；列表按状态过滤
  if (viewMode.value === 'board') params.delete('status')
  params.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error(await readFailure(response, '泊位计划列表读取失败'))
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (keepDetail && selectedId.value) await loadDetail(selectedId.value, true)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '泊位计划列表读取失败'
  }
}

function openCreate() {
  createError.value = ''
  createForm.operator = session.operator
  createOpen.value = true
}

function toSubmitTime(value: string): string {
  // datetime-local 给出 2026-09-26T08:00，转成接口要求的 YYYY-MM-DD HH:MM
  return value ? value.replace('T', ' ') : ''
}

async function submitCreate() {
  createError.value = ''
  creating.value = true
  const values: Record<string, string> = { operator: createForm.operator.trim() || session.operator }
  for (const field of createFields) {
    const raw = createForm[field.key] ?? ''
    values[field.key] = field.type === 'datetime-local' ? toSubmitTime(raw) : raw.trim()
  }
  if (!values['计划编号'] || !values['泊位编号'] || !values['靠泊船舶']) {
    createError.value = '计划编号、泊位编号、靠泊船舶为必填项'
    creating.value = false
    return
  }
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload?.message || '泊位计划登记失败'
      return
    }
    createOpen.value = false
    selectedId.value = payload.entry?.id ?? null
    if (selectedId.value) localStorage.setItem(SELECT_KEY, String(selectedId.value))
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '泊位计划登记失败'
  } finally {
    creating.value = false
  }
}

function openAction(action: string, row: Row) {
  const flow: Record<string, [Status, Status, boolean]> = {
    确认排定: ['待编排', '已排定', false],
    确认靠泊: ['已排定', '靠泊中', false],
    确认离泊: ['靠泊中', '已离泊', false],
    退回待编排: ['已排定', '待编排', true],
    退回排定: ['靠泊中', '已排定', true],
  }
  const [from, to, needReason] = flow[action] ?? [String(row.status), '', false]
  dialog.open = true
  dialog.action = action
  dialog.from = from
  dialog.to = to
  dialog.needReason = needReason
  dialog.reason = ''
  dialog.operator = session.operator
  dialog.target = row
  dialog.error = ''
}

function closeDialog() {
  dialog.open = false
  dialog.target = null
}

async function submitAction() {
  if (!dialog.target) return
  dialog.error = ''
  if (!dialog.operator.trim()) {
    dialog.error = '请填写经办人，状态变更必须留痕'
    return
  }
  if (dialog.needReason && !dialog.reason.trim()) {
    dialog.error = '退回操作必须写清原因，供接班人员核查'
    return
  }
  dialog.busy = true
  session.setOperator(dialog.operator.trim())
  try {
    const response = await request(`${ENDPOINT}/${dialog.target.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action: dialog.action, operator: dialog.operator.trim(), reason: dialog.reason.trim() },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 冲突、越档等后端拦截原样展示，绝不静默放过
      dialog.error = payload?.message || '操作未生效，请稍后重试'
      return
    }
    closeDialog()
    await reload()
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '泊位计划操作失败'
  } finally {
    dialog.busy = false
  }
}

async function openDetail(id: number) {
  selectedId.value = id
  localStorage.setItem(SELECT_KEY, String(id))
  await loadDetail(id)
}

async function loadDetail(id: number, silent = false) {
  try {
    const response = await request(`${ENDPOINT}/${id}`)
    if (!response.ok) {
      if (!silent) errorMessage.value = await readFailure(response, '泊位计划明细读取失败')
      detail.value = null
      return
    }
    detail.value = await response.json()
    fillEditForm(detail.value as Row)
  } catch (error) {
    if (!silent) errorMessage.value = error instanceof Error ? error.message : '泊位计划明细读取失败'
  }
}

function fillEditForm(row: Row) {
  for (const key of ['泊位编号', '靠泊船舶', '计划靠泊时间', '计划离泊时间', '船长', '吃水深度']) {
    editForm[key] = String(row[key] ?? '')
  }
  editForm.operator = session.operator
}

async function submitEdit() {
  if (!detail.value) return
  if (!editForm.operator.trim()) {
    errorMessage.value = '请填写经办人，修改计划必须留痕'
    return
  }
  saving.value = true
  errorMessage.value = ''
  session.setOperator(editForm.operator.trim())
  try {
    const response = await request(`${ENDPOINT}/${detail.value.id}`, {
      method: 'PATCH',
      body: JSON.stringify({ values: { ...editForm, operator: editForm.operator.trim() } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      errorMessage.value = payload?.message || '修改未生效'
      return
    }
    await reload()
    if (detail.value) await loadDetail(detail.value.id as number)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '修改计划失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await reload()
  // 刷新后仍停在最近一步：恢复上次打开的计划明细
  if (selectedId.value && !detail.value) {
    const stillExists = rows.value.some((r) => Number(r.id) === selectedId.value)
    if (stillExists) await loadDetail(selectedId.value, true)
  }
})
</script>
