interface Props {
  yearFilter: string;
  onYearChange: (value: string) => void;
}

export function FilterPanel({ yearFilter, onYearChange }: Props) {
  return (
    <input
      className="w-24 rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white shadow-sm"
      placeholder="施行年"
      value={yearFilter}
      onChange={(event) => onYearChange(event.target.value)}
    />
  );
}
