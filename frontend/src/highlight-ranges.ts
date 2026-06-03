export interface HighlightRange {
  start: number;
  end: number;
}

export function mergeHighlightRanges(ranges: HighlightRange[], textLength: number) {
  const sorted = ranges
    .filter((range) => range.start >= 0 && range.end > range.start && range.end <= textLength)
    .sort((a, b) => a.start - b.start);
  const merged: HighlightRange[] = [];

  for (const range of sorted) {
    const last = merged[merged.length - 1];
    if (!last || range.start > last.end) {
      merged.push({ ...range });
    } else {
      last.end = Math.max(last.end, range.end);
    }
  }

  return merged;
}

export function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}
