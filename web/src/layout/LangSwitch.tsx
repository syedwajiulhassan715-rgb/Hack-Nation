import { LANGS, useI18n } from '../i18n'

/** EN / ES switch. Changes UI copy and asks for Spanish answers (`lang=es`); law text stays as written. */
export function LangSwitch({ variant = 'paper' }: { variant?: 'paper' | 'ink' }) {
  const { lang, setLang, t } = useI18n()
  return (
    <div className={`lang-switch ${variant}`} role="group" aria-label={t.language}>
      {LANGS.map((l) => (
        <button
          key={l}
          type="button"
          lang={l}
          aria-pressed={lang === l}
          className={lang === l ? 'on' : ''}
          onClick={() => setLang(l)}
          title={l === 'en' ? 'English' : 'Español'}
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  )
}
