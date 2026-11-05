# -*- coding: utf-8 -*-
"""PRMS-V-11 车辆通道：测速在上位机，依赖多端口 L2。"""

from core.vehicle.passage_fsm import Passage, PassageFsm
from core.vehicle.passage_store import PassageStore

__all__ = ["Passage", "PassageFsm", "PassageStore"]
