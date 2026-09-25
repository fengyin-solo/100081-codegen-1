import { defineStore } from 'pinia'

const OPERATOR_KEY = 'port.session.operator'
const SHIFT_KEY = 'port.session.shift'

function readOperator(): string {
  const saved = window.localStorage.getItem(OPERATOR_KEY)
  return saved && saved.trim() ? saved.trim() : '值班管理员'
}

function readShift(): string {
  const saved = window.localStorage.getItem(SHIFT_KEY)
  return saved && saved.trim() ? saved.trim() : '白班 08:00-20:00'
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: readOperator(),
    shiftLabel: readShift(),
    scope: '港口集装箱作业调度平台',
  }),
  getters: {
    canOperate: (state) => state.operator.trim().length > 0,
  },
  actions: {
    setOperator(name: string) {
      this.operator = name.trim() || '值班管理员'
      window.localStorage.setItem(OPERATOR_KEY, this.operator)
    },
    setShift(label: string) {
      this.shiftLabel = label
      window.localStorage.setItem(SHIFT_KEY, label)
    },
  },
})
