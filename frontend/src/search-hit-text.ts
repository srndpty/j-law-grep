import { fetchLawDocument, type LawDocument, type LawSection, type SearchHit } from "./api/search";

export function deriveArticleNo(hit: SearchHit): string {
  if (hit.article_no) return hit.article_no;
  const urlMatch = hit.url.match(/\/a\/([^/]+)/);
  if (urlMatch) return urlMatch[1];
  const parts = hit.path.split("/");
  if (parts.length >= 2 && parts[1]) return parts[1];
  return "";
}

export function deriveParagraphNo(hit: SearchHit): number | string | null {
  if (hit.paragraph_no !== null && hit.paragraph_no !== undefined) return hit.paragraph_no;
  const match = hit.url.match(/\/a\/[^/]+\/(\d+)/);
  if (match) {
    const value = Number(match[1]);
    return Number.isNaN(value) ? null : value;
  }
  return null;
}

export function formatLocation(hit: SearchHit): string {
  const base = hit.law_name || hit.path;
  const segments: string[] = [];
  const articleNo = deriveArticleNo(hit);
  const paragraphNo = deriveParagraphNo(hit);
  if (articleNo) {
    segments.push(articleNo.includes("条") ? articleNo : `第${articleNo}条`);
  }
  if (paragraphNo) segments.push(`${paragraphNo}項`);
  if (hit.item_no) segments.push(`${hit.item_no}号`);
  const position = segments.join(" ");
  if (base && position) return `${base} / ${position}`;
  return base || position || hit.path;
}

function blockText(block: Record<string, unknown>): string {
  for (const key of ["text", "html", "content"]) {
    const value = block[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

export function hitText(hit: SearchHit): string {
  const blockTexts = hit.blocks.map(blockText).filter(Boolean);
  if (blockTexts.length) return blockTexts.join("\n\n");
  return hit.snippet_text ?? hit.snippet;
}

function sectionLabel(section: LawSection): string {
  const segments: string[] = [];
  if (section.article_no) {
    segments.push(
      section.article_no.includes("条") ? section.article_no : `第${section.article_no}条`
    );
  }
  if (section.paragraph_no) segments.push(`${section.paragraph_no}項`);
  if (section.item_no) segments.push(`${section.item_no}号`);
  return segments.join(" ");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function targetId(hit: SearchHit): string {
  return sectionId({
    article_no: hit.article_no,
    paragraph_no: hit.paragraph_no,
    item_no: hit.item_no,
  });
}

function sectionId(section: Pick<LawSection, "article_no" | "paragraph_no" | "item_no">): string {
  return ["section", section.article_no || "", section.paragraph_no ?? "", section.item_no ?? ""]
    .map((part) => encodeURIComponent(String(part)))
    .join("-");
}

function renderLawDocument(document: LawDocument, hit: SearchHit): string {
  const activeId = targetId(hit);
  const sections = document.sections
    .map((section) => {
      const id = sectionId(section);
      const active = id === activeId;
      const heading = section.heading
        ? `<div class="heading">${escapeHtml(section.heading)}</div>`
        : "";
      return `
        <section id="${id}" class="section ${active ? "active" : ""}">
          <div class="label">${escapeHtml(sectionLabel(section))}</div>
          ${heading}
          <p>${escapeHtml(section.text).replace(/\n/g, "<br>")}</p>
        </section>`;
    })
    .join("");

  return `<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(document.law_name || hit.law_name)}</title>
  <style>
    body {
      margin: 0;
      background: #f5f6f8;
      color: #171717;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.75;
    }
    header {
      position: sticky;
      top: 0;
      background: #111418;
      color: white;
      padding: 16px 28px;
      border-bottom: 1px solid #2b3036;
      z-index: 1;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }
    main {
      max-width: 960px;
      margin: 0 auto;
      padding: 24px 28px 56px;
    }
    .section {
      scroll-margin-top: 88px;
      border-left: 4px solid transparent;
      border-bottom: 1px solid #ddd;
      background: white;
      padding: 16px 18px;
    }
    .section.active {
      border-left-color: #2563eb;
      background: #eff6ff;
      box-shadow: inset 0 0 0 1px #93c5fd;
    }
    .label {
      color: #4b5563;
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 6px;
    }
    .heading {
      font-weight: 700;
      margin-bottom: 6px;
    }
    p {
      margin: 0;
      white-space: normal;
    }
  </style>
</head>
<body>
  <header><h1>${escapeHtml(document.law_name || hit.law_name)}</h1></header>
  <main>${sections}</main>
  <script>
    document.getElementById(${JSON.stringify(activeId)})?.scrollIntoView({ block: "center" });
  </script>
</body>
</html>`;
}

function writeLoading(tab: Window, hit: SearchHit) {
  tab.document.open();
  tab.document.write(
    `<!doctype html><meta charset="utf-8"><title>${escapeHtml(
      hit.law_name || "読み込み中"
    )}</title><body style="font-family: sans-serif; padding: 24px;">読み込み中...</body>`
  );
  tab.document.close();
}

function writeError(tab: Window, message: string) {
  tab.document.open();
  tab.document.write(`<!doctype html><meta charset="utf-8"><title>読み込みエラー</title>
    <body style="font-family: sans-serif; padding: 24px;">
      <h1>法律全文を開けませんでした</h1>
      <p>${escapeHtml(message)}</p>
    </body>`);
  tab.document.close();
}

export async function openLawDocument(hit: SearchHit) {
  const tab = window.open("about:blank", "_blank");
  if (!tab) return;
  tab.opener = null;
  writeLoading(tab, hit);
  try {
    if (!hit.law_id) throw new Error("検索結果に law_id が含まれていません。");
    const document = await fetchLawDocument(hit.law_id);
    tab.document.open();
    tab.document.write(renderLawDocument(document, hit));
    tab.document.close();
  } catch (err) {
    writeError(tab, err instanceof Error ? err.message : "不明なエラーです。");
  }
}
