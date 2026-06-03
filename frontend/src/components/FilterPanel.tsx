interface Props {
  laws: string[];
  lawFilter: string;
  onLawChange: (value: string) => void;
  yearFilter: string;
  onYearChange: (value: string) => void;
}

export function FilterPanel({ laws, lawFilter, onLawChange, yearFilter, onYearChange }: Props) {
  // Keep a current filter that is not in the fetched list selectable (e.g. set
  // via URL before /api/laws resolves).
  const options = lawFilter && !laws.includes(lawFilter) ? [lawFilter, ...laws] : laws;
  return (
    <>
      <select
        className="rounded-md border border-gray-700 bg-[#151a20] px-3 py-2 text-sm text-white shadow-sm"
        value={lawFilter}
        onChange={(event) => onLawChange(event.target.value)}
      >
        <option value="">すべての法令</option>
        {options.map((law) => (
          <option key={law} value={law}>
            {law}
          </option>
        ))}
      </select>
      <input
        className="w-24 rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white shadow-sm"
        placeholder="施行年"
        value={yearFilter}
        onChange={(event) => onYearChange(event.target.value)}
      />
    </>
  );
}
