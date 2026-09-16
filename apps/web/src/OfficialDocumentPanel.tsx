import { useEffect, useState } from 'react'
import { useRoute } from './navigation'
import { t } from './i18n'
import { time } from './format'
import type { DocumentCollection, OfficialDocument } from './researchTypes'

export default function OfficialDocumentPanel({ document, collection, historical }: {
  document?: OfficialDocument | null; collection?: DocumentCollection | null; historical: boolean
}) {
  const route = useRoute()
  const selectedParagraph = Number(route.params.get('paragraph'))
  const [expanded, setExpanded] = useState(selectedParagraph > 8)
  useEffect(() => { if (selectedParagraph > 0) globalThis.document.getElementById(`paragraph-${selectedParagraph}`)?.scrollIntoView?.({ block: 'center' }) }, [selectedParagraph, document])
  const paragraphs = document?.text.split('\n\n') ?? []
  return <section className="panel official-document" aria-label={t('Official document text')}>
    <div className="section-heading"><h3>{t('Official document text')}</h3><span className={`badge ${document ? '' : 'badge-amber'}`}>{document ? t('Text captured') : t('Feed excerpt only')}</span></div>
    {collection?.state === 'retrying' && <p className="data-warning">{t('The latest document refresh failed. Saved evidence remains available; collection will retry.')} {t('Next check:')} {time(collection.next_poll_at)}</p>}
    {collection?.state === 'disabled' && <p className="quiet">{t('Document collection is paused. Saved versions remain available.')}</p>}
    {!document && <p>{historical ? t('No official document text had been captured at this cutoff. The feed excerpt remains available above.') : t('Official document text has not been captured yet. The feed excerpt remains available above.')}</p>}
    {document && <>
      <p className="document-provenance"><strong>{document.kind === 'SPEECH' ? t('Official speech') : t('Monetary policy release')}</strong> · {t('Text captured at')} {time(document.observed_at)}</p>
      <p className="quiet">{t('Original language. Capture time is separate from publication time; later versions are excluded from earlier research.')}</p>
      <p className="quiet">{t('Captured page text only; linked articles and PDF attachments are not included.')}</p>
      {document.kind === 'SPEECH' && <p className="coverage-note">{t("A speaker's views are not a committee decision. Topic relevance does not establish a cause for market movements.")}</p>}
      <div className="official-document-body">{paragraphs.slice(0, expanded ? undefined : 8).map((paragraph, index) => <p id={`paragraph-${index + 1}`} className={selectedParagraph === index + 1 ? 'selected-paragraph' : undefined} key={index}><span className="document-paragraph-number" aria-label={t('Paragraph {number}', { number: index + 1 })}>{index + 1}</span>{paragraph}</p>)}</div>
      {paragraphs.length > 8 && <button onClick={() => setExpanded(!expanded)}>{expanded ? t('Show fewer paragraphs') : t('Read all {count} paragraphs', { count: paragraphs.length })}</button>}
      <details className="document-audit"><summary>{t('Source and version details')}</summary><p><a href={document.url} target="_blank" rel="noopener noreferrer">{t('Open official document ↗')}</a></p><p className="audit-ids">{t('Text SHA-256:')} {document.text_sha256}<br />{t('Original HTML SHA-256:')} {document.raw_sha256}<br />{t('Extraction version:')} {document.extractor_version}</p></details>
    </>}
  </section>
}
