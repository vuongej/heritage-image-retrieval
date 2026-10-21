import os

os.environ.setdefault("API_KEY_ENFORCE", "false")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("TEST_API_KEY", "gsk_test_dev_only")
# Test không bao giờ gọi OpenRouter thật (load_env dùng setdefault nên giá trị rỗng được giữ).
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["VECTOR_BACKEND"] = "numpy"  # test không cần Qdrant
# Test dùng MiniLM local (mock), không bao giờ gọi endpoint embedding thật.
os.environ["EMBED_BACKEND"] = "torch"
os.environ["EMBED_MODEL"] = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
os.environ["EMBED_DIM"] = "384"
os.environ["EMBED_API_KEY"] = ""
# Production mặc định rerank bằng BGE local; test giữ "llm" (không key -> cosine mock), không nạp model.
os.environ["RERANK_BACKEND"] = "llm"
os.environ["PRELOAD_MODELS"] = "false"  # test không nạp model thật khi khởi động TestClient
