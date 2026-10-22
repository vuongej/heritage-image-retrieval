"""Gói deploy phải có đủ COPY của Dockerfile và không chứa dữ liệu/credential local."""

from deploy.hf_processor import stage_files


def test_processor_deploy_bundle(tmp_path):
    stage_files(tmp_path)
    for rel in [
        "processing/main.py", "processing/samples/sample.csv", "pipeline/verify/encoder.py",
        "storage/runtime.py", "retrieval/__init__.py", "api/security.py",
        "models/verify/model_card.json", "models/verify/m1b_fold0.txt",
        "deploy/processor.requirements.txt", "Dockerfile", "README.md",
    ]:
        assert (tmp_path / rel).is_file(), rel
    assert "app_port: 8100" in (tmp_path / "README.md").read_text("utf-8")
    paths = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")]
    assert not any(p.startswith((".env", "data/", "reports/", ".git/")) for p in paths)
    assert not any("__pycache__" in p or p.endswith(".pyc") for p in paths)
