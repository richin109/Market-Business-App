from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from sqlalchemy import select

from mbs.db import SessionLocal
from mbs.media_assets import MediaAssetService
from mbs.models import ReceiptUpload
from mbs.receipts.duplicates import InMemoryPerceptualDuplicateStore, PillowPerceptualHasher
from mbs.receipts.storage import (
    LocalProtectedFileStore,
    UnavailablePDFScanner,
    receipt_storage_root,
)
from mbs.receipts.upload import DEFAULT_MAX_FILE_BYTES, ReceiptUploadService
from mbs.routers.auth import router as auth_router
from mbs.routers.items import router as items_router
from mbs.routers.receipts import router as receipts_router
from mbs.routers.remembered_rules import router as remembered_rules_router
from mbs.routers.settings import router as settings_router
from mbs.routers.stores import router as stores_router
from mbs.settings import read_setting


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    perceptual_store = InMemoryPerceptualDuplicateStore()
    with SessionLocal() as session:
        phash_threshold = read_setting(session, "phash_duplicate_threshold")
        if phash_threshold is None:
            raise RuntimeError("The phash_duplicate_threshold setting must not be NULL")
        accepted_fingerprints = session.execute(
            select(ReceiptUpload.source_sha256, ReceiptUpload.perceptual_hash).where(
                ReceiptUpload.perceptual_hash.is_not(None),
                ReceiptUpload.duplicate_status.is_distinct_from("POSSIBLE_DUPLICATE"),
                ReceiptUpload.duplicate_status.is_distinct_from("CONFIRMED_DUPLICATE"),
            )
        )
        for source_sha256, fingerprint in accepted_fingerprints:
            if fingerprint is not None:
                perceptual_store.save(source_sha256, fingerprint)
    file_store = LocalProtectedFileStore(receipt_storage_root())
    application.state.media_asset_service = MediaAssetService(file_store)
    application.state.receipt_upload_service = ReceiptUploadService(
        max_file_bytes=int(os.environ.get("RECEIPT_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES)),
        file_store=file_store,
        malware_scanner=UnavailablePDFScanner(),
        perceptual_hasher=PillowPerceptualHasher(),
        perceptual_store=perceptual_store,
        perceptual_threshold=int(phash_threshold),
    )
    yield


app = FastAPI(title="Market Business System", lifespan=lifespan)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'self'; form-action 'self'",
}


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if response.headers.get("content-type", "").startswith("text/html"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(auth_router)
app.include_router(items_router)
app.include_router(receipts_router)
app.include_router(remembered_rules_router)
app.include_router(settings_router)
app.include_router(stores_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
