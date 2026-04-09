#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from core.aicore.aicore import get_aicore_instance

QUERY = "现在三花聚顶的记忆层应该怎么接入 AICore？"


def main():
    aicore = get_aicore_instance()

    # 先拿一次真实回复
    resp = aicore.chat(QUERY)

    print("=" * 72)
    print("模型回复")
    print("=" * 72)
    print(resp)
    print()

    # 直接复用当前门禁逻辑做判断
    allow = aicore._should_store_assistant_message(resp)

    print("=" * 72)
    print("门禁判断")
    print("=" * 72)
    print("should_store =", allow)
    print()

    lower_s = resp.lower()

    real_terms = [
        "core/memory_engine/memory_manager.py",
        "core/prompt_engine/prompt_memory_bridge.py",
        "core/aicore/extensible_aicore.py",
        "data/memory",
        "memorymanager",
        "promptmemorybridge",
        "extensibleaicore",
        "session_cache",
        "long_term",
        "persona",
        "三花聚顶",
        "aicore",
    ]
    fake_or_generic_markers = [
        "src/memory/manager.py",
        "src/memory/bridge.py",
        "src/aicore/core.py",
        "memory service",
        "http/grpc",
        "grpc",
        "rest",
        "微服务",
        "独立服务",
        "部署 memory layer",
        "注册插件",
        "sqlite store",
        "redis store",
        "config.yaml",
        "run_aicore.py",
        "tests/test_memory_integration.py",
    ]

    real_hits = [term for term in real_terms if term.lower() in lower_s]
    generic_hits = [term for term in fake_or_generic_markers if term.lower() in lower_s]

    print("=" * 72)
    print("命中真实结构关键词")
    print("=" * 72)
    print(real_hits if real_hits else "[]")
    print()

    print("=" * 72)
    print("命中泛化/假路径关键词")
    print("=" * 72)
    print(generic_hits if generic_hits else "[]")
    print()

    print("=" * 72)
    print("统计")
    print("=" * 72)
    print("len(resp)        =", len(resp))
    print("real_hits_count  =", len(real_hits))
    print("generic_hits_cnt =", len(generic_hits))
    print("contains_table   =", ("|" in resp and "步骤" in resp))


if __name__ == "__main__":
    main()
