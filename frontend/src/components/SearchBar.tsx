import { Search as SearchIcon } from "lucide-react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onCompositionStart: () => void;
  onCompositionEnd: (value: string) => void;
}

export function SearchBar({ value, onChange, onCompositionStart, onCompositionEnd }: Props) {
  return (
    <div className="relative flex-1">
      <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
      <input
        className="w-full rounded-md border border-gray-700 bg-[#151a20] py-2 pl-9 pr-3 text-sm text-white shadow-sm focus:border-blue-500 focus:outline-none"
        placeholder="キーワードや法令条番号を入力"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onCompositionStart={onCompositionStart}
        onCompositionEnd={(event) => onCompositionEnd(event.currentTarget.value)}
      />
    </div>
  );
}
