import type { SearchHit } from "../api/search";
import { SearchResultItem } from "./SearchResultItem";

interface Props {
  hits: SearchHit[];
  selectedIndex: number;
  isLoading: boolean;
  onSelect: (index: number) => void;
  setItemRef: (index: number, element: HTMLElement | null) => void;
}

export function SearchResultList({ hits, selectedIndex, isLoading, onSelect, setItemRef }: Props) {
  return (
    <div className="space-y-3">
      {hits.map((hit, index) => (
        <SearchResultItem
          key={hit.file_id}
          hit={hit}
          selected={selectedIndex === index}
          onSelect={() => onSelect(index)}
          setRef={(element) => setItemRef(index, element)}
        />
      ))}
      {!hits.length && !isLoading && (
        <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
          検索結果がありません。
        </div>
      )}
    </div>
  );
}
