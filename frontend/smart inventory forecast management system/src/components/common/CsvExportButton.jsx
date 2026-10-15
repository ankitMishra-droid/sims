import React from 'react'
import { Download } from 'lucide-react'

export default function CsvExportButton({ data = [], filename = 'export', columns = [], title = 'Export CSV' }) {
  const handleExport = () => {
    if (!data.length) return

    // Headers
    const headers = columns.length
      ? columns.map((c) => c.label || c.key)
      : Object.keys(data[0])

    const keys = columns.length ? columns.map((c) => c.key) : Object.keys(data[0])

    const rows = data.map((item) =>
      keys
        .map((k) => {
          let val = item[k]
          if (val === null || val === undefined) val = ''
          val = String(val).replace(/"/g, '""')
          return `"${val}"`
        })
        .join(',')
    )

    const csvContent = [headers.join(','), ...rows].join('\n')
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.setAttribute('href', url)
    link.setAttribute('download', `${filename}_${new Date().toISOString().split('T')[0]}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <button
      type="button"
      className="btn btn-secondary btn-sm"
      onClick={handleExport}
      disabled={!data.length}
      title="Download spreadsheet / CSV"
    >
      <Download size={13} />
      <span>{title}</span>
    </button>
  )
}
