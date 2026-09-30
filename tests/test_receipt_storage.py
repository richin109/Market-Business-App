from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_session, create_user
from mbs.db import get_session
from mbs.main import app
from mbs.receipts.storage import (
    ClamAVScanner,
    InMemoryOutbox,
    LocalProtectedFileStore,
    ScanStatus,
)
from mbs.receipts.upload import ReceiptUploadService, UploadStatus


class MockOCREngine:
    def __init__(self) -> None:
        self.calls = 0

    def extract(self, source: bytes, media_type: str) -> dict[str, Any]:
        self.calls += 1
        return {
            "receipt": {
                "store": "Synthetic Market",
                "date": "2026-09-30",
                "time": "14:05:06",
                "transaction_number": "TC-500",
                "total": "1.00",
            },
            "items": [{"description": "Milk", "line_total": "1.00"}],
        }


def test_clean_upload_is_saved_with_one_outbox_event(tmp_path: Path) -> None:
    engine = MockOCREngine()
    outbox = InMemoryOutbox()
    service = ReceiptUploadService(
        engine,
        file_store=LocalProtectedFileStore(tmp_path),
        malware_scanner=ClamAVScanner(lambda source: True),
        outbox=outbox,
    )
    source = b"\x89PNG\r\n\x1a\nsynthetic-clean"

    result = service.upload(source, "image/png")

    assert result.status is UploadStatus.ACCEPTED
    assert result.file_key is not None
    stored_file = tmp_path / result.file_key
    assert stored_file.read_bytes() == source
    assert len(outbox.events) == 1
    assert outbox.events[0].file_key == result.file_key
    assert engine.calls == 1


def test_scanner_unavailable_fails_closed_before_ocr(tmp_path: Path) -> None:
    engine = MockOCREngine()
    outbox = InMemoryOutbox()
    service = ReceiptUploadService(
        engine,
        file_store=LocalProtectedFileStore(tmp_path),
        malware_scanner=ClamAVScanner(lambda source: None),
        outbox=outbox,
    )

    result = service.upload(b"\x89PNG\r\n\x1a\nscanner-down", "image/png")

    assert result.status is UploadStatus.SCAN_PENDING
    assert engine.calls == 0
    assert outbox.events == []
    assert list(tmp_path.rglob("*")) == []


def test_infected_upload_is_rejected_before_storage_and_ocr(tmp_path: Path) -> None:
    engine = MockOCREngine()
    service = ReceiptUploadService(
        engine,
        file_store=LocalProtectedFileStore(tmp_path),
        malware_scanner=ClamAVScanner(lambda source: False),
    )

    result = service.upload(b"\x89PNG\r\n\x1a\nsynthetic-infected", "image/png")

    assert result.status is UploadStatus.MALWARE_REJECTED
    assert engine.calls == 0
    assert list(tmp_path.rglob("*")) == []


def test_clamav_adapter_maps_connection_failure_to_unavailable() -> None:
    def unavailable(source: bytes) -> bool:
        raise OSError("clamd unavailable")

    assert ClamAVScanner(unavailable).scan(b"synthetic") is ScanStatus.UNAVAILABLE


def test_authenticated_upload_endpoint_delegates_to_validated_service(tmp_path: Path) -> None:
    database_path = tmp_path / "upload-api.db"
    engine = create_engine(f"sqlite:///{database_path}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    with Session(engine) as database_session:
        user = create_user(database_session, "manager", "manager password", Role.MANAGER)
        session_token, _ = create_session(database_session, user)
        database_session.commit()

        engine_service = MockOCREngine()
        app_service = ReceiptUploadService(
            engine_service,
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            malware_scanner=ClamAVScanner(lambda source: True),
        )

        def override_session() -> Any:
            yield database_session

        import mbs.main as main_module

        previous_service = main_module.receipt_upload_service
        main_module.receipt_upload_service = app_service
        app.dependency_overrides[get_session] = override_session
        try:
            response = TestClient(app).post(
                "/api/v1/receipts/upload",
                content=b"\x89PNG\r\n\x1a\napi-upload",
                headers={
                    "Content-Type": "image/png",
                    "Cookie": f"mbs_session={session_token}",
                },
            )
        finally:
            app.dependency_overrides.clear()
            main_module.receipt_upload_service = previous_service

    assert response.status_code == 200
    assert response.json()["status"] == UploadStatus.ACCEPTED
    assert engine_service.calls == 1
