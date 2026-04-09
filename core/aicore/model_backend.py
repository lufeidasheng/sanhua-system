#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Union
from concurrent.futures import Future


class ModelBackend(ABC):
    @abstractmethod
    def chat(self, query: str, **kwargs) -> Union[str, Future]:
        ...

    @abstractmethod
    def list_models(self) -> List[Union[str, Dict]]:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...

    @abstractmethod
    def get_backend_info(self) -> Dict[str, Any]:
        ...
