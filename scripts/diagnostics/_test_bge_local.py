import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HOME"] = "E:\\huggingface_cache"

print("Loading BGE with local_files_only=True...")
try:
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
    print(f"OK: {type(m).__name__}")
    # Quick encode test
    emb = m.encode(["测试"])
    print(f"Embedding dim: {emb.shape}")
except Exception as e:
    print(f"FAIL: {e}")
