import { useEffect, useRef, type ReactNode } from 'react'

export default function TerminalDialog({ open, onClose, title, children, className = '', returnFocus }: { open: boolean; onClose: () => void; title: string; children: ReactNode; className?: string; returnFocus?: string }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog || !open) return
    const previous = document.activeElement as HTMLElement | null
    dialog.showModal()
    return () => {
      dialog.close()
      requestAnimationFrame(() => {
        const target = returnFocus ? document.querySelector<HTMLElement>(returnFocus) : previous?.isConnected ? previous : null
        target?.focus({ preventScroll: true })
      })
    }
  }, [open, returnFocus])
  return <dialog ref={ref} className={`terminal-dialog ${className}`} aria-label={title} onCancel={onClose} onClick={(event) => { if (event.target === ref.current) { const rect = ref.current.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose() } }}><div className="dialog-heading"><strong>{title}</strong><button onClick={onClose} aria-label={`Close ${title}`}>×</button></div>{open && children}</dialog>
}
