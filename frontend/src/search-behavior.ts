export function shouldAutoSearch(query: string, mode: string, isComposing: boolean) {
  if (isComposing) return false;
  if (mode === "regex") return false;
  return query.trim().length >= 2;
}
