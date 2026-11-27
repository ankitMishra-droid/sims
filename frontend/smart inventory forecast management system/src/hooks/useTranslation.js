import { useSelector } from 'react-redux'
import { translate } from '../i18n/translations'

export function useTranslation() {
  const language = useSelector((state) => state.ui.language || 'en')
  const t = (key, fallback = '') => translate(language, key, fallback)
  return { t, language }
}
