from io import BytesIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mbs.auth import Role, create_user
from mbs.models import AuditLog, ReceiptOutboxEvent, ReceiptUpload
from mbs.receipts.duplicates import InMemoryPerceptualDuplicateStore, PillowPerceptualHasher
from mbs.receipts.storage import ClamAVScanner, LocalProtectedFileStore
from mbs.receipts.upload import ReceiptUploadService, UploadStatus
from tests.database import postgres_test_url


class FixedHasher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fingerprint(self, source: bytes, media_type: str) -> str:
        self.calls.append(media_type)
        return "a" * 16


def _database(path: Path) -> tuple[Engine, Session]:
    engine = create_engine(postgres_test_url(path))
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgres_test_url(path).replace("%", "%%"))
    command.upgrade(config, "head")
    session = Session(engine)
    return engine, session


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 6), color=(30, 100, 170)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_upload_stages_file_and_outbox_without_scanning_or_ocr(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "staged-image.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            malware_scanner=ClamAVScanner(lambda source: (_ for _ in ()).throw(AssertionError())),
            perceptual_hasher=FixedHasher(),
        )
        source = _png()

        result = service.upload(session, source, "image/png", manager.id)
        session.commit()

        upload = session.get(ReceiptUpload, result.upload_pk)
        assert result.status is UploadStatus.QUEUED
        assert result.file_key is not None
        assert upload is not None and upload.processing_status == "QUEUED"
        assert upload.scan_status == "NOT_SCANNED"
        assert upload.staging_file_key is not None
        assert (tmp_path / "files" / upload.staging_file_key).read_bytes() == source
        assert not (tmp_path / "files" / result.file_key).exists()
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
        assert (
            session.scalar(
                select(AuditLog).where(AuditLog.event_type == "RECEIPT_UPLOAD_NOT_SCANNED")
            )
            is not None
        )
    finally:
        session.close()
        engine.dispose()


