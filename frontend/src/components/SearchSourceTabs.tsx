import { clsx } from "clsx";

const SOURCES = [
  { value: "law", label: "法令" },
  { value: "diet", label: "国会" },
  { value: "all", label: "横断" },
];

interface Props {
  source: string;
  onChange: (source: string) => void;
}

export function SearchSourceTabs({ source, onChange }: Props) {
  return (
    <div className="flex rounded-md border border-gray-700 bg-[#151a20] p-0.5 shadow-sm">
      {SOURCES.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={clsx(
            "rounded px-2.5 py-1 text-sm font-medium transition",
            source === item.value ? "bg-emerald-600 text-white" : "text-gray-300 hover:bg-gray-800"
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
