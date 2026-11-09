# -*- coding: utf-8 -*-
"""生成精简版《PRMS-V_车辆辐射通道可行方案与分阶段实现计划》Word（进度摘要）。

完整版（架构图、采购清单、四阶段计划）在 docs/ 同名 docx；
勿用本脚本覆盖 docs 内完整版，除非有意只要摘要。
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

DOC_FONT = "宋体"
DOC_TITLE = "PRMS-V_车辆辐射通道可行方案与分阶段实现计划"
DOC_DATE = date.today().isoformat()


def _set_run_font(run, name: str) -> None:
    run.font.name = name
    r = run._element.get_or_add_rPr()
    rfonts = r.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def _set_style_font(style, name: str, size_pt: float | None = None, bold: bool | None = None) -> None:
    style.font.name = name
    if size_pt is not None:
        style.font.size = Pt(size_pt)
    if bold is not None:
        style.font.bold = bold
    r = style._element.get_or_add_rPr()
    rfonts = r.get_or_add_rFonts()
    rfonts.set(qn("w:ascii"), name)
    rfonts.set(qn("w:hAnsi"), name)
    rfonts.set(qn("w:eastAsia"), name)


def set_doc_font(doc: Document, name: str = DOC_FONT, size_pt: float = 10.5) -> None:
    _set_style_font(doc.styles["Normal"], name, size_pt=size_pt)


def apply_heading_fonts(doc: Document, name: str = DOC_FONT) -> None:
    _set_style_font(doc.styles["Title"], name, size_pt=18, bold=True)
    for level in range(1, 10):
        _set_style_font(doc.styles[f"Heading {level}"], name, size_pt=max(11, 15 - level), bold=True)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], col_widths_cm: list[float] | None = None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        table.rows[0].cells[i].text = h
        for p in table.rows[0].cells[i].paragraphs:
            for r in p.runs:
                r.bold = True
                r.font.size = Pt(9)
                _set_run_font(r, DOC_FONT)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            table.rows[ri + 1].cells[ci].text = str(val)
            for p in table.rows[ri + 1].cells[ci].paragraphs:
                for r in p.runs:
                    r.font.size = Pt(9)
                    _set_run_font(r, DOC_FONT)
    if col_widths_cm:
        for row in table.rows:
            for i, w in enumerate(col_widths_cm):
                if i < len(row.cells):
                    row.cells[i].width = Cm(w)
    doc.add_paragraph("")


def build_document() -> Document:
    doc = Document()
    set_doc_font(doc)
    apply_heading_fonts(doc)

    h = doc.add_heading("PRMS-V 车辆辐射通道\n可行方案与分阶段实现计划", level=0)
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run("更新日期：%s" % DOC_DATE).italic = True

    doc.add_paragraph(
        "说明：本文档为项目开工时的总体方案与里程碑说明。"
        "若您曾在本地保存同名 Word，请以本仓库 docs 目录下最新生成版为准；"
        "实现细节同步见《PRMS-V_车辆通道相机与口岸证据包说明》。"
    )

    doc.add_heading("1. 建设目标", level=1)
    for t in (
        "在现有 PRMS-G 人员通道软件（daq_tablet）上扩展 PRMS-V 车辆辐射通道，不另起一套上位机。",
        "上位机依据主控 L2（60B）入口/出口红外沿计算车速，汇总探头 CPS 与硬报，联动相机留证。",
        "对标口岸/海关场景：一趟车一条记录，可导出含图像、短视频与辐射摘要的证据包。",
    ):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("2. 总体可行方案（架构）", level=1)
    add_table(
        doc,
        ["层次", "职责", "主要实现"],
        [
            ["主控 / 探头", "辐射判决、IR 占用、L2 上报", "STM32 固件 + Modbus/TCP"],
            ["上位机通行", "开趟/关趟、车速、历史", "passage_fsm.py、passage_store.py"],
            ["上位机相机", "RTSP 预览、ISAPI 抓拍、识牌 HTTP", "camera_service.py、rtsp_preview.py"],
            ["证据归档", "manifest + zip", "evidence_export.py（schema 1.1）"],
            ["主控室 UI", "车辆总览、设置、中英文", "vehicle_dashboard_page.py、main_window.py"],
        ],
        [2.5, 4.5, 9.5],
    )
    doc.add_paragraph(
        "方案要点：车辆测速在上位机完成（PRMS-V-11）；相机子码流预览，主码流 ISAPI 留证；"
        "识牌由卡口机 HTTP 推送，与探头 TCP 8234/8235、识牌 8236 端口分离。"
    )

    doc.add_heading("3. 方案比选（简述）", level=1)
    add_table(
        doc,
        ["选项", "结论"],
        [
            ["测速在主控 vs 上位机", "采用上位机（L2 时间戳 + 车长配置），主控改动小"],
            ["抓拍仅 RTSP 抠帧 vs ISAPI", "优先 ISAPI 101，失败 RTSP 帧兜底"],
            ["证据仅 1 张 vs 多节点 + 视频", "口岸对标：entry/alarm/exit/plate + ~10s clip"],
            ["内置录像墙 vs 证据包 mp4", "仅事件短视频进 zip，用系统播放器审计"],
        ],
        [5.5, 11.0],
    )

    doc.add_heading("4. 分阶段实现计划", level=1)
    add_table(
        doc,
        ["阶段", "内容", "状态", "验收要点"],
        [
            ["P0", "车辆通道开关、L2 测速 FSM、总览 UI、SQLite 通行", "已完成", "入口→出口得到车速与历史行"],
            ["P1", "RTSP 预览、硬报沿 ISAPI 抓拍 1 张", "已完成", "填 RTSP 可预览，硬报有图"],
            ["P2", "识牌 HTTP 8236、ingest_plate、手补车牌", "已完成", "本趟进行中可写车牌"],
            ["P3", "主控室模式、多端口 TCP、i18n 车辆页", "已完成", "control-room + 中英文"],
            ["P4", "口岸证据包 V1：entry/alarm/exit + manifest zip", "已完成", "硬报趟次生成 evidence zip"],
            ["P5", "识牌 multipart 图片、硬报 ~10s 视频、schema 1.1", "已完成", "zip 含 plate.jpg、alarm_clip.mp4"],
            ["P6", "打包内置 opencv、出厂 Word 说明", "已完成", "build_windows.bat + docx 脚本"],
            ["P7", "双机位 RTSP、报警视频时间轴对齐", "未做", "—"],
            ["P8", "FTP/ISAPI 订阅识牌、平台在线调阅", "未做", "—"],
        ],
        [1.2, 5.5, 1.5, 8.3],
    )

    doc.add_heading("5. 当前交付物（文档与代码）", level=1)
    add_table(
        doc,
        ["类型", "路径"],
        [
            ["分阶段计划（本文）", "docs/PRMS-V_车辆辐射通道可行方案与分阶段实现计划.docx"],
            ["相机与证据包说明", "docs/PRMS-V_车辆通道相机与口岸证据包说明.docx"],
            ["开发接口清单", "core/vehicle/相机对接接口清单.md"],
            ["证据包规格", "core/vehicle/口岸证据包规格.md"],
            ["Word 再生成", "python tools/build_prms_v_phase_plan_docx.py"],
        ],
        [4.5, 12.0],
    )

    doc.add_heading("6. 风险与依赖", level=1)
    for t in (
        "相机与 PC 同网段、RTSP 与防火墙策略；子码流带宽占用（预览+缓冲+导出可能多路拉流）。",
        "硬报与视频时间对齐为近似（环形缓冲 5s + 续录 5s），非帧级 UTC 对齐。",
        "405-E 识牌报文格式因固件版本差异，需现场抓样微调 plate_parse。",
        "exe 部署依赖 VC++ 运行库与整目录拷贝（含 _internal）。",
    ):
        doc.add_paragraph(t, style="List Bullet")

    doc.add_heading("7. 下一步建议", level=1)
    for t in (
        "现场联调：IR 开趟 → 硬报 → 出口，核对 evidence zip 五类文件是否齐全。",
        "归档 SITE/MACHINE 编号，便于多通道汇总。",
        "若招标明确要求全程录像，单独立项 P7+（不与当前事件 clip 混做）。",
    ):
        doc.add_paragraph(t, style="List Bullet")

    apply_heading_fonts(doc)
    return doc


def main():
    root = Path(__file__).resolve().parents[1]
    name = "PRMS-V_车辆辐射通道可行方案与分阶段实现计划.docx"
    paths = [
        root / "docs" / name,
        root / "core" / "vehicle" / name,
    ]
    doc = build_document()
    for out in paths:
        out.parent.mkdir(parents=True, exist_ok=True)
        doc.save(out)
        print("Wrote:", out)


if __name__ == "__main__":
    main()
