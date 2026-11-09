# -*- coding: utf-8 -*-
"""在保留架构图的前提下，按当前代码完善《可行方案与分阶段实现计划》Word。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

DOC_FONT = "宋体"
REV_DATE = date.today().isoformat()
DOC_NAME = "PRMS-V_车辆辐射通道可行方案与分阶段实现计划.docx"


def _set_cell_font(cell, size_pt: float = 9.0, bold: bool | None = None) -> None:
    for p in cell.paragraphs:
        for r in p.runs:
            r.font.name = DOC_FONT
            r.font.size = Pt(size_pt)
            if bold is not None:
                r.font.bold = bold
            pr = r._element.get_or_add_rPr()
            rfonts = pr.get_or_add_rFonts()
            rfonts.set(qn("w:ascii"), DOC_FONT)
            rfonts.set(qn("w:hAnsi"), DOC_FONT)
            rfonts.set(qn("w:eastAsia"), DOC_FONT)


def set_cell_text(cell, text: str, size_pt: float = 9.0, bold: bool | None = None) -> None:
    cell.text = str(text)
    _set_cell_font(cell, size_pt=size_pt, bold=bold)


def add_table(doc: Document, headers: list[str], rows: list[list[str]], col_widths_cm: list[float] | None = None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        set_cell_text(table.rows[0].cells[i], h, bold=True)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            set_cell_text(table.rows[ri + 1].cells[ci], val)
    if col_widths_cm:
        for row in table.rows:
            for i, w in enumerate(col_widths_cm):
                if i < len(row.cells):
                    row.cells[i].width = Cm(w)
    doc.add_paragraph("")
    return table


def _find_para(doc: Document, needle: str) -> int:
    for i, p in enumerate(doc.paragraphs):
        if needle in (p.text or ""):
            return i
    return -1


def _insert_before_paragraph(doc: Document, index: int, elements: list) -> None:
    """Insert block elements before doc.paragraphs[index] (python-docx body order)."""
    anchor = doc.paragraphs[index]._element
    body = anchor.getparent()
    for el in elements:
        body.insert(body.index(anchor), el)


def patch_document(doc: Document) -> None:
    if _find_para(doc, "九、当前实现状态") >= 0:
        raise SystemExit("document already contains section 9; skip to avoid duplicate patches")

    # 封面信息表
    t0 = doc.tables[0]
    set_cell_text(t0.rows[3].cells[0], "编制 / 修订")
    set_cell_text(
        t0.rows[3].cells[1],
        "2026-11-05 初稿；%s 按已交付软件修订（Phase A + MVP + 口岸证据包 V1.1）" % REV_DATE,
    )

    # 数据流：相机对接方式
    t2 = doc.tables[2]
    set_cell_text(
        t2.rows[4].cells[2],
        "卡口相机：RTSP 子码流预览（Channels/102）；"
        "ISAPI 101 抓拍；识牌 HTTP POST → PC 8236（/hik/anpr，multipart 车牌+图）。"
        "详见 docs《相机与口岸证据包说明》与 core/vehicle/相机对接接口清单.md。",
    )
    set_cell_text(
        t2.rows[7].cells[2],
        "SQLite vehicle_passages + 可选 Mongo PRMS.vehicle_passages；"
        "硬报有效趟次导出 evidence/{passage_id}/ 与 .zip（schema 1.1）。",
    )

    # 硬件表：卡口说明
    t3 = doc.tables[3]
    set_cell_text(
        t3.rows[3].cells[2],
        "现场参考海康 DS-TCG405-E 类；ISAPI + 报警主机 URL，非远距雷视。",
    )
    set_cell_text(
        t3.rows[4].cells[2],
        "相机推送或 HTTP 监听 ingest；本趟 open 时写入 plate，支持 UI 人工补录（plate_manual）。",
    )
    set_cell_text(
        t3.rows[5].cells[2],
        "daq_tablet（--control-room 主控室模式）；打包版含 opencv（RTSP/短录像）。",
    )

    # 数据模型
    t4 = doc.tables[4]
    extra_rows = [
        ("plate_manual", "是否人工补录车牌（SQLite 字段）"),
        ("r2_on", "本趟是否应开 R2（超速且无硬报/无效）"),
        (
            "image_paths",
            "entry|alarm|exit|plate|video 多角色路径（evidence_assets.py）",
        ),
        ("evidence_zip", "硬报有效趟：manifest + images/ + video/alarm_clip.mp4"),
        (
            "operator_ack",
            "设计预留；消警/确认仍走主控 0x15 等人员通道流程，未单独入 passage 表",
        ),
    ]
    for label, meaning in extra_rows:
        row = t4.add_row()
        set_cell_text(row.cells[0], label)
        set_cell_text(row.cells[1], meaning)

    # 端口
    t5 = doc.tables[5]
    row = t5.add_row()
    set_cell_text(row.cells[0], "识牌 HTTP")
    set_cell_text(row.cells[1], "8236（VEHICLE_PLATE_HTTP_PORT，可改；路径 /hik/anpr）")
    row = t5.add_row()
    set_cell_text(row.cells[0], "车辆通道 UI")
    set_cell_text(row.cells[1], "python main.py --control-room；配置 VEHICLE_CHANNEL_ENABLED 等（ConfigManager）")

    # Phase 2 验收 + 实现状态列
    from docx.table import _Cell

    t8 = doc.tables[8]
    status_col = [
        "软件实现（%s）" % REV_DATE,
        "已完成：passage_fsm.py、passage_store.py",
        "已完成：speed.py + VEHICLE_LENGTH_M / VEHICLE_V_LIMIT_KMH",
        "已完成：FSM _latch_packet 绑定 decision/hit/CPS",
        "已完成：entry/alarm/exit ISAPI+RTSP；硬报 ~10s mp4",
        "已完成：plate_http_server + ingest_plate；405-E 报文待现场微调",
        "已完成：r2_on + ui_base control_single_relay(2)；硬报时不开 R2",
    ]
    for i, row in enumerate(t8.rows):
        if len(row.cells) >= 3:
            set_cell_text(row.cells[2], status_col[i] if i < len(status_col) else "")
            continue
        new_tc = row._tr.add_tc()
        c = _Cell(new_tc, t8)
        set_cell_text(c, status_col[i] if i < len(status_col) else "", bold=(i == 0))

    # Phase 1 / 3 加状态说明行
    t7 = doc.tables[7]
    note_row = t7.add_row()
    set_cell_text(note_row.cells[0], "固件 / 上位机联调（软件侧）")
    set_cell_text(
        note_row.cells[1],
        "PMT 主控：PG14/PG15、L2 bit0/1、0x0078 占用下发探头；"
        "上位机 tcp_multi_port 8234/8235。剩余为现场接线与 L 标定验收。",
    )

    t9 = doc.tables[9]
    note_row = t9.add_row()
    set_cell_text(note_row.cells[0], "软件已备文档")
    set_cell_text(
        note_row.cells[1],
        "docs/PRMS-V_车辆通道相机与口岸证据包说明.docx；"
        "core/vehicle/口岸证据包规格.md。JJF/夜间 LPR/误挡仍待 Phase 3 现场。",
    )

    # 上位机分工表
    t10 = doc.tables[10]
    set_cell_text(
        t10.rows[3].cells[1],
        "core/vehicle/*：FSM、SQLite、camera_service、evidence_export、"
        "vehicle_dashboard_page、i18n；打包 packaging/daq_tablet.spec（opencv）。",
    )

    # 结论表
    set_cell_text(
        doc.tables[12].rows[0].cells[0],
        "评审结论（修订）：Phase A 主链路与 Phase 2 MVP 已在 daq_tablet 落地；"
        "口岸证据包 V1.1 为在 MVP 之上的增强。Phase 3 现场试验与 Phase 4 backlog 仍按原计划推进。",
    )

    # 修订文首说明
    for p in doc.paragraphs:
        if p.text.startswith("本文档给出车辆放射性"):
            p.text = (
                p.text.rstrip()
                + " "
                + "【%s 修订】下文「九、当前实现状态」与表格中「软件实现」列反映仓库已交付能力；"
                "相机/LPR 以 ISAPI + HTTP 8236 为准（非封闭 SDK 独占方案）。"
                % REV_DATE
            )
            break

    # 4.2.3 补充一句（找 LPR 小节后的列表）
    for p in doc.paragraphs:
        if p.text.strip() == "识别失败：提供人工补录车牌字段。":
            break
    # 在 4.3 前插入 4.2.6
    idx = _find_para(doc, "4.3 网络与端口")
    if idx >= 0:
        anchor = doc.paragraphs[idx]._element
        body = anchor.getparent()
        from docx.oxml import OxmlElement

        def _heading(text, level=3):
            p = doc.add_paragraph(text, style="Heading %d" % level)
            return p._element

        def _bullet(text):
            p = doc.add_paragraph(text, style="List Bullet")
            return p._element

        inserts = []
        h = doc.add_paragraph("4.2.6 已交付实现要点（与代码一致）", style="Heading 3")
        inserts.append(h._element)
        bullets = [
            "模块目录：daq_tablet/core/vehicle/（passage_fsm、passage_store、camera_service、"
            "plate_http_server、evidence_export、alarm_clip_recorder 等）。",
            "配置键：VEHICLE_CHANNEL_ENABLED、VEHICLE_LENGTH_M、VEHICLE_V_LIMIT_KMH、"
            "VEHICLE_RTSP_URL、VEHICLE_CAPTURE_DIR、VEHICLE_PLATE_HTTP_*。",
            "抓拍策略：入口/出口/硬报沿 enqueue ISAPI；失败 RTSP 帧兜底；"
            "硬报沿触发环形缓冲 + 续录约 10s → alarm_clip.mp4。",
            "证据包：有效趟 + 硬报 → {CAPTURE_DIR}/evidence/{passage_id}/ 与同名 .zip（schema 1.1）。",
            "边沿说明：上位机检测 L2 io_status bit0/1 0→1；入口位与主控 s_ir_occ 占用语义一致，"
            "现场须用挡光试验核对 t₁/t₂。",
        ]
        for b in bullets:
            bp = doc.add_paragraph(b, style="List Bullet")
            inserts.append(bp._element)
        for el in reversed(inserts):
            body.insert(body.index(anchor), el)

    # 九、当前实现状态 — 插在「— 文档结束 —」前
    end_idx = _find_para(doc, "— 文档结束 —")
    if end_idx < 0:
        end_idx = len(doc.paragraphs) - 2

    anchor = doc.paragraphs[end_idx]._element
    body = anchor.getparent()
    block = []

    h1 = doc.add_paragraph("九、当前实现状态", style="Heading 1")
    block.append(h1._element)
    p0 = doc.add_paragraph(
        "本节对照 %s 时 daq_tablet 与 PMT 主控固件（Phase A）已合并能力，"
        "供出厂联调、送检与后续 Phase 3/4 排期使用。" % REV_DATE
    )
    block.append(p0._element)

    h2 = doc.add_paragraph("9.1 阶段总览", style="Heading 2")
    block.append(h2._element)

    # 临时移到末尾再挪 — add_table 会 append 到 doc end
    for el in block:
        body.insert(body.index(anchor), el)
    block.clear()

    # 插入点改为 anchor 前 — tables must be inserted via moving
    # 简化：在 end 前 add 会乱序，改用 paragraph 后在 doc 末尾加表再 manual move 太复杂
    # 直接在「文档结束」前 insert 仅标题，表用 insert_paragraph_before 链

    # Re-get anchor after inserts
    end_idx = _find_para(doc, "— 文档结束 —")
    anchor = doc.paragraphs[end_idx]._element
    body = anchor.getparent()

    phase_table = add_table(
        doc,
        ["原计划阶段", "范围", "实现状态", "说明"],
        [
            ["Phase 0", "方案 / BOM", "已完成", "本文档 + 相机/证据包 Word"],
            ["Phase 1", "硬件联调", "部分", "固件与上位机就绪；L 标定与接线待现场签字"],
            ["Phase 2", "上位机 MVP", "已完成", "FSM、测速、L2 绑定、相机、LPR HTTP、R2、SQLite"],
            ["Phase 2+", "口岸证据包", "已完成", "zip schema 1.1，超出原 MVP 表格范围"],
            ["Phase 3", "现场试验", "未开始", "夜间 LPR、JJF 动态、误挡、车辆手册"],
            ["Phase 4", "backlog", "未做", "L2 带车速、双机位、平台调阅、OCR 等"],
        ],
        [2.2, 4.0, 1.5, 8.8],
    )
    body.insert(body.index(anchor), phase_table._element)

    h22 = doc.add_paragraph("9.2 软件模块对照", style="Heading 2")
    body.insert(body.index(anchor), h22._element)
    mod_table = add_table(
        doc,
        ["设计条目", "源文件 / 配置"],
        [
            ["通行 FSM", "core/vehicle/passage_fsm.py"],
            ["车速", "core/vehicle/speed.py；VEHICLE_LENGTH_M、VEHICLE_V_LIMIT_KMH"],
            ["通行库", "core/vehicle/passage_store.py → SQLite vehicle_passages"],
            ["L2 接入", "core/master_summary.py；tcp_multi_port 8235"],
            ["相机 / 录像", "camera_service.py、alarm_clip_recorder.py、hik_isapi.py、rtsp_preview.py"],
            ["识牌", "plate_http_server.py、plate_parse.py；端口 8236"],
            ["证据导出", "evidence_export.py、evidence_assets.py；口岸证据包规格.md"],
            ["主控室 UI", "vehicle_dashboard_page.py；main.py --control-room"],
            ["打包", "packaging/daq_tablet.spec、build_windows.bat（含 cv2）"],
        ],
        [4.5, 11.8],
    )
    body.insert(body.index(anchor), mod_table._element)

    h23 = doc.add_paragraph("9.3 与设计的差异（已知）", style="Heading 2")
    body.insert(body.index(anchor), h23._element)
    diffs = [
        "相机接口：设计写「SDK 软触发」；实现为 ISAPI 抓图 + 海康类设备 HTTP 识牌推送，不绑定单一厂商 SDK 库。",
        "短录像：默认约 10s（5s 缓冲 + 5s 续录，8fps），写入证据 zip，非全程 NVR。",
        "operator_ack：未写入 passage 表；消警逻辑与 PRMS-G 主控室一致。",
        "主控 Phase B（L2 内 speed_kmh、主控自动 R2）：未实现，符合 Phase A 边界。",
    ]
    for d in diffs:
        bp = doc.add_paragraph(d, style="List Bullet")
        body.insert(body.index(anchor), bp._element)

    h24 = doc.add_paragraph("9.4 相关文档", style="Heading 2")
    body.insert(body.index(anchor), h24._element)
    refs = [
        "docs/PRMS-V_车辆通道相机与口岸证据包说明.docx",
        "core/vehicle/相机对接接口清单.md",
        "core/vehicle/口岸证据包规格.md",
        "Core/user/master_proto/上位机对接说明-通道报警与复位.md（PMT 仓库，PG14/PG15、0x0078）",
    ]
    for r in refs:
        bp = doc.add_paragraph(r, style="List Bullet")
        body.insert(body.index(anchor), bp._element)

    # 更新页脚日期
    for p in doc.paragraphs:
        if p.text.startswith("编制日期："):
            p.text = (
                "编制日期：2026-11-05（Asia/Shanghai）｜"
                "修订日期：%s｜主链路：双红外测速 + 卡口 LPR + 双探头/主控 L2"
                % REV_DATE
            )
            break

    # 八、结论 补充
    for p in doc.paragraphs:
        if p.text.startswith("可行主方案："):
            p.text = (
                "可行主方案：PG14/PG15 双红外测速 + 出入口卡口 LPR + 现有 γ 双探头 / 主控 L2 + "
                "工控机通行 FSM 入库；Phase A 以上位机为主、不动 L2 包结构；远距交通雷视一体机不进入 PRMS 主链路。"
                "截至 %s，daq_tablet 车辆模块与口岸证据包 V1.1 已按本方案 Phase A/2 交付，Phase 3 现场验收与 Phase 4 增强仍待排期。"
                % REV_DATE
            )
            break
        if p.text.startswith("可选后续："):
            p.text = (
                "可选后续：Phase 3 完成 L 标定签字、夜间 LPR 批次、JJF 动态试验与车辆版操作手册；"
                "Phase 4 按 backlog 单独立项（主控 Phase B、双机位 RTSP、平台在线调阅等）。"
                "Issue 级任务以 core/vehicle 目录与本文档第九节模块表为准。"
            )
            break


def main():
    import shutil

    root = Path(__file__).resolve().parents[1]
    src = root / "docs" / DOC_NAME
    if not src.is_file():
        raise SystemExit("missing: %s" % src)
    doc = Document(str(src))
    patch_document(doc)
    doc.save(str(src))
    print("Patched:", src)
    copy_to = root / "core" / "vehicle" / DOC_NAME
    copy_to.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, copy_to)
    print("Copied:", copy_to)


if __name__ == "__main__":
    main()
