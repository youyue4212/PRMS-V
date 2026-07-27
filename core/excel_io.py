# -*- coding: utf-8 -*-
"""Atomic Excel helpers - avoid leaving 0-byte .xlsx on failed writes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable


def ensure_openpyxl() -> None:
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "Missing openpyxl. On the SBC run: pip3 install openpyxl"
        ) from e


def write_excel_atomic(final_path, write_callback: Callable[[str], None],
                       min_bytes: int = 200) -> int:
    """
    Write Excel via callback(tmp_path), then atomically replace final_path.
    Raises if result file is missing or smaller than min_bytes.
    """
    ensure_openpyxl()
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    # Keep .xlsx suffix so pandas/openpyxl accept the path; write beside final file.
    tmp_path = final_path.with_name(final_path.stem + ".writing.xlsx")
    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass
    try:
        write_callback(str(tmp_path))
        size = tmp_path.stat().st_size if tmp_path.exists() else 0
        if size < min_bytes:
            raise RuntimeError(
                f"Excel write too small ({size} bytes) -> {final_path}"
            )
        os.replace(str(tmp_path), str(final_path))
        return size
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        if final_path.exists() and final_path.stat().st_size < min_bytes:
            try:
                final_path.unlink()
            except OSError:
                pass
        raise


def dataframe_to_excel_atomic(df, final_path, **to_excel_kwargs) -> int:
    def _write(tmp: str):
        kwargs = dict(to_excel_kwargs)
        kwargs.setdefault("index", False)
        kwargs.setdefault("engine", "openpyxl")
        df.to_excel(tmp, **kwargs)

    return write_excel_atomic(final_path, _write)
