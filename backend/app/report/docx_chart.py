"""워드(DOCX) 안에 **네이티브 차트**를 넣는다 — 사용자가 워드에서 '데이터 편집'으로 숫자를 고치면 그래프가 다시 그려진다.

python-docx 는 차트를 지원하지 않아 OOXML 부품을 직접 만든다(새 라이브러리 없이):
  /word/charts/chartN.xml            DrawingML 차트(c:chartSpace) — 값은 numCache/strCache 에 넣어 워드가 바로 그린다
  /word/embeddings/…N.xlsx           차트 데이터 원본(openpyxl) — '데이터 편집'이 여는 통합 문서
  document.xml 의 w:drawing/wp:inline 이 차트 부품을 가리킨다.
문서 양식의 차트 양식으로 만든 차트(색·막대+선 보조축·밴드·영역·원)는 chart_xml_form 이 그린다 — 기본 막대·꺾은선은 chart_xml 그대로.
"""
from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from docx.opc.constants import CONTENT_TYPE as CT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml import parse_xml
from docx.shared import Cm
from docx.text.paragraph import Paragraph
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SHEET = "Sheet1"
PALETTE = ["1F3A5F", "7A9CC6", "C9A227", "8C8C8C"]


def _workbook(categories: Sequence[str], series: Sequence[Tuple[str, Sequence[float]]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.cell(row=1, column=1, value="")
    for j, (name, values) in enumerate(series, start=2):
        ws.cell(row=1, column=j, value=name)
        for i, v in enumerate(values, start=2):
            ws.cell(row=i, column=j, value=v)
    for i, c in enumerate(categories, start=2):
        ws.cell(row=i, column=1, value=c)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _str_cache(values: Sequence[str]) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{escape(str(v))}</c:v></c:pt>' for i, v in enumerate(values))
    return f'<c:strCache><c:ptCount val="{len(values)}"/>{pts}</c:strCache>'


def _num_cache(values: Sequence[float], fmt: str) -> str:
    pts = "".join(f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>' for i, v in enumerate(values) if v is not None)
    return f'<c:numCache><c:formatCode>{escape(fmt)}</c:formatCode><c:ptCount val="{len(values)}"/>{pts}</c:numCache>'


def _text_props(size: int = 900) -> str:
    return (
        f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{size}"><a:solidFill><a:srgbClr val="404040"/></a:solidFill>'
        '<a:latin typeface="맑은 고딕"/><a:ea typeface="맑은 고딕"/></a:defRPr></a:pPr><a:endParaRPr lang="ko-KR"/></a:p></c:txPr>'
    )


def chart_xml(categories: Sequence[str], series: Sequence[Tuple[str, Sequence[float]]], *, horizontal: bool, number_format: str, embed_rid: str, kind: str = "bar") -> str:
    """kind = bar(막대, horizontal 이면 가로) | line(꺾은선 — 점 표시·값 위에)."""
    n = len(categories)
    last = n + 1
    cat_ref = f"{SHEET}!$A$2:$A${last}"
    line = kind == "line"
    horizontal = horizontal and not line
    sers = []
    for k, (name, values) in enumerate(series):
        col = get_column_letter(k + 2)
        color = PALETTE[k % len(PALETTE)]
        if line:
            look = (
                f'<c:spPr><a:ln w="22225" cap="rnd"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:round/></a:ln></c:spPr>'
                f'<c:marker><c:symbol val="circle"/><c:size val="5"/><c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:marker>'
            )
        else:
            look = f'<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr><c:invertIfNegative val="0"/>'
        sers.append(
            f'<c:ser><c:idx val="{k}"/><c:order val="{k}"/>'
            f'<c:tx><c:strRef><c:f>{SHEET}!${col}$1</c:f>{_str_cache([name])}</c:strRef></c:tx>'
            + look
            + f'<c:dLbls><c:numFmt formatCode="{escape(number_format)}" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>{_text_props(800)}'
            f'<c:dLblPos val="{"t" if line else "outEnd"}"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/>'
            '<c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>'
            f'<c:cat><c:strRef><c:f>{cat_ref}</c:f>{_str_cache(categories)}</c:strRef></c:cat>'
            f'<c:val><c:numRef><c:f>{SHEET}!${col}$2:${col}${last}</c:f>{_num_cache(list(values), number_format)}</c:numRef></c:val>'
            + ('<c:smooth val="0"/>' if line else "")
            + "</c:ser>"
        )
    if line:
        plot = '<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>' + "".join(sers) + '<c:marker val="1"/><c:axId val="500000001"/><c:axId val="500000002"/></c:lineChart>'
    else:
        plot = (
            f'<c:barChart><c:barDir val="{"bar" if horizontal else "col"}"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
            + "".join(sers)
            + '<c:gapWidth val="60"/><c:axId val="500000001"/><c:axId val="500000002"/></c:barChart>'
        )
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/>' + _text_props() + "</c:legend>" if len(series) > 1 else ""
    no_line = '<c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="BFBFBF"/></a:solidFill></a:ln></c:spPr>'
    grid = '<c:majorGridlines><c:spPr><a:ln w="3175"><a:solidFill><a:srgbClr val="E5E5E5"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{NS_C}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
        '<c:roundedCorners val="0"/>'
        '<c:chart><c:autoTitleDeleted val="1"/><c:plotArea><c:layout/>'
        + plot
        + f'<c:catAx><c:axId val="500000001"/><c:scaling><c:orientation val="{"maxMin" if horizontal else "minMax"}"/></c:scaling><c:delete val="0"/>'
        f'<c:axPos val="{"l" if horizontal else "b"}"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
        # c:crosses = 이 축이 상대 축의 어디에 그려지는가. 범주 축은 값 0 에서(막대가 0 에서 시작),
        # 가로 막대는 범주 순서를 뒤집어(위에서 아래로) 두므로 값 축을 '마지막 범주' 쪽(=아래)에 그린다
        f'<c:tickLblPos val="low"/>{no_line}{_text_props()}<c:crossAx val="500000002"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
        f'<c:valAx><c:axId val="500000002"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="{"b" if horizontal else "l"}"/>{grid}'
        f'<c:numFmt formatCode="{escape(number_format)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
        f'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>{_text_props()}<c:crossAx val="500000001"/><c:crosses val="{"max" if horizontal else "autoZero"}"/><c:crossBetween val="between"/></c:valAx>'
        '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr></c:plotArea>'
        f'{legend}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
        '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
        f'{_text_props()}'
        f'<c:externalData r:id="{embed_rid}"><c:autoUpdate val="0"/></c:externalData>'
        "</c:chartSpace>"
    )


AX = {"left": ("500000001", "500000002"), "right": ("500000003", "500000004")}
LEGEND_POS = {"top": "t", "bottom": "b", "right": "r"}


def _form_ser(k: int, name: str, values: Sequence[Optional[float]], categories: Sequence[str], *, family: str, color: str, colors: Sequence[str], number_format: str, labels: bool, dashed: bool, markers: bool) -> str:
    """양식 차트의 계열 하나 — family = bar | line | area | pie(점마다 색). 요소 순서는 계열 종류마다 스키마 순서대로."""
    col = get_column_letter(k + 2)
    last = len(categories) + 1
    head = f'<c:idx val="{k}"/><c:order val="{k}"/><c:tx><c:strRef><c:f>{SHEET}!${col}$1</c:f>{_str_cache([name])}</c:strRef></c:tx>'
    data = (
        f'<c:cat><c:strRef><c:f>{SHEET}!$A$2:$A${last}</c:f>{_str_cache(categories)}</c:strRef></c:cat>'
        f'<c:val><c:numRef><c:f>{SHEET}!${col}$2:${col}${last}</c:f>{_num_cache(list(values), number_format)}</c:numRef></c:val>'
    )
    pos = {"bar": "outEnd", "line": "t", "pie": "bestFit"}.get(family)
    dlbls = (
        f'<c:dLbls><c:numFmt formatCode="{escape(number_format)}" sourceLinked="0"/><c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>{_text_props(800)}'
        + (f'<c:dLblPos val="{pos}"/>' if pos else "")
        + '<c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>'
        if labels
        else ""
    )
    if family == "bar":
        return f'<c:ser>{head}<c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></c:spPr><c:invertIfNegative val="0"/>{dlbls}{data}</c:ser>'
    if family == "area":
        return f'<c:ser>{head}<c:spPr><a:solidFill><a:srgbClr val="{color}"><a:alpha val="45000"/></a:srgbClr></a:solidFill><a:ln w="15875"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill></a:ln></c:spPr>{dlbls}{data}</c:ser>'
    if family == "pie":
        pts = "".join(f'<c:dPt><c:idx val="{i}"/><c:bubble3D val="0"/><c:spPr><a:solidFill><a:srgbClr val="{colors[i % len(colors)]}"/></a:solidFill><a:ln w="12700"><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln></c:spPr></c:dPt>' for i in range(len(categories)))
        return f'<c:ser>{head}{pts}{dlbls}{data}</c:ser>'
    dash = '<a:prstDash val="dash"/>' if dashed else ""
    marker = (
        f'<c:marker><c:symbol val="circle"/><c:size val="5"/><c:spPr><a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr></c:marker>'
        if markers and not dashed
        else '<c:marker><c:symbol val="none"/></c:marker>'
    )
    return f'<c:ser>{head}<c:spPr><a:ln w="{12700 if dashed else 22225}" cap="rnd"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>{dash}<a:round/></a:ln></c:spPr>{marker}{dlbls}{data}<c:smooth val="0"/></c:ser>'


def chart_xml_form(
    categories: Sequence[str],
    series: Sequence[Tuple[str, Sequence[Optional[float]]]],
    meta: Sequence[Dict[str, Any]],
    *,
    kind: str,
    horizontal: bool,
    number_format: str,
    embed_rid: str,
    colors: Sequence[str],
    labels: Optional[bool],
    legend: str,
    grid: bool,
) -> str:
    """양식 차트 — kind = bar | line | area | pie | combo(계열마다 막대/선, 오른쪽 축) | band(첫 계열 + 계산 띠선 점선).
    meta[k] = {type?, axis?, computed?}. colors = 'RRGGBB' 목록(양식 색)."""
    n = len(categories)
    palette = [c.lstrip("#").upper() for c in colors] or PALETTE
    labels = (n <= 12 and kind not in ("band", "area")) if labels is None else labels
    markers = n <= 24
    horizontal = horizontal and kind == "bar"
    groups: Dict[Tuple[str, str], List[str]] = {}
    for k, (name, values) in enumerate(series):
        m = meta[k] if k < len(meta) else {}
        if kind == "pie":
            family = "pie"
        elif kind == "combo":
            family = m.get("type") if m.get("type") in ("bar", "line", "area") else "bar"
        elif kind == "band":
            family = "line"
        else:
            family = kind if kind in ("bar", "line", "area") else "bar"
        axis = "right" if kind == "combo" and m.get("axis") == "right" else "left"
        # 밴드의 계산 띠선은 한 색(양식의 둘째 색, 없으면 회색) — 주 계열과 구분
        color = (palette[1] if len(palette) > 1 else "A6A6A6") if m.get("computed") else palette[k % len(palette)]
        ser = _form_ser(k, name, values, categories, family=family, color=color, colors=palette, number_format=number_format, labels=labels and not m.get("computed"), dashed=bool(m.get("computed")), markers=markers)
        groups.setdefault((family, axis), []).append(ser)
    plots = []
    for (family, axis), sers in groups.items():
        ids = "".join(f'<c:axId val="{a}"/>' for a in AX[axis])
        body = "".join(sers)
        if family == "bar":
            plots.append(f'<c:barChart><c:barDir val="{"bar" if horizontal else "col"}"/><c:grouping val="clustered"/><c:varyColors val="0"/>{body}<c:gapWidth val="60"/>{ids}</c:barChart>')
        elif family == "line":
            plots.append(f'<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>{body}<c:marker val="1"/>{ids}</c:lineChart>')
        elif family == "area":
            plots.append(f'<c:areaChart><c:grouping val="standard"/><c:varyColors val="0"/>{body}{ids}</c:areaChart>')
        else:
            plots.append(f'<c:pieChart><c:varyColors val="1"/>{body}<c:firstSliceAng val="0"/></c:pieChart>')
    no_line = '<c:spPr><a:ln w="6350"><a:solidFill><a:srgbClr val="BFBFBF"/></a:solidFill></a:ln></c:spPr>'
    gridline = '<c:majorGridlines><c:spPr><a:ln w="3175"><a:solidFill><a:srgbClr val="E5E5E5"/></a:solidFill></a:ln></c:spPr></c:majorGridlines>' if grid else ""
    axes = ""
    if kind != "pie":
        axes = (
            f'<c:catAx><c:axId val="{AX["left"][0]}"/><c:scaling><c:orientation val="{"maxMin" if horizontal else "minMax"}"/></c:scaling><c:delete val="0"/>'
            f'<c:axPos val="{"l" if horizontal else "b"}"/><c:numFmt formatCode="General" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
            f'<c:tickLblPos val="low"/>{no_line}{_text_props()}<c:crossAx val="{AX["left"][1]}"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
            f'<c:valAx><c:axId val="{AX["left"][1]}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="{"b" if horizontal else "l"}"/>{gridline}'
            f'<c:numFmt formatCode="{escape(number_format)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
            f'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>{_text_props()}<c:crossAx val="{AX["left"][0]}"/><c:crosses val="{"max" if horizontal else "autoZero"}"/><c:crossBetween val="between"/></c:valAx>'
        )
        if any(axis == "right" for _f, axis in groups):
            # 오른쪽 축 — 범주 축은 숨기고(왼쪽 것과 같다) 값 축만 오른쪽에
            axes += (
                f'<c:catAx><c:axId val="{AX["right"][0]}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="1"/><c:axPos val="b"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/>'
                f'<c:tickLblPos val="nextTo"/><c:crossAx val="{AX["right"][1]}"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/><c:noMultiLvlLbl val="0"/></c:catAx>'
                f'<c:valAx><c:axId val="{AX["right"][1]}"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="r"/>'
                f'<c:numFmt formatCode="{escape(number_format)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
                f'<c:spPr><a:ln><a:noFill/></a:ln></c:spPr>{_text_props()}<c:crossAx val="{AX["right"][0]}"/><c:crosses val="max"/><c:crossBetween val="between"/></c:valAx>'
            )
    pos = LEGEND_POS.get(legend) or ("r" if kind == "band" else "" if legend == "none" else "b")  # 밴드는 띠선이 무엇인지 범례로
    show_legend = pos and (len(series) > 1 or kind == "pie")
    legend_xml = f'<c:legend><c:legendPos val="{pos}"/><c:overlay val="0"/>{_text_props()}</c:legend>' if show_legend else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<c:chartSpace xmlns:c="{NS_C}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">'
        '<c:roundedCorners val="0"/>'
        '<c:chart><c:autoTitleDeleted val="1"/><c:plotArea><c:layout/>'
        + "".join(plots)
        + axes
        + '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr></c:plotArea>'
        f'{legend_xml}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
        '<c:spPr><a:noFill/><a:ln><a:noFill/></a:ln></c:spPr>'
        f'{_text_props()}'
        f'<c:externalData r:id="{embed_rid}"><c:autoUpdate val="0"/></c:externalData>'
        "</c:chartSpace>"
    )


def _next_index(package) -> int:
    used = [str(p.partname) for p in package.iter_parts() if str(p.partname).startswith("/word/charts/chart")]
    return len(used) + 1


def add_bar_chart(
    paragraph: Paragraph,
    *,
    categories: Sequence[str],
    series: Sequence[Tuple[str, Sequence[float]]],
    horizontal: bool = False,
    number_format: str = "0.0",
    width: Cm = Cm(15.5),
    height: Cm = Cm(7.5),
) -> None:
    """문단에 막대 그래프 하나(계열 여러 개 가능). 값이 없는 칸은 None."""
    add_chart(paragraph, categories=categories, series=series, horizontal=horizontal, number_format=number_format, width=width, height=height)


def add_chart(
    paragraph: Paragraph,
    *,
    categories: Sequence[str],
    series: Sequence[Tuple[str, Sequence[float]]],
    kind: str = "bar",
    horizontal: bool = False,
    number_format: str = "0.0",
    width: Cm = Cm(15.5),
    height: Cm = Cm(7.5),
    form: Optional[Dict[str, Any]] = None,
) -> None:
    """문단에 차트 하나 — kind = bar | line(기본 모양). form 을 주면(문서 양식의 차트 양식) chart_xml_form —
    form = {meta: [계열마다 {type, axis, computed}], colors, labels, legend, grid}, kind 는 bar | line | area | pie | combo | band."""
    doc_part = paragraph.part
    package = doc_part.package
    n = _next_index(package)
    xlsx = Part(PackURI(f"/word/embeddings/Microsoft_Excel_Worksheet{n}.xlsx"), CT.SML_SHEET, _workbook(categories, series), package)
    chart = Part(PackURI(f"/word/charts/chart{n}.xml"), CT.DML_CHART, b"", package)
    embed_rid = chart.relate_to(xlsx, RT.PACKAGE)
    if form is not None:
        xml = chart_xml_form(
            categories, series, form.get("meta") or [], kind=kind, horizontal=horizontal, number_format=number_format, embed_rid=embed_rid,
            colors=form.get("colors") or [], labels=form.get("labels"), legend=form.get("legend") or "", grid=form.get("grid", True) is not False,
        )
    else:
        xml = chart_xml(categories, series, horizontal=horizontal, number_format=number_format, embed_rid=embed_rid, kind=kind)
    chart._blob = xml.encode("utf-8")
    rid = doc_part.relate_to(chart, RT.CHART)
    inline = (
        f'<w:drawing xmlns:w="{NS_W}" xmlns:wp="{NS_WP}" xmlns:a="{NS_A}" xmlns:c="{NS_C}" xmlns:r="{NS_R}">'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{int(width)}" cy="{int(height)}"/>'
        f'<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{9000 + n}" name="Chart {n}"/><wp:cNvGraphicFramePr/>'
        f'<a:graphic><a:graphicData uri="{NS_C}"><c:chart r:id="{rid}"/></a:graphicData></a:graphic></wp:inline></w:drawing>'
    )
    paragraph.add_run()._r.append(parse_xml(inline))


__all__: List[str] = ["add_bar_chart", "add_chart", "chart_xml", "chart_xml_form"]
