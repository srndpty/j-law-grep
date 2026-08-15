import json
from argparse import Namespace

import pytest

from indexer.manifest import build_manifest, document_stats
from indexer.pipeline import collect_records, to_index_actions
from indexer.shuisho_importer import (
    HttpNotFound,
    build_document,
    decode_html,
    kanji_to_int,
    parse_body,
    parse_sangiin_list,
    parse_shugiin_list,
    run_fetch,
    sangiin_list_url,
    shugiin_list_url,
    wareki_to_iso,
)

SHUGIIN_LIST_HTML = """
<HTML><HEAD><meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS"></HEAD><BODY>
<TABLE>
<TR VALIGN="TOP"><TH id="SHITSUMON.NUMBER">番号</TH><TH id="SHITSUMON.KENMEI">質問件名</TH></TR>
<TR VALIGN=top><TD CLASS="TD" headers="SHITSUMON.NUMBER" ALIGN="RIGHT"><span>1</span></TD>
<TD CLASS="TD" headers="SHITSUMON.KENMEI"><span>創薬力強化に関する質問主意書</span></TD>
<TD CLASS="TD" headers="SHITSUMON.TEISHUTSUSHA"><span>福田玄君</span></TD>
<TD CLASS="TD" headers="SHITSUMON.STATUS"><span>答弁受理</span></TD>
<TD CLASS="TD" headers="SHITSUMON.KLINK"><span><A HREF="217001.htm">経過</A></span></TD>
<TD CLASS="TD" headers="SHITSUMON.SLINK"><span><A HREF="a217001.htm">質問</A></span></TD>
<TD CLASS="TD" headers="SHITSUMON.SLINKPDF"><span><A HREF="../../../itdb_shitsumon_pdf_s.nsf/html/shitsumon/pdfS/a217001.pdf/$File/a217001.pdf">PDF</A></span></TD>
<TD CLASS="TD" headers="SHITSUMON.TLINK"><span><A HREF="b217001.htm">答弁</A></span></TD>
<TD CLASS="TD" headers="SHITSUMON.TLINKPDF"><span><A HREF="../../../itdb_shitsumon_pdf_t.nsf/html/shitsumon/pdfT/b217001.pdf/$File/b217001.pdf">PDF</A></span></TD></TR>
<TR VALIGN=top><TD CLASS="TD" headers="SHITSUMON.NUMBER" ALIGN="RIGHT"><span>2</span></TD>
<TD CLASS="TD" headers="SHITSUMON.KENMEI"><span>答弁待ちに関する質問主意書</span></TD>
<TD CLASS="TD" headers="SHITSUMON.TEISHUTSUSHA"><span>山田太郎君</span></TD>
<TD CLASS="TD" headers="SHITSUMON.STATUS"><span>転送</span></TD>
<TD CLASS="TD" headers="SHITSUMON.SLINK"><span><A HREF="a217002.htm">質問</A></span></TD>
<TD CLASS="TD" headers="SHITSUMON.TLINK"><span>&nbsp;</span></TD></TR>
</TABLE></BODY></HTML>
"""

SHUGIIN_QUESTION_HTML = """
<HTML><HEAD><meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">
<TITLE>創薬力強化に関する質問主意書</TITLE></HEAD><BODY>
<H1 class="txt05" id="TopContents">質問本文情報</H1>
<DIV class="gh21divr"><A HREF="217001.htm">経過へ</A></DIV>
令和七年一月二十四日提出<BR>
質問第一号<BR>
<P>創薬力強化に関する質問主意書<BR></P>
<DIV class="gh21divr">提出者　　福田　玄</DIV>
<HR>
<BR>
創薬力強化に関する質問主意書<BR>
<BR>
　政府は、ドラッグロスの発生に対応するため、以下質問いたします。<BR>
<BR>
一　創薬力強化機構の設立時期を示されたい。<BR>
<BR><BR>
<DIV class="gh21divr"><A HREF="217001.htm">経過へ</A></DIV>
</BODY></HTML>
"""

