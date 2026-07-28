# Python-KontAKTNovaToPDF

Converts a single **KMD Nova** document to PDF and stores it in KontAKT's local file store, for the **KontAKT** aktindsigt (FOI request) system. The Nova counterpart to `Python-KontAKTGOToPDF`.

KontAKT triggers this once per document when a caseworker transfers a case's files.

## What it does

For one Nova document:

1. Looks up the document (its `documentUuid` and file extension) by document number.
2. Downloads the original file.
3. Converts it to PDF via the shared [`oomtm`](https://github.com/mtm-aarhus/oomtm) library (LibreOffice / Pillow for images / e-mail rendering). Nova has no built-in converter, so all conversion happens here.
4. POSTs the PDF bytes into KontAKT's local file store (`POST /api/v1/cases/{id}/documents/{doc_id}/store`) — one call does the upload and records name/size/SHA-256/status.

Files that can't be converted are stored **as their original** (still delivered, just not OCR-screenable); video / audio / unconvertible binaries are skipped.

## Input (one document)

| Field | Meaning |
|-------|---------|
| `kontakt_case_id` | KontAKT case id |
| `doc_id` | KontAKT document id (the store is addressed by this id) |
| `source_case_id` | Nova case number |
| `dok_id` | Nova document number |
| `akt_id` | Act number (zero-padded in the stored filename) |
| `title` | Document title |
| `case_title` | KontAKT case title |

## Output

The PDF (or unconverted original) written into KontAKT's file store; the `/store` endpoint records the name, size, SHA-256 and status. Errors are reported via the `/file` status callback.

## Required configuration

- Constant `KMDNovaURL` — Nova API base URL
- Constant `KMDTokenTimestamp` — cached token issue time (updated automatically)
- Credential `KMDClientSecret` — KMD OAuth2 client secret
- Credential `KMDAccessToken` — username = token URL, password = cached bearer token (updated automatically)
- Credential `KontAKTAPI` — username = base URL, password = API key

## Dependencies

The shared [`oomtm`](https://github.com/mtm-aarhus/oomtm) library (`nova`, `pdf`). PDF conversion auto-installs LibreOffice on the worker if it's missing (no admin required).
