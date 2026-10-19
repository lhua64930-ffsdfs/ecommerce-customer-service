export function formatTime(iso: string): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''

  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

  if (sameDay) return time
  const day = date.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  return `${day} ${time}`
}
