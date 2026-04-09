import json
import os

def load_chatgpt_json(json_path):
    """
    从 ChatGPT 的 conversations.json 中提取有效用户/助手对话内容
    格式统一为 [{role: "...", content: "..."}]
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        all_conversations = json.load(f)

    memory_chunks = []
    total_skipped = 0

    for conv in all_conversations:
        mapping = conv.get("mapping", {})
        for item in mapping.values():
            message = item.get("message")
            if not message:
                total_skipped += 1
                continue

            role = message.get("author", {}).get("role")
            content = message.get("content", {}).get("parts", [])

            if not role or not content:
                total_skipped += 1
                continue

            # 处理不同类型的 content 内容
            raw = content[0] if isinstance(content, list) and content else content

            if isinstance(raw, dict):
                text = raw.get("text", "")
            elif isinstance(raw, str):
                text = raw
            else:
                text = str(raw)

            text = text.strip()
            if not text:
                total_skipped += 1
                continue

            # ✅ 可加关键词筛选
            # if "聚核助手" not in text and "模块" not in text:
            #     continue

            memory_chunks.append({
                "role": role,
                "content": text
            })

    print(f"✅ 提取完成：有效内容 {len(memory_chunks)} 条，跳过无效项 {total_skipped} 条。")
    return memory_chunks


def save_to_memory(memory_chunks, output_path="aicore/memory/memory.json"):
    """
    合并 memory 内容并保存至指定文件，兼容复杂结构（包含 user_name、preferences、habits、history）
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.exists(output_path):
        with open(output_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        # 提取 history 列表
        if isinstance(existing_data, dict):
            existing_history = existing_data.get("history", [])
        else:
            existing_history = []
    else:
        # 如果文件不存在，用空结构初始化
        existing_data = {
            "user_name": "你",
            "preferences": {},
            "habits": {},
            "history": []
        }
        existing_history = []

    combined = existing_history + memory_chunks

    # 去重（基于 role + content），跳过缺失键的条目
    seen = set()
    unique = []
    for item in combined:
        role = item.get('role')
        content = item.get('content')
        if role is None or content is None:
            continue
        key = (role, content)
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # 更新 history 字段
    existing_data["history"] = unique

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    print(f"🧠 记忆更新完成：共写入 {len(unique)} 条内容到 {output_path}")


if __name__ == "__main__":
    print("📥 ChatGPT 导入工具")
    json_path = input("请输入 conversations.json 的完整路径: ").strip()

    if not os.path.isfile(json_path):
        print("❌ 错误：找不到该文件，请确认路径是否正确。")
        exit(1)

    memory = load_chatgpt_json(json_path)
    if memory:
        save_to_memory(memory)
    else:
        print("⚠️ 没有提取到任何有效内容。")
