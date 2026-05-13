import { createContext, useContext, useState } from 'react'
import { strings } from '../i18n/strings'

const LanguageContext = createContext()

export function LanguageProvider({ children }) {
  const [lang, setLang] = useState(
    () => localStorage.getItem('xia_lang') || 'zh'
  )
  const t = (key, params) => {
    let s = strings[lang][key] ?? key
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        s = s.replace(`{${k}}`, v)
      })
    }
    return s
  }
  const toggle = () => {
    const next = lang === 'zh' ? 'en' : 'zh'
    setLang(next)
    localStorage.setItem('xia_lang', next)
  }
  return (
    <LanguageContext.Provider value={{ lang, t, toggle }}>
      {children}
    </LanguageContext.Provider>
  )
}

export const useLanguage = () => useContext(LanguageContext)
