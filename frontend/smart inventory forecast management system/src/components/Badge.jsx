import React from 'react'

export default function Badge({ status, label, className = '' }) {
  const norm = String(status || '').toUpperCase()

  let badgeType = 'badge-draft'
  let display = label || status

  if (['RECEIVED', 'ACTIVE', 'HEALTHY', 'IN STOCK'].includes(norm)) {
    badgeType = 'badge-received'
  } else if (['PARTIALLY_RECEIVED', 'SENT', 'IN PROGRESS', 'PURCHASE'].includes(norm)) {
    badgeType = 'badge-partially_received'
  } else if (['LOW STOCK', 'WARNING', 'PENDING'].includes(norm)) {
    badgeType = 'badge-sent'
  } else if (['CANCELLED', 'OUT OF STOCK', 'INACTIVE', 'CRITICAL', 'DANGER'].includes(norm)) {
    badgeType = 'badge-cancelled'
  } else if (['DRAFT'].includes(norm)) {
    badgeType = 'badge-draft'
  }

  // Format reason names nicely
  if (!label) {
    if (norm === 'PARTIALLY_RECEIVED') display = 'Partially Received'
    else if (norm === 'PURCHASE_ORDER_RECEIVED') display = 'PO Received'
    else if (norm === 'PURCHASE_ORDER_PARTIALLY_RECEIVED') display = 'PO Partial'
    else if (norm === 'INITIAL_STOCK') display = 'Initial Stock'
    else if (norm === 'SALE') display = 'Sale Out'
  }

  return <span className={`badge ${badgeType} ${className}`}>{display}</span>
}
