import React, { useState, useRef, useEffect, useMemo } from 'react'
import { Search, ChevronDown, X, Check } from 'lucide-react'

/**
 * Enterprise-grade SearchableSelect Component
 * Allows rapid typeahead searching and selection of products, suppliers, items, etc.
 * Supports dark/light mode seamlessly via design system variables.
 */
export default function SearchableSelect({
  options = [], // [{ value, label, subLabel, badge, meta }]
  value = '',
  onChange,
  placeholder = 'Select option...',
  searchPlaceholder = 'Type to search...',
  disabled = false,
  required = false,
  id,
  className = '',
  allowClear = false,
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [highlightedIndex, setHighlightedIndex] = useState(0)

  const containerRef = useRef(null)
  const searchInputRef = useRef(null)
  const listRef = useRef(null)

  // Find currently selected option
  const selectedOption = useMemo(() => {
    if (value === '' || value === null || value === undefined) return null
    return options.find((opt) => String(opt.value) === String(value)) || null
  }, [options, value])

  // Filter options based on query
  const filteredOptions = useMemo(() => {
    if (!searchQuery.trim()) return options
    const q = searchQuery.toLowerCase().trim()
    return options.filter((opt) => {
      const matchLabel = opt.label && String(opt.label).toLowerCase().includes(q)
      const matchSub = opt.subLabel && String(opt.subLabel).toLowerCase().includes(q)
      const matchBadge = opt.badge && String(opt.badge).toLowerCase().includes(q)
      const matchMeta = opt.meta && String(opt.meta).toLowerCase().includes(q)
      return matchLabel || matchSub || matchBadge || matchMeta
    })
  }, [options, searchQuery])

  // Reset highlight when filter changes
  useEffect(() => {
    setHighlightedIndex(0)
  }, [filteredOptions])

  const [openUpwards, setOpenUpwards] = useState(false)

  // Focus search input and detect dropup vs dropdown
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('')
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        const spaceBelow = window.innerHeight - rect.bottom
        const scrollParent = containerRef.current.closest('.modal-body')

        let shouldOpenUp = false
        if (scrollParent) {
          const parentRect = scrollParent.getBoundingClientRect()
          const spaceInParentBelow = parentRect.bottom - rect.bottom
          if (spaceInParentBelow < 240 && (rect.top - parentRect.top) > 180) {
            shouldOpenUp = true
          }
        } else if (spaceBelow < 240 && rect.top > 240) {
          shouldOpenUp = true
        }

        setOpenUpwards(shouldOpenUp)
      }

      setTimeout(() => {
        searchInputRef.current?.focus()
      }, 50)
    }
  }, [isOpen])

  // Click outside listener
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (disabled) return

    if (!isOpen) {
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowDown') {
        e.preventDefault()
        setIsOpen(true)
      }
      return
    }

    if (e.key === 'Escape') {
      e.preventDefault()
      setIsOpen(false)
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlightedIndex((prev) =>
        prev < filteredOptions.length - 1 ? prev + 1 : 0
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlightedIndex((prev) =>
        prev > 0 ? prev - 1 : filteredOptions.length - 1
      )
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (filteredOptions[highlightedIndex]) {
        handleSelect(filteredOptions[highlightedIndex])
      }
    }
  }

  const handleSelect = (option) => {
    onChange?.(option ? option.value : '', option)
    setIsOpen(false)
    setSearchQuery('')
  }

  const handleClear = (e) => {
    e.stopPropagation()
    onChange?.('', null)
  }

  return (
    <div
      ref={containerRef}
      className={`searchable-select-wrapper ${className}`}
      style={{ position: 'relative', width: '100%' }}
      onKeyDown={handleKeyDown}
    >
      {/* Hidden input to support HTML form validation if required */}
      {required && (
        <input
          type="text"
          value={value || ''}
          required={required}
          onChange={() => {}}
          style={{
            position: 'absolute',
            opacity: 0,
            pointerEvents: 'none',
            top: 0,
            left: 0,
            height: '100%',
            width: '100%',
          }}
          tabIndex={-1}
        />
      )}

      {/* Trigger Button / Form Control Box */}
      <div
        id={id}
        tabIndex={disabled ? -1 : 0}
        onClick={() => !disabled && setIsOpen(!isOpen)}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.55rem 0.85rem',
          backgroundColor: disabled ? 'var(--erp-surface-subtle)' : 'var(--erp-surface)',
          border: `1px solid ${isOpen ? 'var(--erp-brand)' : 'var(--erp-border-strong)'}`,
          borderRadius: 'var(--radius-md)',
          color: selectedOption ? 'var(--erp-text-main)' : 'var(--erp-text-subtle)',
          cursor: disabled ? 'not-allowed' : 'pointer',
          outline: 'none',
          boxShadow: isOpen ? '0 0 0 3px rgba(113, 75, 103, 0.15)' : 'none',
          transition: 'all 0.15s ease',
          minHeight: '38px',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden', flex: 1 }}>
          {selectedOption ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', overflow: 'hidden' }}>
              <span
                style={{
                  fontWeight: 600,
                  fontSize: '0.875rem',
                  color: 'var(--erp-text-main)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {selectedOption.label}
              </span>
              {selectedOption.badge && (
                <span
                  style={{
                    fontSize: '0.7rem',
                    backgroundColor: 'var(--erp-brand-subtle)',
                    color: 'var(--erp-brand)',
                    padding: '1px 6px',
                    borderRadius: '4px',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {selectedOption.badge}
                </span>
              )}
            </div>
          ) : (
            <span style={{ fontSize: '0.875rem', color: 'var(--erp-text-subtle)' }}>
              {placeholder}
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flexShrink: 0, marginLeft: '0.5rem' }}>
          {allowClear && selectedOption && !disabled && (
            <button
              type="button"
              onClick={handleClear}
              style={{
                color: 'var(--erp-text-subtle)',
                display: 'flex',
                alignItems: 'center',
                padding: '2px',
                borderRadius: '3px',
              }}
              title="Clear selection"
            >
              <X size={14} />
            </button>
          )}
          <ChevronDown
            size={16}
            style={{
              color: 'var(--erp-text-muted)',
              transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s ease',
            }}
          />
        </div>
      </div>

      {/* Popover Dropdown Panel */}
      {isOpen && (
        <div
          style={{
            position: 'absolute',
            top: openUpwards ? 'auto' : 'calc(100% + 4px)',
            bottom: openUpwards ? 'calc(100% + 4px)' : 'auto',
            left: 0,
            right: 0,
            minWidth: '280px',
            zIndex: 99999,
            backgroundColor: 'var(--erp-surface)',
            border: '1px solid var(--erp-border)',
            borderRadius: 'var(--radius-md)',
            boxShadow: openUpwards
              ? '0 -10px 25px -5px rgba(0, 0, 0, 0.25), 0 -8px 10px -6px rgba(0, 0, 0, 0.15)'
              : '0 10px 25px -5px rgba(0, 0, 0, 0.25), 0 8px 10px -6px rgba(0, 0, 0, 0.15)',
            overflow: 'hidden',
            animation: 'fadeIn 0.12s ease',
          }}
        >
          {/* Integrated Search Input */}
          <div
            style={{
              padding: '0.5rem 0.65rem',
              borderBottom: '1px solid var(--erp-border)',
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              backgroundColor: 'var(--erp-surface-subtle)',
            }}
          >
            <Search size={14} style={{ color: 'var(--erp-brand)', flexShrink: 0 }} />
            <input
              ref={searchInputRef}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={searchPlaceholder}
              style={{
                width: '100%',
                border: 'none',
                outline: 'none',
                background: 'transparent',
                fontSize: '0.825rem',
                color: 'var(--erp-text-main)',
                fontFamily: 'inherit',
              }}
              onClick={(e) => e.stopPropagation()}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                style={{ color: 'var(--erp-text-subtle)', padding: '2px', display: 'flex' }}
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Options List */}
          <div
            ref={listRef}
            style={{
              maxHeight: '220px',
              overflowY: 'auto',
              padding: '0.35rem',
            }}
          >
            {filteredOptions.length === 0 ? (
              <div
                style={{
                  padding: '1.25rem 0.75rem',
                  textAlign: 'center',
                  fontSize: '0.8rem',
                  color: 'var(--erp-text-muted)',
                }}
              >
                No matches found for "{searchQuery}"
              </div>
            ) : (
              filteredOptions.map((opt, idx) => {
                const isSelected = String(opt.value) === String(value)
                const isHighlighted = idx === highlightedIndex

                return (
                  <div
                    key={opt.value ?? idx}
                    onClick={() => handleSelect(opt)}
                    onMouseEnter={() => setHighlightedIndex(idx)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.5rem 0.65rem',
                      borderRadius: 'var(--radius-sm)',
                      cursor: 'pointer',
                      backgroundColor: isHighlighted
                        ? 'var(--erp-surface-subtle)'
                        : isSelected
                        ? 'var(--erp-brand-subtle)'
                        : 'transparent',
                      color: isSelected ? 'var(--erp-brand)' : 'var(--erp-text-main)',
                      fontSize: '0.825rem',
                      gap: '0.5rem',
                      transition: 'background-color 0.1s ease',
                    }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', overflow: 'hidden' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                        <span style={{ fontWeight: isSelected ? 700 : 500 }}>
                          {opt.label}
                        </span>
                        {opt.badge && (
                          <span
                            style={{
                              fontSize: '0.675rem',
                              backgroundColor: 'var(--erp-brand-subtle)',
                              color: 'var(--erp-brand)',
                              padding: '1px 5px',
                              borderRadius: '3px',
                              fontFamily: 'var(--font-mono)',
                              fontWeight: 600,
                            }}
                          >
                            {opt.badge}
                          </span>
                        )}
                      </div>
                      {opt.subLabel && (
                        <span style={{ fontSize: '0.725rem', color: 'var(--erp-text-muted)' }}>
                          {opt.subLabel}
                        </span>
                      )}
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                      {opt.meta && (
                        <span
                          style={{
                            fontSize: '0.75rem',
                            fontWeight: 600,
                            color: 'var(--erp-text-muted)',
                          }}
                        >
                          {opt.meta}
                        </span>
                      )}
                      {isSelected && (
                        <Check size={14} style={{ color: 'var(--erp-brand)' }} />
                      )}
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
