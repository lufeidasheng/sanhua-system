import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

class MemoryRetriever:
    def __init__(self, memory_path="aicore/memory/memory.json", embedding_model_name="all-MiniLM-L6-v2"):
        self.memory_path = memory_path
        self.model = SentenceTransformer(embedding_model_name)
        self.memory_texts = []
        self.memory_embeddings = None
        self.index = None
        self.load_memory_and_build_index()

    def load_memory_and_build_index(self):
        # 读取 memory.json，取 history 列表中所有 content
        with open(self.memory_path, "r", encoding="utf-8") as f:
            memory_data = json.load(f)
        history = memory_data.get("history", [])

        # 只保留文本内容（role+content）
        self.memory_texts = [f"{item.get('role','')}: {item.get('content','')}" for item in history if item.get('content')]

        # 计算所有文本的向量表示
        self.memory_embeddings = self.model.encode(self.memory_texts, convert_to_numpy=True)

        # 建立 faiss 索引
        dim = self.memory_embeddings.shape[1]
        self.index = faiss.IndexFlatL2(dim)
        self.index.add(self.memory_embeddings)
        print(f"🧠 载入记忆条目 {len(self.memory_texts)} 条，向量维度 {dim}")

    def retrieve(self, query, top_k=5):
        # 对 query 计算向量
        query_vec = self.model.encode([query], convert_to_numpy=True)

        # faiss 查询
        distances, indices = self.index.search(query_vec, top_k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            text = self.memory_texts[idx]
            results.append((text, dist))
        return results


if __name__ == "__main__":
    retriever = MemoryRetriever()

    while True:
        q = input("请输入查询内容（exit退出）：").strip()
        if q.lower() == "exit":
            break
        results = retriever.retrieve(q)
        print("🔍 检索结果：")
        for i, (text, dist) in enumerate(results, 1):
            print(f"{i}. {text}  (距离: {dist:.4f})")

        # 演示把结果拼进 prompt
        combined_context = "\n".join([r[0] for r in results])
        prompt = f"基于以下记忆内容回答问题：\n{combined_context}\n问题：{q}\n回答："
        print("\n📝 生成的 Prompt:\n")
        print(prompt)
        print("-" * 40)
