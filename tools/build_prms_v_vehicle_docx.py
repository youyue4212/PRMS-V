# -*- coding: utf-8 -*-
"""生成 PRMS-V 车辆通道：相机对接 + 口岸证据包 Word 说明。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

DOC_FONT = "宋体"
DOC_VERSION = "V1.1"
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
        _set_style_font(doc.styles[f"Heading {level}"], name, size_pt=14 - level, bold=True)


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

    title = doc.add_heading("PRMS-V 车辆通道\n相机对接与口岸证据包说明", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.add_run("文档版本：%s    更新日期：%s" % (DOC_VERSION, DOC_DATE)).italic = True
    doc.add_paragraph(
        "适用软件：daq_tablet 监测软件（伽玛能谱 / 车辆通道 PRMS-V-11）。"
        "本文档由开工时的《相机对接接口清单》扩展而来，涵盖口岸级证据包、车牌图与报警短视频。"
    )

    doc.add_heading("1. 文档关系", level=1)
    doc.add_paragraph(
        "Markdown 源稿（开发用）：core/vehicle/相机对接接口清单.md、口岸证据包规格.md、camera_api.md。"
    )
    doc.add_paragraph(
        "Word 出厂/送检用：运行 tools/build_prms_v_vehicle_docx.py 生成本文件。"
    )

    doc.add_heading("2. 系统概述", level=1)
    doc.add_paragraph(
        "车辆通道在上位机侧完成：L2 入口/出口沿测速、辐射硬报联动、相机预览与留证、"
        "一趟车一条通行记录（SQLite / 可选 Mongo）。"
    )
    doc.add_paragraph(
        "推荐相机：海康 DS-TCG405-E 或其它支持 RTSP + ISAPI 抓图 + HTTP 识牌上报的设备。"
    )

    doc.add_heading("3. 软件配置（设置 → 通讯 / 归档）", level=1)
    add_table(
        doc,
        ["配置键", "说明"],
        [
            ["VEHICLE_CHANNEL", "勾选车辆通道"],
            ["VEHICLE_RTSP_URL", "预览 RTSP，建议子码流 …/Channels/102"],
            ["VEHICLE_CAPTURE_DIR", "抓拍与证据包根目录，默认 ~/daq_tablet/vehicle_captures"],
            ["VEHICLE_CAMERA_ISAPI_CHANNEL", "ISAPI 抓图通道，默认 101（主码流留证）"],
            ["VEHICLE_PLATE_HTTP_PORT", "识牌 HTTP 监听，默认 8236，路径 /hik/anpr"],
            ["ARCHIVE_SITE_ID / ARCHIVE_MACHINE_ID", "写入证据包 manifest（口岸/站点编号）"],
        ],
        [4.5, 12.0],
    )

    doc.add_heading("4. 网络与端口", level=1)
    add_table(
        doc,
        ["用途", "方向", "端口"],
        [
            ["探头能谱 TCP", "探头 → PC 监听", "8234（多端口模式）"],
            ["主控 L2 TCP", "主控 → PC 监听", "8235（多端口模式）"],
            ["相机识牌 HTTP", "相机 → PC 监听", "8236（可改；防火墙入站放行）"],
            ["RTSP 预览/缓冲", "PC → 相机拉流", "554（相机侧）"],
            ["ISAPI 抓拍", "PC → 相机 HTTP", "80（相机侧）"],
        ],
        [4.0, 5.0, 7.5],
    )

    doc.add_heading("5. 抓拍与留证策略", level=1)
    add_table(
        doc,
        ["节点", "角色", "说明"],
        [
            ["入口 IR 开趟", "entry", "ISAPI 一张，失败则 RTSP 当前帧"],
            ["辐射硬报上升沿", "alarm", "同上，每趟硬报首次触发一次"],
            ["出口关趟", "exit", "有效趟结束；若无 alarm 图可再补 alarm"],
            ["识牌 HTTP POST", "plate", "解析车牌 + multipart/Base64 图片 → plate.jpg"],
            ["硬报沿", "video", "子码流环形缓冲约 5s + 续录 5s → alarm_clip.mp4"],
        ],
        [3.5, 2.0, 11.0],
    )
    doc.add_paragraph(
        "库内路径编码：entry|路径;alarm|路径;…;video|路径.mp4（分号分隔，竖线分隔角色）。"
    )

    doc.add_heading("6. 口岸证据包（schema 1.1）", level=1)
    doc.add_paragraph("触发：本趟有效结束且无 invalid_reason，且发生辐射硬报。")
    doc.add_paragraph("输出目录：{抓拍目录}/evidence/{passage_id}/，并生成 {passage_id}.zip。")
    doc.add_paragraph("包内结构：")
    for line in (
        "manifest.json — 全量元数据、files[] 清单",
        "radiation.json — 各探头峰值/触发 CPS、决策码",
        "images/entry.jpg、alarm.jpg、exit.jpg、plate.jpg（有则写入）",
        "video/alarm_clip.mp4 — 硬报短视频（约 10s）",
        "README.txt",
    ):
        doc.add_paragraph(line, style="List Bullet")
    doc.add_paragraph(
        "每增加一张图或视频成功后自动更新 zip。审计时解压后用系统播放器打开 mp4 即可，上位机不做监控录像墙。"
    )

    doc.add_heading("7. 现场调试步骤（简要）", level=1)
    steps = [
        "相机与 PC 同网段，Web 开启 RTSP，记下 admin 密码。",
        "设置中开启车辆通道，填写 RTSP（建议 102 子码流）。",
        "主控室启动：python main.py --control-room（或使用打包 exe 整目录）。",
        "中间区应出现预览；失败检查 RTSP URL、OpenCV（打包版已内置 opencv-python）。",
        "相机报警主机 URL：http://<PC-IP>:8236/hik/anpr",
        "模拟入口→硬报→出口，检查 evidence 目录下 zip 内容是否齐全。",
    ]
    for i, s in enumerate(steps, 1):
        doc.add_paragraph("%d. %s" % (i, s))

    doc.add_heading("8. Windows 打包部署", level=1)
    doc.add_paragraph(
        "运行 packaging/build_windows.bat，将 packaging/dist/daq_tablet 整夹拷到目标机。"
        "须含 _internal 与 opencv；目标机安装 VC++ 2015–2022 x64。"
        "换电脑无需再 pip install opencv-python。"
    )

    doc.add_heading("9. 后续规划（未实现）", level=1)
    for line in (
        "报警视频与 L2 时间戳逐帧对齐标注",
        "双机位 RTSP、7×24 全程录像",
        "平台内嵌多路回放",
    ):
        doc.add_paragraph(line, style="List Bullet")

    doc.add_heading("10. 代码索引", level=1)
    add_table(
        doc,
        ["模块", "路径"],
        [
            ["相机服务", "core/vehicle/camera_service.py"],
            ["证据导出", "core/vehicle/evidence_export.py"],
            ["报警短视频", "core/vehicle/alarm_clip_recorder.py"],
            ["识牌解析", "core/vehicle/plate_parse.py"],
            ["RTSP 预览", "core/vehicle/rtsp_preview.py"],
        ],
        [4.0, 12.5],
    )

    apply_heading_fonts(doc)
    return doc


def main():
    root = Path(__file__).resolve().parents[1]
    out_docs = root / "docs" / "PRMS-V_车辆通道相机与口岸证据包说明.docx"
    out_vehicle = root / "core" / "vehicle" / "PRMS-V_车辆通道相机与口岸证据包说明.docx"
    doc = build_document()
    out_docs.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_docs)
    doc.save(out_vehicle)
    print("Wrote:", out_docs)
    print("Wrote:", out_vehicle)


if __name__ == "__main__":
    main()
