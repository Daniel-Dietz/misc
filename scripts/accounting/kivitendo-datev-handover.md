# kivitendo DATEV file handover

**Status: Adapt first.** Created 2026-10-09 for a self-hosted kivitendo 4.0.1
installation with a separately reviewed SKR04, cash-VAT, EXTF 700 / batch 13
exporter. This repository does **not** contain that customized exporter.
Do not run against an arbitrary stock installation and assume compatibility.

The scripts prepare files locally. They do not connect to DATEV, mail a tax
adviser, post entries, mark transactions as exported or finalize bookings.
Windows reception, DATEV login and successful target import are separate steps.

## Requirements and installation

- Python 3.11+, Linux/systemd; Perl with kivitendo console dependencies and XML::LibXML.
- Reviewed `SL::DATEV::Profile`, matching database/client/adviser identity, EXTF 700/13 exporter.
- Invoice PDFs archived in kivitendo with immutable file-version GUIDs.
- Current official `Document_v060.xsd` and `Document_types_v060.xsd` in the same local directory.
- Runtime identity able to read kivitendo configuration, database and document files.
  The example service reuses kivitendo's www-data identity and sets PostgreSQL
  connections plus the accounting transaction to read-only.

Install the Python/Perl scripts root-owned under
`/usr/local/lib/kivitendo-datev-handover/`, and both XSD files under
`/usr/local/share/kivitendo-datev-handover/`. Download schemas from DATEV's
[XSD page](https://developer.datev.de/de/file-formats/details/datev-xml-interface-online/xsdminusfiles).
No schema is downloaded at runtime. Recheck changes before replacing it.

Adapt the example JSON and install as `/etc/kivitendo/datev-file-handover.json`,
readable by the runtime identity only. Keep actual client details out of git.
Create `/var/lib/kivitendo/datev-handover` owned by that identity, mode 0700.
Install the supplied service/timer in `/etc/systemd/system/`, then run a manual
preparation and inspect its output before enabling the timer.

```sh
runuser -u www-data -- python3 /usr/local/lib/kivitendo-datev-handover/kivitendo-datev-handover.py \
  --config /etc/kivitendo/datev-file-handover.json prepare
systemctl daemon-reload
systemctl enable --now kivitendo-datev-handover.timer
systemctl start kivitendo-datev-handover.service
```

The daily schedule is 02:15 Europe/Berlin with up to two minutes jitter.
This prepares through the current German calendar day, including a provisional
current month. It does not schedule automatic sending or importing.

## Output and integrity

`latest.json` identifies the last successful snapshot; `status.json` reports
the most recent run, including failure. Snapshots are immutable directories
named by semantic content hash. Unchanged data on the same cutoff reuses the
existing snapshot; generation timestamps do not create duplicate snapshots.

- `Buchungen/YYYY-MM/`: separate EXTF monthly files, locked flag 0, review notes.
- `Belegtransfer/Belege-XML.zip`: all unique invoice PDFs plus XSD-validated v6
  `document.xml`; preserves GUIDs, correct inbound/outbound types and client IDs.
- `Ergaenzende_Nachweise/`: deduplicated attachments; mapping in the manifest.
  These are supporting files for the adviser, not automatic Belegtransfer input.
- `manifest.json`: file hashes, references, person-account overview, source
  accounting fingerprints and unlinked journal rows. The person-account list
  is **not** an importable DATEV master-data batch.

XML uses **processID 2** and a repository under `Buchführung / kivitendo YYYY /
YYYY-MM`. DATEV will archive/finalize those **documents** when uploaded.
They do not enter the inbox to generate a second set of booking proposals.
The **bookings** themselves are transferred separately through EXTF with
finalization disabled. Do not upload to a live target before checking the
agreed document/archive workflow and the correct target client.

All invoice/payment rows originating in AR or AP require a PDF. GL rows may
have no direct invoice attachment; these are disclosed, not replaced by
invented documents. Additional bank statements remain separate supporting files.
The scripts never rewrite original PDFs or alter original accounting dates.

## Controlled outbox

```sh
runuser -u www-data -- python3 /usr/local/lib/kivitendo-datev-handover/kivitendo-datev-handover.py \
  --config /etc/kivitendo/datev-file-handover.json queue \
  --period YYYY-MM --snapshot HASH_FROM_LATEST_JSON
```

This refreshes preparation, verifies the chosen snapshot and queues a closed
month locally. Repeat queueing of the same period is rejected. `--allow-partial`
is only for an explicitly agreed partial-month test; future changes to such a
queued month will require reconciliation, not a second full-month import.

The outbox deduplicates PDF GUIDs across periods. Keep earlier packets and their
manifests: deleting an earlier outbox entry also removes its duplicate record.
Outbox status means **queued locally**, never delivered or imported. Do not
point a receiver at `snapshots/` or copy all historical snapshots into DATEV.
Only approved outbox packets belong in the delivery workflow. Transmission
receipts and DATEV import acknowledgements are not yet implemented here.

## Windows and tax-adviser continuation

1. Select an accessible Windows PC, install the official free DATEV Belegtransfer,
   and authenticate with the authorized DATEV user.
2. Configure a dedicated receive folder for the correct adviser/client. Match
   the installed Belegtransfer version's XML package detection/settings.
3. Add an authenticated transfer from the Linux outbox to a **Windows staging
   folder**. Verify hashes and persistent delivery state before atomically
   placing only `Belege-XML.zip` in Belegtransfer's watched folder.
4. Keep EXTF CSVs in a separate Kanzlei handover folder. The adviser imports them
   into Kanzlei-Rechnungswesen after receipt uploads succeeded; ordinary DUO
   document upload is not an EXTF booking import.
5. Start with one agreed test period. Verify client, short first fiscal year,
   cash VAT, account balances, credit note and linked PDFs. Record successful
   import before enabling unattended production delivery.

At initial implementation only Linux devices were accessible. Therefore no
Windows target, share, SSH recipient or scheduled receiver is assumed or
configured. DATEV/SmartLogin sessions may require user interaction; this is not
claimed to be a permanently unattended DATEV login.

## Verification and recovery

The accompanying test script operates on temporary copies and checks XML
identity, archive mode, inbound/outbound types, PDF hashes, duplicate periods,
stale snapshots, wrong clients, partial-month blocking and tampered files.

```sh
python3 test-kivitendo-datev-handover.py --config /etc/kivitendo/datev-file-handover.json
```

Failed preparation leaves previous snapshots intact, updates `status.json` and
exits nonzero. Console errors are stored in private `last-error.log`. The timer
retries on its next run; monitor systemd failures and this status file.
To stop scheduled preparation: `systemctl disable --now kivitendo-datev-handover.timer`.
No automatic retention/deletion is implemented: include the output directory
in backups and monitor disk usage. Never reset the outbox ledger merely to
resend; first reconcile what actually reached DATEV.

Validation is local technical validation, **not** confirmation of an actual
DATEV import or a substitute for the tax adviser's approval of accounting.

Verified on the original Debian 13 host: accounting fields matched the
previously reviewed export after excluding the newly added PDF-link field and
generation timestamp; all accounting table fingerprints stayed unchanged.
XSD v6 validation, invoice PDF hashes, repeat preparation and all failure-case
tests passed. The systemd service completed successfully under its filesystem
restrictions. No DATEV target import or Windows receiver was tested.
