#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compatibility shim: IntentRecognizer has moved to sanhuatongyu.intent.
"""

from core.core2_0.sanhuatongyu.intent.intent_recognizer import IntentRecognizer, IntentRule

__all__ = ["IntentRecognizer", "IntentRule"]
