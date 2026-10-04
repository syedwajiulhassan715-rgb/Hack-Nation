import { useState } from 'react'
import type { Mode } from '../api/client'
import { prettyDate } from '../lib/dates'
import { navigate } from '../lib/router'

interface Props {
  asOf: string | null
  mode: Mode
}

export function Footer({ asOf, mode }: Props) {
  const [how, setHow] = useState(false)
  return (
    <>
      <footer className="footer-strip">
        <span>
          As of <span className="mono">{prettyDate(asOf)}</span>
        </span>
        <span className="dot">·</span>
        <strong>Not legal advice</strong>
        <span className="dot">·</span>
        <span>Sources: official statute and ordinance text</span>
        <span className="dot">·</span>
        <button type="button" className="link" onClick={() => setHow((h) => !h)}>
          How this works
        </button>
        <span className="dot">·</span>
        <button type="button" className="link" onClick={() => navigate('/changes')}>
          Change tests
        </button>
        {mode === 'offline' && <span className="offline">Offline data</span>}
      </footer>
      {how && (
        <div className="how" role="dialog" aria-label="How this works">
          <h3>How this works</h3>
          <ol>
            <li>A model reads each source document and proposes rule records. Every quote must be found word for word in the document, or the record is rejected.</li>
            <li>Each sample address is matched to its legal state and city through the Census address match, not the mailing city.</li>
            <li>A deterministic engine checks each rule against the building facts and the date. Missing facts give Unknown, never a silent no.</li>
            <li>Everything on screen comes from those generated files. Tap any citation to see the exact sentence.</li>
          </ol>
          <p className="fine">This is not legal advice and not a compliance certification.</p>
          <button type="button" className="btn btn-ink" onClick={() => setHow(false)}>
            Close
          </button>
        </div>
      )}
    </>
  )
}
