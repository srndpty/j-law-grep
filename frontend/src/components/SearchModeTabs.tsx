import { clsx } from "clsx";

const MODES = [
  { value: "auto", label: "自動" },
  { value: "literal", label: "リテラル" },
  { value: "boolean", label: "Boolean" },
  { value: "citation", label: "引用" },
  { value: "regex", label: "正規表現" },
];

interface Props {
  mode: string;
  onChange: (mode: string) => void;
}

export function SearchModeTabs({ mode, onChange }: Props) {
  return (
    <div className="flex rounded-md border border-gray-700 bg-[#151a20] p-0.5 shadow-sm">
      {MODES.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onChange(item.value)}
          className={clsx(
            "rounded px-2.5 py-1 text-sm font-medium transition",
            mode === item.value ? "bg-blue-600 text-white" : "text-gray-300 hover:bg-gray-800"
          )}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
