"""BGE 加载测试 —— 使用 HF 镜像"""
import os
os.environ["HF_HOME"] = "E:\\huggingface_cache"
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

print("Loading BGE-small-zh-v1.5 (mirror)...")
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
print(f"Loaded! dim={model.get_sentence_embedding_dimension()}")

emb = model.encode(["孤独，想躲开，有点抗拒"])
print(f"Embedding shape: {emb.shape}")
print("OK")
