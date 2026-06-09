interface Props {
  source: string;
  filters: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}

export function SearchDietFilters({ source, filters, onChange, onClear }: Props) {
  if (source === "law") return null;

  return (
    <div className="grid w-full grid-cols-1 gap-2 border-t border-gray-800 pt-3 sm:grid-cols-2 lg:grid-cols-[120px_160px_160px_150px_150px_auto]">
      <select
        className="rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
        value={filters.house ?? ""}
        onChange={(event) => onChange("house", event.currentTarget.value)}
        aria-label="院"
      >
        <option value="">すべての院</option>
        <option value="衆議院">衆議院</option>
        <option value="参議院">参議院</option>
      </select>
      <input
        className="rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
        placeholder="会議名"
        value={filters.meeting ?? ""}
        onChange={(event) => onChange("meeting", event.currentTarget.value)}
      />
      <input
        className="rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
        placeholder="発言者"
        value={filters.speaker ?? ""}
        onChange={(event) => onChange("speaker", event.currentTarget.value)}
      />
      <input
        className="rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
        type="date"
        value={filters.date_from ?? ""}
        onChange={(event) => onChange("date_from", event.currentTarget.value)}
        aria-label="開始日"
      />
      <input
        className="rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
        type="date"
        value={filters.date_to ?? ""}
        onChange={(event) => onChange("date_to", event.currentTarget.value)}
        aria-label="終了日"
      />
      <button
        type="button"
        className="rounded-md border border-gray-700 px-2 py-2 text-sm text-gray-300 hover:bg-gray-800"
        onClick={onClear}
      >
        クリア
      </button>
    </div>
  );
}
