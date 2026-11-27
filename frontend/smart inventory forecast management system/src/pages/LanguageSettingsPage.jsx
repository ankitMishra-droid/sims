import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Check, Globe } from 'lucide-react'
import { api } from '../api'
import { updateUserProfile } from '../store/authSlice'
import { setLanguage, addToast } from '../store/uiSlice'
import { SUPPORTED_LANGUAGES } from '../i18n/translations'
import { useTranslation } from '../hooks/useTranslation'
import PageHeader from '../components/common/PageHeader'
import Badge from '../components/Badge'

export default function LanguageSettingsPage() {
  const dispatch = useDispatch()
  const { language, t } = useTranslation()
  const { isAuthenticated } = useSelector((state) => state.auth)
  const [savingCode, setSavingCode] = useState(null)

  const handleSelect = async (lang) => {
    setSavingCode(lang.code)
    dispatch(setLanguage(lang.code))

    if (isAuthenticated) {
      try {
        const updatedUser = await api.updateMe({ preferred_language: lang.code })
        dispatch(updateUserProfile(updatedUser))
      } catch (err) {
        dispatch(
          addToast({
            type: 'warning',
            message: err.message || 'Saved locally, but could not sync language preference to server.',
          })
        )
        setSavingCode(null)
        return
      }
    }

    dispatch(
      addToast({
        type: lang.enabled ? 'success' : 'info',
        message: lang.enabled
          ? `Interface language set to ${lang.name} (${lang.nativeName})`
          : `${lang.name} saved as preference. Core interface currently falls back to English.`,
      })
    )
    setSavingCode(null)
  }

  return (
    <div className="erp-page-container">
      <PageHeader
        title={t('settings.languageTitle')}
        subtitle={t('settings.languageSubtitle')}
      />

      <div className="section-card">
        <div className="section-card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Globe size={18} color="var(--erp-brand)" />
            <h2 className="section-card-title">{t('auth.languageLabel')}</h2>
          </div>
          <Badge status="SENT" label={`Active: ${language.toUpperCase()}`} />
        </div>

        <p style={{ margin: '0 0 1rem', fontSize: '0.84rem', color: 'var(--erp-text-muted)' }}>
          English and Hindi include complete workspace navigation, onboarding, forms, validations, and settings translations.
          Additional regional languages persist across your user account and safely fall back to English strings until their dictionaries are populated. Urdu applies RTL layout preparation attributes (`dir=&quot;rtl&quot;`), though full RTL QA remains pending.
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
            gap: '0.85rem',
          }}
        >
          {SUPPORTED_LANGUAGES.map((lang) => {
            const isSelected = language === lang.code
            return (
              <button
                key={lang.code}
                type="button"
                disabled={savingCode === lang.code}
                onClick={() => handleSelect(lang)}
                className={`choice-tile ${isSelected ? 'selected' : ''}`}
                style={{ cursor: savingCode === lang.code ? 'wait' : 'pointer' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                  <strong style={{ fontSize: '0.92rem', color: 'var(--erp-text-main)' }}>
                    {lang.nativeName}
                  </strong>
                  {isSelected && <Check size={16} color="var(--erp-brand)" />}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.4rem', width: '100%' }}>
                  <span style={{ fontSize: '0.78rem', color: 'var(--erp-text-muted)' }}>
                    {lang.name}{lang.dir === 'rtl' ? ' • RTL Preview' : ''}
                  </span>
                  <Badge
                    status={lang.enabled ? 'ACTIVE' : 'DRAFT'}
                    label={lang.enabled ? 'Available' : 'Fallback (EN)'}
                  />
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
