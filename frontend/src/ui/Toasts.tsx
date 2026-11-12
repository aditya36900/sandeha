import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useStore } from '../store';

/** Moments that change what the operator should do next, announced once. */
export default function Toasts() {
  const { toasts, dismissToast } = useStore();
  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-[340px] max-w-[calc(100vw-2rem)]" aria-live="polite">
      <AnimatePresence>
        {toasts.map(t => (
          <motion.div key={t.id} initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }}
            className="bg-raised rounded-xl px-4 py-3 shadow-xl border-l-4"
            style={{ borderColor: t.tone === 'doubt' ? 'var(--doubt)' : t.tone === 'pass' ? 'var(--pass)' : t.tone === 'fail' ? 'var(--fail)' : 'var(--mist)' }}>
            <div className="flex justify-between gap-3">
              <p className="voice text-lg leading-snug">{t.text}</p>
              <button onClick={() => dismissToast(t.id)} className="text-mist hover:text-bone text-sm" aria-label="Dismiss">✕</button>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
