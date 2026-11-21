# Python-KontAKTNovaToPDF

Converts a single **KMD Nova** document to PDF and stores it in KontAKT's local file store, for the **KontAKT** aktindsigt (FOI request) system. The Nova counterpart to `Python-KontAKTGOToPDF`.

KontAKT triggers this once per document when a caseworker transfers a case's files.

## What it does

For one Nova document:

1. Looks up the document (its `documentUuid` and file extension) by document number.
2. Downloads the original file.
3. Converts it to PDF with the shared [`oomtm`](https://github.com/mtm-aarhus/oomtm) library (`oomtm.convert`), the same way every KontAKT PDF robot does: WeasyPrint for e-mails, HTML, text and CSV, LibreOffice for Office files, Pillow for images.
4. POSTs the PDF bytes into KontAKT's local file store (`POST /api/v1/cases/{id}/documents/{doc_id}/store`) — one call does the upload and records name/size/SHA-256/status.

Files that can't be converted (video, audio, unknown types, broken files) are stored **as their original**, with oomtm's reason as the note: still delivered, just not screenable. A mail's attachments are their own documents in Nova, so a mail's PDF is just the mail.

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

The shared [`oomtm`](https://github.com/mtm-aarhus/oomtm) library (`nova`, `convert`), pinned to a commit, with the `[pdf]` extra. On the first run, `reset.open_all` makes oomtm install its engines without admin rights, once per machine: LibreOffice (~350 MB) and WeasyPrint's Windows libraries (~30 MB), both from [oomtm_setup](https://github.com/mtm-aarhus/oomtm_setup) first.
