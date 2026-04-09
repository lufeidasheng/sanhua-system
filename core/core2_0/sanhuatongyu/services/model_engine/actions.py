# core/core2_0/sanhuatongyu/services/model_engine/actions.py
# -*- coding: utf-8 -*-
def set_backend(context, backend: str|None=None):
    eng = context.services["model_engine"]; return eng.set_forced_backend(backend)

def status(context):
    eng = context.services["model_engine"]; return eng.engine_health()

def reload(context):
    eng = context.services["model_engine"]; return {"ok": True, "engine": eng.VERSION}
