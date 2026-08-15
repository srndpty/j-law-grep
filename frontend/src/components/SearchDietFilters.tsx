interface Props {
  source: string;
  filters: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}

const INPUT_CLASS =
  "rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white focus:border-blue-500 focus:outline-none";

export function SearchDietFilters({ source, filters, onChange, onClear }: Props) {
  if (source === "law") return null;

  // 会議名は国会会議録だけ、会期と質問/答弁の別は質問主意書だけが持つ。
  // 横断検索ではどちらの絞り込みも意味があるので両方出す。
  const showMeeting = source !== "shuisho";
  const showShuisho = source !== "diet";

  return (
    <div className="flex w-full flex-wrap gap-2 border-t border-gray-800 pt-3">
      <select
        className={INPUT_CLASS}
        value={filters.house ?? ""}
        onChange={(event) => onChange("house", event.currentTarget.value)}
        aria-label="院"
      >
        <option value="">すべての院</option>
        <option value="衆議院">衆議院</option>
        <option value="参議院">参議院</option>
      </select>
      {showMeeting && (
        <input
          className={INPUT_CLASS}
          placeholder="会議名"
          value={filters.meeting ?? ""}
          onChange={(event) => onChange("meeting", event.currentTarget.value)}
        />
      )}
      {showShuisho && (
        <input
          className={`${INPUT_CLASS} w-24`}
          placeholder="会期"
          inputMode="numeric"
          value={filters.session ?? ""}
          onChange={(event) => onChange("session", event.currentTarget.value)}
          aria-label="会期"
        />
      )}
      {showShuisho && (
        <select
          className={INPUT_CLASS}
          value={filters.shuisho_kind ?? ""}
          onChange={(event) => onChange("shuisho_kind", event.currentTarget.value)}
          aria-label="質問/答弁"
        >
          <option value="">質問・答弁の両方</option>
          <option value="question">質問本文のみ</option>
          <option value="answer">答弁本文のみ</option>
        </select>
      )}
      <input
        className={INPUT_CLASS}
        placeholder={source === "shuisho" ? "提出者（前方一致）" : "発言者（前方一致）"}
        value={filters.speaker ?? ""}
        onChange={(event) => onChange("speaker", event.currentTarget.value)}
      />
      <input
        className={INPUT_CLASS}
        type="date"
        value={filters.date_from ?? ""}
        onChange={(event) => onChange("date_from", event.currentTarget.value)}
        aria-label="開始日"
      />
      <input
        className={INPUT_CLASS}
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