SHUGIIN_ANSWER_HTML = """
<HTML><HEAD><meta http-equiv="Content-Type" content="text/html; charset=Shift_JIS">
<TITLE>答弁本文情報</TITLE></HEAD><BODY>
<H1 class="txt05" id="TopContents">答弁本文情報</H1>
令和七年二月四日受領<BR>
答弁第一号<BR>
<BR>
　　内閣衆質二一七第一号<BR>
　　令和七年二月四日<BR>
<DIV class="gh22divr">内閣総理大臣　石破　茂</DIV>
<HR>
<BR>
衆議院議員福田玄君提出創薬力強化に関する質問に対する答弁書<BR>
<BR>
一について<BR>
<BR>
　お尋ねについてお答えすることは困難である。<BR>
<BR>
<DIV class="gh22divr"><A HREF="217001.htm">経過へ</A></DIV>
</BODY></HTML>
"""

SANGIIN_LIST_HTML = """
<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head><body>
<table class="list_c">
<tr><th scope="col" id="t1">提出番号</th><th scope="row">件名</th>
<td colspan="3" class="ta_l"><a href="meisai/m217001.htm" class="Graylink">
土地利用状況に関する質問主意書</a></td></tr>
<tr><td headers="t1" rowspan="2">1</td>
<th scope="row" rowspan="2">提出者</th>
<td rowspan="2" class="ta_l">神谷　　宗幣君</td>
<td><a href="syuh/s217001.htm" class="Graylink">質問本文（html）</a></td>
<td><a href="touh/t217001.htm" class="Graylink">答弁本文（html）</a></td></tr>
<tr><td><a href="syup/s217001.pdf" class="Graylink">質問本文（PDF）</a></td>
<td><a href="toup/t217001.pdf" class="Graylink">答弁本文（PDF）</a></td></tr>
<tr><th scope="col" id="t2">提出番号</th><th scope="row">件名</th>
<td colspan="3" class="ta_l"><a href="meisai/m217002.htm" class="Graylink">
未答弁に関する質問主意書</a></td></tr>
<tr><td headers="t2" rowspan="2">2</td>
<th scope="row" rowspan="2">提出者</th>
<td rowspan="2" class="ta_l">田中　　花子君</td>
<td><a href="syuh/s217002.htm" class="Graylink">質問本文（html）</a></td></tr>
</table></body></html>
"""

SANGIIN_QUESTION_HTML = """
<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8"></head><body>
<div id="ContentsBox">
<h2 class="title_text">質問主意書</h2>
<TABLE><TR><TD ALIGN="LEFT">
質問第一号<BR>
<BR>
土地利用状況に関する質問主意書<BR>
<BR>
令和七年一月二十四日<BR>
<DIV ALIGN="RIGHT">神谷 宗幣</DIV>
<HR>
<BR>
土地利用状況に関する質問主意書<BR>
<BR>
一　千メートルとした根拠を明らかにされたい。<BR>
<BR>
　　右質問する。<BR>
</TD></TR></TABLE>
</div></body></html>
"""


def _args(tmp_path, **overrides) -> Namespace:
    args = Namespace(
        output=tmp_path,
        house="shugiin",
        session_from=217,
        session_to=217,
        limit_discovered=None,
        limit_fetched=None,
        delay_seconds=0,
        retries=0,
        retry_backoff_seconds=0,
        checkpoint_every=50,
        state_file=None,
        errors_file=None,
        overwrite=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _stub_fetcher(pages: dict[str, str]):
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        if url not in pages:
            raise HttpNotFound(f"HTTP 404: {url}")
        return pages[url]

    return fetch, calls


def _shugiin_pages() -> dict[str, str]:
    base = "https://www.shugiin.go.jp/internet/itdb_shitsumon.nsf/html/shitsumon/"
    return {
        shugiin_list_url(217): SHUGIIN_LIST_HTML,
        f"{base}a217001.htm": SHUGIIN_QUESTION_HTML,
        f"{base}b217001.htm": SHUGIIN_ANSWER_HTML,
        f"{base}a217002.htm": SHUGIIN_QUESTION_HTML,
    }


@pytest.mark.parametrize(
    ("text", "expected"),
    [("一", 1), ("十", 10), ("二十四", 24), ("三十一", 31), ("元", 1), ("7", 7), ("", None)],
)
def test_kanji_to_int(text, expected):
    assert kanji_to_int(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("令和七年二月四日受領", "2025-02-04"),
        ("平成二十四年十月一日", "2012-10-01"),
        ("令和元年五月一日", "2019-05-01"),
        ("昭和六十三年十二月三十一日", "1988-12-31"),
        ("日付なし", ""),
    ],
)
def test_wareki_to_iso(text, expected):
    assert wareki_to_iso(text) == expected


