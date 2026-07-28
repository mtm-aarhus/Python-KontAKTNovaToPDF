"""KontAKT Nova → PDF robot.

Queue-driven, one queue element per document. Nova has no built-in PDF
converter, so for a single Nova document it:
  1. looks up the document (documentUuid + file extension) by document number,
  2. downloads the original file,
  3. converts it to PDF via oomtm.pdf (LibreOffice / Pillow / email-render),
  4. POSTs the PDF bytes into KontAKT's local file store (POST .../store);
     files that can't be converted are stored as their original instead.

Videos / audio / unconvertible binaries are skipped (status='skipped').

The Nova token and cached credentials live on the ``Client`` opened in
``reset.open_all`` and are reused across every queue element (the framework
reconnects via ``reset.reset`` on a retry).

Queue payload (set by KontAKT's "Hent filer" trigger):
    {
        "kontakt_case_id": 11,
        "doc_id": 42,
        "source_case_id": "S2024-12345",
        "dok_id": "D2024-9",
        "akt_id": 5,
        "title": "Ansøgning",
        "case_title": "Aktindsigt i miljøsag"
    }

OO config:
    Constant   KMDNovaURL
    Constant   KMDTokenTimestamp
    Credential KMDClientSecret
    Credential KMDAccessToken        — username = token URL, password = cached token
    Credential KontAKTAPI            — username = base URL, password = X-API-Key
"""
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueElement
import json
import tempfile
from pathlib import Path

import requests

from robot_framework import reset
from oomtm import nova as oomtm_nova
from oomtm import pdf as oomtm_pdf
from oomtm import sharepoint as sp  # filename helpers only (build_filename, sanitize_title)


def process(
    orchestrator_connection: OrchestratorConnection,
    queue_element: QueueElement | None = None,
    client: "reset.Client | None" = None,
) -> None:
    orchestrator_connection.log_trace("Running process.")
    if queue_element is None:
        raise RuntimeError("KontAKTNovaToPDF is queue-driven; no queue_element given.")
    if client is None:  # e.g. a manual run outside the queue framework
        client = reset.open_all(orchestrator_connection)

    payload = json.loads(queue_element.data or "{}")
    case_id = int(payload["kontakt_case_id"])
    doc_id = int(payload["doc_id"])
    source_case_id = str(payload.get("source_case_id") or "").strip()
    dok_id = str(payload["dok_id"]).strip()
    akt_id = payload.get("akt_id")
    title = str(payload.get("title") or "").strip()
    case_title = str(payload.get("case_title") or "").strip()

    orchestrator_connection.log_info(f"NovaToPDF case={case_id} doc={doc_id} dok={dok_id}")
    _callback(orchestrator_connection, client, case_id, doc_id, {"status": "converting"})

    try:
        result = _convert_and_store(
            orchestrator_connection, client, case_id, doc_id, source_case_id, dok_id, akt_id, title,
        )
    except Exception as exc:
        orchestrator_connection.log_info(f"NovaToPDF failed: {exc!r}")
        _callback(orchestrator_connection, client, case_id, doc_id, {"status": "error", "note": str(exc)[:500]})
        raise

    # On success the /store endpoint already recorded status + metadata; only an
    # error needs reporting back via the /file status callback.
    if result.get("status") == "error":
        _callback(orchestrator_connection, client, case_id, doc_id, result)
    orchestrator_connection.log_info(f"NovaToPDF done doc={doc_id}: {result.get('status')}")


# ----- Conversion + upload ---------------------------------------------------


def _convert_and_store(orchestrator_connection, client, case_id, doc_id, source_case_id, dok_id, akt_id, title):
    nova_url = client.nova_url
    token = client.token

    info = oomtm_nova.lookup_document(
        token=token, base_url=nova_url, document_number=dok_id, case_number=source_case_id,
    )
    if not info:
        return {"status": "error", "note": f"Dokument {dok_id} ikke fundet i Nova."}
    document_uuid = info.get("documentUuid")
    ext = (info.get("fileExtension") or "").lower().lstrip(".")
    if not document_uuid:
        return {"status": "error", "note": f"Dokument {dok_id} mangler documentUuid i Nova."}

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        src = work / f"{dok_id}.{ext or 'bin'}"
        oomtm_nova.download_file(token=token, base_url=nova_url, document_uuid=document_uuid, local_path=str(src))

        if ext == "pdf":
            upload_path, upload_ext, status, note = src, "pdf", "ready", ""
        elif oomtm_pdf.classify(ext) == "skip":
            upload_path, upload_ext, status, note = src, (ext or "bin"), "uploaded_original", (
                f"Filtypen .{ext} kan ikke konverteres til PDF — uploadet som original "
                "(bliver ikke OCR-screenet)."
            )
        else:
            pdf_path, cstatus, cnote = oomtm_pdf.convert_to_pdf(
                src, ext, work, auto_install=True, log=orchestrator_connection.log_info,
            )
            if cstatus == "ready" and pdf_path is not None:
                upload_path, upload_ext, status, note = pdf_path, "pdf", "ready", ""
            else:
                upload_path, upload_ext, status, note = src, (ext or "bin"), "uploaded_original", (
                    cnote or "Kunne ikke konverteres til PDF — original uploadet (bliver ikke OCR-screenet)."
                )

        akt = akt_id if akt_id is not None else 0
        filename = sp.build_filename(akt, dok_id, sp.sanitize_title(title), upload_ext)
        _store_file(client, case_id, doc_id, upload_path, filename,
                    "pdf" if status == "ready" else "original", note)
        return {"status": status}


def _store_file(client, case_id, doc_id, local_path, filename, kind, note=""):
    """POST the produced file's bytes into KontAKT's local store (replaces the
    conversion). The /store endpoint records name/size/hash/status, so no
    separate metadata callback is needed. ``kind`` is 'pdf' or 'original'."""
    with open(local_path, "rb") as fh:
        r = requests.post(
            f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/store",
            params={"filename": filename, "kind": kind, "note": note or ""},
            headers={"X-API-Key": client.kontakt_key, "Content-Type": "application/octet-stream"},
            data=fh, timeout=600,
        )
    r.raise_for_status()


# ----- KontAKT callback ------------------------------------------------------


def _callback(orchestrator_connection, client, case_id: int, doc_id: int, body: dict) -> None:
    try:
        requests.post(
            f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/file",
            headers={"X-API-Key": client.kontakt_key, "Content-Type": "application/json"},
            json=body, timeout=30,
        )
    except Exception as exc:  # pylint: disable=broad-except
        orchestrator_connection.log_info(f"Callback to KontAKT failed: {exc!r}")