def test_exact_upload_retry_returns_existing_row_without_another_event(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "staged-retry.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        service = ReceiptUploadService(file_store=LocalProtectedFileStore(tmp_path / "files"))
        source = _png()

        first = service.upload(session, source, "image/png", manager.id)
        session.commit()
        retry = service.upload(session, source, "image/png", manager.id)
        session.commit()

        assert retry.status is UploadStatus.EXACT_DUPLICATE
        assert retry.idempotent is True
        assert retry.upload_pk == first.upload_pk
        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 1
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
        upload = session.get(ReceiptUpload, first.upload_pk)
        assert upload is not None and upload.scan_status == "NOT_SCANNED"
    finally:
        session.close()
        engine.dispose()


def test_pdf_upload_fails_closed_when_scanner_unavailable(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "pdf-unavailable.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            malware_scanner=ClamAVScanner(lambda source: None),
        )

        result = service.upload(session, b"%PDF-1.7 synthetic", "application/pdf", manager.id)

        assert result.status is UploadStatus.SCAN_PENDING
        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 0
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 0
        assert list((tmp_path / "files").rglob("*")) == []
    finally:
        session.close()
        engine.dispose()


def test_infected_pdf_is_rejected_before_staging(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "pdf-infected.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            malware_scanner=ClamAVScanner(lambda source: False),
        )

        result = service.upload(session, b"%PDF-1.7 synthetic", "application/pdf", manager.id)

        assert result.status is UploadStatus.MALWARE_REJECTED
        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 0
        rejection = session.scalar(
            select(AuditLog).where(AuditLog.event_type == "RECEIPT_UPLOAD_MALWARE_REJECTED")
        )
        assert rejection is not None
        assert rejection.entity_id == result.source_sha256
        assert rejection.actor == str(manager.id)
    finally:
        session.close()
        engine.dispose()


def test_pdf_upload_with_clean_scanner_creates_outbox_event(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "pdf-clean.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        hasher = FixedHasher()
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            malware_scanner=ClamAVScanner(lambda source: True),
            perceptual_hasher=hasher,
        )

        result = service.upload(
            session,
            b"%PDF-1.7 synthetic",
            "application/pdf",
            manager.id,
        )
        session.commit()

        assert result.status is UploadStatus.QUEUED
        upload = session.get(ReceiptUpload, result.upload_pk)
        assert upload is not None and upload.scan_status == "CLEAN"
        accepted = session.scalar(
            select(AuditLog).where(AuditLog.event_type == "RECEIPT_UPLOAD_ACCEPTED")
        )
        assert accepted is not None
        assert accepted.entity_id == upload.upload_pk
        assert "scan_status=CLEAN" in (accepted.details or "")
        assert hasher.calls == []
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 1
    finally:
        session.close()
        engine.dispose()


def test_near_match_is_held_and_creates_no_processing_event(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "near-match.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        duplicate_store = InMemoryPerceptualDuplicateStore()
        duplicate_store.save("a" * 64, "a" * 16)
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            perceptual_hasher=FixedHasher(),
            perceptual_store=duplicate_store,
        )

        result = service.upload(session, _png(), "image/png", manager.id)
        session.commit()
        retry = service.upload(session, _png(), "image/png", manager.id)
        session.commit()

        upload = session.get(ReceiptUpload, result.upload_pk)
        assert result.status is UploadStatus.POSSIBLE_DUPLICATE
        assert retry.status is UploadStatus.POSSIBLE_DUPLICATE
        assert retry.idempotent is True
        assert retry.upload_pk == result.upload_pk
        assert result.matched_source_sha256 == "a" * 64
        assert upload is not None and upload.processing_status == "POSSIBLE_DUPLICATE"
        assert upload.scan_status == "NOT_SCANNED"
        assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == 0
    finally:
        session.close()
        engine.dispose()


def test_near_match_resolution_recovers_staged_bytes_and_audits_both_decisions(
    tmp_path: Path,
) -> None:
    for process_as_new in (False, True):
        engine, session = _database(tmp_path / f"near-match-resolution-{process_as_new}.db")
        try:
            manager = create_user(session, "manager", "manager password", Role.MANAGER)
            file_store = LocalProtectedFileStore(tmp_path / f"files-{process_as_new}")
            duplicate_store = InMemoryPerceptualDuplicateStore()
            duplicate_store.save("a" * 64, "a" * 16)
            source = _png()
            service = ReceiptUploadService(
                file_store=file_store,
                perceptual_hasher=FixedHasher(),
                perceptual_store=duplicate_store,
            )
            held = service.upload(session, source, "image/png", manager.id)
            session.commit()
            assert held.upload_pk is not None
            held_upload_pk = held.upload_pk
            upload = session.get(ReceiptUpload, held_upload_pk)
            assert upload is not None and upload.staging_file_key is not None
            staging_key = upload.staging_file_key
            assert file_store.read(staging_key) == source

            restarted_service = ReceiptUploadService(
                file_store=file_store,
                perceptual_hasher=FixedHasher(),
                perceptual_store=InMemoryPerceptualDuplicateStore(),
            )
            resolved = restarted_service.resolve_possible_duplicate(
                session, held_upload_pk, manager.id, process_as_new
            )
            session.commit()

            upload = session.get(ReceiptUpload, held_upload_pk)
            assert upload is not None and file_store.read(staging_key) == source
            expected_event = (
                "RECEIPT_UPLOAD_NEAR_MATCH_RESOLVED"
                if process_as_new
                else "RECEIPT_UPLOAD_DUPLICATE_CONFIRMED"
            )
            assert (
                session.scalar(
                    select(AuditLog).where(
                        AuditLog.event_type == expected_event,
                        AuditLog.entity_id == held.upload_pk,
                    )
                )
                is not None
            )
            assert resolved.status is (
                UploadStatus.QUEUED if process_as_new else UploadStatus.EXACT_DUPLICATE
            )
            assert upload.processing_status == ("QUEUED" if process_as_new else "DUPLICATE")
            assert session.scalar(select(func.count(ReceiptOutboxEvent.id))) == int(process_as_new)
        finally:
            session.close()
            engine.dispose()


def test_distinct_image_is_not_held_as_a_perceptual_duplicate(tmp_path: Path) -> None:
    def image_bytes(shape: str) -> bytes:
        image = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(image)
        if shape == "half-rectangle":
            draw.rectangle((0, 0, 31, 63), fill="black")
        else:
            draw.ellipse((16, 16, 48, 48), fill="black")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    engine, session = _database(tmp_path / "phash-false-positive.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        hasher = PillowPerceptualHasher()
        first_source = image_bytes("half-rectangle")
        second_source = image_bytes("circle")
        first_hash = hasher.fingerprint(first_source, "image/png")
        second_hash = hasher.fingerprint(second_source, "image/png")
        assert (int(first_hash, 16) ^ int(second_hash, 16)).bit_count() > 6
        duplicate_store = InMemoryPerceptualDuplicateStore()
        duplicate_store.save("d" * 64, first_hash)
        service = ReceiptUploadService(
            file_store=LocalProtectedFileStore(tmp_path / "files"),
            perceptual_hasher=hasher,
            perceptual_store=duplicate_store,
        )

        result = service.upload(session, second_source, "image/png", manager.id)

        assert result.status is UploadStatus.QUEUED
        assert result.matched_source_sha256 is None
    finally:
        session.close()
        engine.dispose()


def test_upload_rejects_mime_signature_mismatch(tmp_path: Path) -> None:
    engine, session = _database(tmp_path / "invalid-upload.db")
    try:
        manager = create_user(session, "manager", "manager password", Role.MANAGER)
        service = ReceiptUploadService(file_store=LocalProtectedFileStore(tmp_path / "files"))

        try:
            service.upload(session, b"not an image", "image/png", manager.id)
        except ValueError:
            pass
        else:
            raise AssertionError("Expected invalid image to be rejected")

        assert session.scalar(select(func.count(ReceiptUpload.upload_pk))) == 0
    finally:
        session.close()
        engine.dispose()