def test_decode_html_reads_shift_jis_by_declared_charset():
    raw = SHUGIIN_QUESTION_HTML.encode("cp932")
    assert "創薬力強化に関する質問主意書" in decode_html(raw)


def test_decode_html_falls_back_when_charset_missing():
    assert decode_html("答弁書".encode()) == "答弁書"


def test_parse_shugiin_list_reads_cells_by_header_attribute():
    entries = parse_shugiin_list(SHUGIIN_LIST_HTML, 217, shugiin_list_url(217))

    assert [entry.number for entry in entries] == [1, 2]
    first = entries[0]
    assert first.shuisho_id == "shugiin-217-001"
    assert first.title == "創薬力強化に関する質問主意書"
    assert first.submitter == "福田玄"
    assert first.status == "答弁受理"
    assert first.question_url.endswith("/shitsumon/a217001.htm")
    assert first.answer_url.endswith("/shitsumon/b217001.htm")
    assert "pdfS/a217001.pdf" in first.question_pdf_url
    # 答弁未受理の件は答弁リンクが無い。
    assert entries[1].answer_url == ""


def test_parse_sangiin_list_reads_entries_by_detail_link():
    entries = parse_sangiin_list(SANGIIN_LIST_HTML, 217, sangiin_list_url(217))

    assert [entry.number for entry in entries] == [1, 2]
    first = entries[0]
    assert first.shuisho_id == "sangiin-217-001"
    assert first.title == "土地利用状況に関する質問主意書"
    assert first.submitter == "神谷宗幣"
    assert first.question_url.endswith("/217/syuh/s217001.htm")
    assert first.answer_url.endswith("/217/touh/t217001.htm")
    assert first.answer_pdf_url.endswith("/217/toup/t217001.pdf")
    assert entries[1].answer_url == ""


def test_parse_body_splits_paragraphs_after_the_rule():
    body = parse_body(SHUGIIN_QUESTION_HTML)

    assert body.date == "2025-01-24"
    assert body.paragraphs == [
        "創薬力強化に関する質問主意書",
        "政府は、ドラッグロスの発生に対応するため、以下質問いたします。",
        "一 創薬力強化機構の設立時期を示されたい。",
    ]
    # 末尾のナビゲーションは本文に混ぜない。
    assert not any("経過へ" in paragraph for paragraph in body.paragraphs)


def test_parse_body_reads_answer_metadata():
    body = parse_body(SHUGIIN_ANSWER_HTML)

    assert body.date == "2025-02-04"
    assert body.answerer == "内閣総理大臣 石破 茂"
    assert body.cabinet_number == "内閣衆質二一七第一号"
    assert body.paragraphs[-1] == "お尋ねについてお答えすることは困難である。"


def test_parse_body_handles_sangiin_layout():
    body = parse_body(SANGIIN_QUESTION_HTML)

    assert body.date == "2025-01-24"
    assert body.paragraphs[0] == "土地利用状況に関する質問主意書"
    assert body.paragraphs[-1] == "右質問する。"


def test_parse_body_without_rule_returns_empty():
    assert parse_body("<html><body>本文なし</body></html>").paragraphs == []


def test_run_fetch_writes_documents_and_records_missing_bodies(tmp_path):
    fetch, calls = _stub_fetcher(_shugiin_pages())

    stats = run_fetch(_args(tmp_path), fetcher=fetch)

    assert stats.discovered == 2
    assert stats.fetched == 2
    assert stats.failed == 0
    document = json.loads((tmp_path / "shugiin-217-001.json").read_text(encoding="utf-8"))
    assert document["source_type"] == "shuisho"
    assert document["house"] == "衆議院"
    assert document["session"] == "217"
    assert document["question"]["date"] == "2025-01-24"
    assert document["answer"]["answerer"] == "内閣総理大臣 石破 茂"
    # 答弁が未受理の件は answer が無いまま質問だけ保存される。
    pending = json.loads((tmp_path / "shugiin-217-002.json").read_text(encoding="utf-8"))
    assert pending["answer"] is None
    assert shugiin_list_url(217) in calls


