"""PDF report export using ReportLab.

Generates a professional valuation report PDF with:
- Cover page (project info)
- Cost summary table
- Division breakdown table
- Line-item detail table
"""

from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from app.models.boq_item import BoqItem
from app.models.line_item_quota_binding import LineItemQuotaBinding
from app.models.project import Project
from app.services.project_calc_service import run_project_calculation


def _register_chinese_font() -> str:
    """Try to register a Chinese-capable font; fall back to Helvetica."""
    import os
    import platform

    font_candidates = []
    if platform.system() == "Darwin":
        font_candidates = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
        ]
    elif platform.system() == "Linux":
        font_candidates = [
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
    elif platform.system() == "Windows":
        font_candidates = [
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),
            os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simsun.ttc"),
        ]

    for path in font_candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", path, subfontIndex=0))
                return "ChineseFont"
            except Exception:
                continue

    return "Helvetica"


def export_valuation_pdf(project_id: int, db: Session) -> bytes:
    """Generate a PDF valuation report and return as bytes."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError(f"Project {project_id} not found")

    summary, line_results = run_project_calculation(project_id=project_id, db=db)

    font_name = _register_chinese_font()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CNTitle", parent=styles["Title"],
        fontName=font_name, fontSize=18, leading=24,
    )
    heading_style = ParagraphStyle(
        "CNHeading", parent=styles["Heading2"],
        fontName=font_name, fontSize=13, leading=18, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "CNBody", parent=styles["Normal"],
        fontName=font_name, fontSize=9, leading=12,
    )

    elements: list = []

    # ── Cover / Title ──
    elements.append(Paragraph(f"工程计价报告", title_style))
    elements.append(Spacer(1, 6 * mm))
    info_rows = [
        ["项目名称", project.name],
        ["所在地区", project.region],
        ["项目类型", project.project_type],
        ["计价标准", project.standard_type],
        ["币种", project.currency],
    ]
    if project.description:
        info_rows.append(["项目描述", project.description[:80]])
    if project.budget:
        info_rows.append(["预算", f"{project.budget:,.2f}"])
    info_rows.append(["报告时间", datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')])
    info_table = Table(info_rows, colWidths=[35 * mm, 125 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 10 * mm))

    # ── Cost Summary ──
    elements.append(Paragraph("一、费用汇总", heading_style))
    cost_data = [
        ["费用项目", "金额"],
        ["直接费", f"{summary.total_direct:,.2f}"],
        ["管理费", f"{summary.total_management:,.2f}"],
        ["利润", f"{summary.total_profit:,.2f}"],
        ["规费", f"{summary.total_regulatory:,.2f}"],
        ["税前合计", f"{summary.total_pre_tax:,.2f}"],
        ["税金", f"{summary.total_tax:,.2f}"],
        ["措施费", f"{summary.total_measures:,.2f}"],
        ["工程总价", f"{summary.grand_total:,.2f}"],
    ]
    cost_table = Table(cost_data, colWidths=[80 * mm, 80 * mm])
    cost_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E1F2")),
        ("FONTNAME", (0, 0), (-1, 0), font_name),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2EFDA")),
    ]))
    elements.append(cost_table)
    elements.append(Spacer(1, 8 * mm))

    # ── Division Breakdown ──
    elements.append(Paragraph("二、分部工程汇总", heading_style))
    div_totals: dict[str, float] = defaultdict(float)
    div_counts: dict[str, int] = defaultdict(int)
    for boq, result in line_results:
        div = boq.division or "未分类"
        div_totals[div] += result.total
        div_counts[div] += 1

    grand = summary.grand_total or 1
    div_data = [["分部工程", "清单数", "合计金额", "占比"]]
    for div, total in sorted(div_totals.items(), key=lambda x: -x[1]):
        div_data.append([
            div,
            str(div_counts[div]),
            f"{total:,.2f}",
            f"{total / grand * 100:.1f}%",
        ])
    # Total row
    div_data.append([
        "合计",
        str(sum(div_counts.values())),
        f"{sum(div_totals.values()):,.2f}",
        "100.0%",
    ])

    div_table = Table(div_data, colWidths=[50 * mm, 25 * mm, 50 * mm, 30 * mm])
    # Style with highlighted total row
    div_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E1F2")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2EFDA")),
        ("FONTNAME", (0, -1), (-1, -1), font_name),
    ]))
    elements.append(div_table)
    elements.append(PageBreak())

    # ── Line Items ──
    elements.append(Paragraph("三、分部分项工程计价表", heading_style))
    line_data = [["序号", "编码", "名称", "单位", "工程量", "综合单价", "合价"]]
    for idx, (boq, result) in enumerate(line_results, 1):
        unit_price = result.total / boq.quantity if boq.quantity else 0
        line_data.append([
            str(idx),
            boq.code,
            boq.name[:15],  # truncate for PDF width
            boq.unit,
            f"{boq.quantity:,.2f}",
            f"{unit_price:,.2f}",
            f"{result.total:,.2f}",
        ])

    # Grand total row
    line_data.append([
        "", "", "合计", "", "",
        "",
        f"{sum(r.total for _, r in line_results):,.2f}",
    ])

    line_table = Table(
        line_data,
        colWidths=[12 * mm, 25 * mm, 42 * mm, 15 * mm, 22 * mm, 25 * mm, 25 * mm],
    )
    line_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E1F2")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2EFDA")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F5F5F5")]),
    ]))
    elements.append(line_table)

    # ── Page number footer ──
    def add_page_number(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 7)
        canvas.drawCentredString(
            A4[0] / 2, 12 * mm,
            f"{project.name} — 工程计价报告    第 {doc.page} 页",
        )
        canvas.restoreState()

    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    return buf.getvalue()
