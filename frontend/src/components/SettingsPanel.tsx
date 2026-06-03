interface Props {
  effectiveMode: string;
  indexName: string | undefined;
  lawsError: string | null;
  lawsIsLoading: boolean;
  requestId: string | null;
  onToggleDebug: () => void;
}

export function SettingsPanel({
  effectiveMode,
  indexName,
  lawsError,
  lawsIsLoading,
  requestId,
  onToggleDebug,
}: Props) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-gray-700">検索設定</h2>
      <dl className="mt-3 space-y-2 text-xs text-gray-600">
        <div className="flex justify-between gap-3">
          <dt>mode</dt>
          <dd className="font-mono">{effectiveMode}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt>index</dt>
          <dd className="truncate font-mono" title={indexName}>
            {indexName ?? "-"}
          </dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt>request_id</dt>
          <dd className="truncate font-mono" title={requestId ?? undefined}>
            {requestId ?? "-"}
          </dd>
        </div>
      </dl>
      {lawsIsLoading && <p className="mt-3 text-xs text-gray-500">法令一覧を取得中です。</p>}
      {lawsError && <p className="mt-3 text-xs text-amber-600">{lawsError}</p>}
      <button
        type="button"
        className="mt-3 rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
        onClick={onToggleDebug}
      >
        Debug
      </button>
    </div>
  );
}