def test_run_fetch_skips_already_fetched_entries(tmp_path):
    fetch, _ = _stub_fetcher(_shugiin_pages())
    run_fetch(_args(tmp_path), fetcher=fetch)

    fetch_again, calls = _stub_fetcher(_shugiin_pages())
    stats = run_fetch(_args(tmp_path), fetcher=fetch_again)

    assert stats.skipped == 2
    assert stats.fetched == 0
    # 一覧ページだけ引き直し、本文は取りに行かない。
    assert calls == [shugiin_list_url(217)]


def test_run_fetch_records_missing_session_and_continues(tmp_path):
    fetch, _ = _stub_fetcher(_shugiin_pages())

    stats = run_fetch(_args(tmp_path, session_from=216, session_to=217), fetcher=fetch)

    assert stats.fetched == 2
    errors = (tmp_path / "_fetch_errors.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(errors[0])["session"] == 216


def test_run_fetch_fails_entry_without_any_html_body(tmp_path):
    pages = _shugiin_pages()
    del pages["https://www.shugiin.go.jp/internet/itdb_shitsumon.nsf/html/shitsumon/a217002.htm"]
    fetch, _ = _stub_fetcher(pages)

    stats = run_fetch(_args(tmp_path), fetcher=fetch)

    assert stats.fetched == 1
    assert stats.failed == 1
    assert not (tmp_path / "shugiin-217-002.json").exists()
    errors = (tmp_path / "_fetch_errors.jsonl").read_text(encoding="utf-8")
    assert "no HTML body available" in errors


def test_pipeline_expands_paragraphs_into_records(tmp_path):
    entry = parse_shugiin_list(SHUGIIN_LIST_HTML, 217, shugiin_list_url(217))[0]
    document = build_document(
        entry, parse_body(SHUGIIN_QUESTION_HTML), parse_body(SHUGIIN_ANSWER_HTML)
    )
    (tmp_path / f"{entry.shuisho_id}.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )

    records = collect_records(tmp_path)

    assert [record.article_no for record in records] == ["q1", "q2", "q3", "a1", "a2", "a3"]
    assert {record.source_type for record in records} == {"shuisho"}
    question = records[0]
    assert question.shuisho_kind == "question"
    assert question.law_name == "創薬力強化に関する質問主意書"
    assert question.speaker == "福田玄"
    assert question.date == "2025-01-24"
    assert question.house == "衆議院"
    assert question.path == "質問主意書/衆議院/第217回/第1号/質問本文/1"
    answer = records[-1]
    assert answer.shuisho_kind == "answer"
    assert answer.speaker == "内閣総理大臣 石破 茂"
    assert answer.date == "2025-02-04"
    assert answer.url.endswith("b217001.htm")


def test_index_actions_are_unique_across_question_and_answer(tmp_path):
    entry = parse_shugiin_list(SHUGIIN_LIST_HTML, 217, shugiin_list_url(217))[0]
    # 質問と答弁で本文が同一でも、article_no の接頭辞で doc id が衝突しない。
    same_body = parse_body(SHUGIIN_QUESTION_HTML)
    document = build_document(entry, same_body, same_body)
    (tmp_path / f"{entry.shuisho_id}.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )

    actions = list(to_index_actions(collect_records(tmp_path)))

    assert len({action["_id"] for action in actions}) == len(actions) == 6
    assert actions[0]["_source"]["shuisho_kind"] == "question"
    assert actions[0]["_source"]["shuisho_number"] == "1"
    assert actions[-1]["_source"]["shuisho_kind"] == "answer"


def test_manifest_counts_shuisho_paragraphs(tmp_path):
    entry = parse_shugiin_list(SHUGIIN_LIST_HTML, 217, shugiin_list_url(217))[0]
    document = build_document(
        entry, parse_body(SHUGIIN_QUESTION_HTML), parse_body(SHUGIIN_ANSWER_HTML)
    )
    assert document_stats(document) == (2, 6)

    (tmp_path / f"{entry.shuisho_id}.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    manifest = build_manifest(tmp_path, source="shuisho-scrape")

    assert manifest["counts"] == {"laws": 1, "articles": 2, "records": 6}
    assert manifest["laws"][0]["law_id"] == "shugiin-217-001"
    assert manifest["laws"][0]["source_type"] == "shuisho"
