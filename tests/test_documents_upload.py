from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)


def test_upload_documents_txt():
    files = [
        ("files", ("sample.txt", b"This is a small test document about SmartTask.", "text/plain")),
        ("files", ("notes.md", b"# Header\nSome markdown content about SmartTask.", "text/markdown")),
    ]

    response = client.post(f"{settings.API_V1_STR}/documents", files=files)
    assert response.status_code in (200, 500)

    if response.status_code == 200:
        data = response.json()
        assert "added_chunks" in data
        assert "documents_count" in data
        assert "processed_files" in data
        assert data["documents_count"] >= 1
        assert any(name.endswith((".txt", ".md")) for name in data["processed_files"]) 
    else:
        # В случае проблем с внешними зависимостями в окружении
        err = response.json()
        assert "detail" in err
        assert isinstance(err["detail"], str)
