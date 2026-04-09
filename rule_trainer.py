import json
import re
from pathlib import Path
from ju_wu.juwu import JuWu

RULES_PATH = Path("ju_wu/rules/intent_rules.json")

def load_rules():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_rules(rules):
    with open(RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)

def rule_exists(rules, pattern):
    return any(r["pattern"] == pattern for r in rules)

def suggest_rule(text: str, keywords: list):
    # 默认取最后3个中文关键词
    pattern = "|".join(set(keywords[-3:])) if keywords else text
    return {
        "pattern": pattern,
        "intent": {
            "module": "custom",
            "action": "unknown_action",
            "require_confirm": False
        }
    }

def main():
    print("🧠 聚悟意图规则训练器已启动（输入 exit 退出）")
    juwu = JuWu(memory_manager=None)
    rules = load_rules()

    while True:
        text = input("你说：")
        if text.lower() in ["exit", "退出", "quit"]:
            break

        result = juwu.analyze(text)
        print(f"\n📌 关键词提取：{result['keywords']}")
        print(f"💡 情绪判断：{result['sentiment']}")

        if result["module"] == "default":
            print("⚠️ 未命中任何规则，尝试构建建议规则...")

            suggestion = suggest_rule(text, result["keywords"])
            print("\n📄 建议新增规则：")
            print(json.dumps(suggestion, ensure_ascii=False, indent=2))

            confirm = input("是否添加此规则？(y/n/custom)：").strip().lower()
            if confirm == "y":
                if rule_exists(rules, suggestion["pattern"]):
                    print("⚠️ 此规则已存在，跳过。")
                else:
                    rules.append(suggestion)
                    save_rules(rules)
                    print("✅ 规则已添加")
            elif confirm == "custom":
                mod = input("请输入模块名（如 memory / code / action）：").strip()
                act = input("请输入动作名（如 store_info / generate_code）：").strip()
                suggestion["intent"]["module"] = mod
                suggestion["intent"]["action"] = act
                rules.append(suggestion)
                save_rules(rules)
                print("✅ 自定义规则已添加")
            else:
                print("❌ 放弃添加。")
        else:
            print(f"✅ 已识别为模块：{result['module']}，动作：{result['action']}")

if __name__ == "__main__":
    main()
