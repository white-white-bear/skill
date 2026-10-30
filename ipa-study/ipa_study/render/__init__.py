# -*- coding: utf-8 -*-
"""PDF 排版：引擎在 base，形态在 book / single，可编辑文案在 content。"""
from .base import Renderer
from .book import build_book
from .single import build_single

__all__ = ["Renderer", "build_book", "build_single"]
