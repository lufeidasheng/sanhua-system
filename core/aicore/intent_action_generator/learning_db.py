# core/aicore/intent_action_generator/learning_db.py

import json
import os
from typing import List, Dict

class LearningDB:
    """记录未识别意图、人工补全和正例/反例供后续微调/进化"""
    def __init__(self, db_file="intent_action_learn.json"):
        self.db_file = db_file
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"unrecognized": [], "samples": []}

    def save(self):
        with open(self.db_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def record_unrecognized(self, query: str):
        self.data.setdefault("unrecognized", []).append(query)
        self.save()

    def add_sample(self, query: str, intent: str, action: str):
        self.data.setdefault("samples", []).append({"query": query, "intent": intent, "action": action})
        self.save()
