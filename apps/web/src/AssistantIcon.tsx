import type { NodeKind } from './assistantTypes'

export default function AssistantIcon({ kind }: { kind: NodeKind | 'team' | 'file' | 'upload' }) {
  const paths = {
    quant: <><path d="M4 18V6m0 12h16M8 14l4-5 4 3 4-7" /></>,
    events: <><rect x="5" y="5" width="14" height="15" rx="2" /><path d="M8 3v4m8-4v4M5 10h14M9 14h6m-6 3h3" /></>,
    pricing: <><path d="M7 3h7l4 4v14H6V3h1Zm7 0v5h4M9 12h6m-6 4h4" /></>,
    risk: <><path d="m12 3 8 3v6c0 4-5 8-8 9-3-1-8-5-8-9V6l8-3Z" /><path d="m8 12 3 3 5-6" /></>,
    review: <><path d="m5 12 4 4L19 6" /><path d="M19 13v6H5V5h7" /></>,
    team: <><rect x="8" y="3" width="8" height="6" rx="1.5" /><rect x="2" y="15" width="8" height="6" rx="1.5" /><rect x="14" y="15" width="8" height="6" rx="1.5" /><path d="M12 9v3H6v3m6-3h6v3" /></>,
    file: <><path d="M6 3h8l4 4v14H6V3Zm8 0v5h4M9 12h6m-6 4h4" /></>,
    upload: <><path d="M12 16V3m-4 4 4-4 4 4M4 14v6h16v-6" /></>,
  }
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[kind]}</svg>
}
