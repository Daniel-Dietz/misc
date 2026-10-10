# kivitendo DATEV file handover

**Status: Adapt first.** Created 2026-10-09 for a self-hosted kivitendo 4.0.1
installation with a separately reviewed SKR04, cash-VAT, EXTF 700 / batch 13
exporter. This repository does **not** contain that customized exporter.
Do not run against an arbitrary stock installation and assume compatibility.

The Linux scripts prepare files locally. The optional Windows receiver fetches
explicitly queued packets and can hand their PDF/XML ZIP to an installed DATEV
Belegtransfer watcher. The scripts do not log in to DATEV, mail a tax adviser,
post entries, mark transactions as exported or finalize bookings. Successful
upload and target import require separate confirmation.

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
Only approved outbox packets belong in the delivery workflow. Windows fetch and
local watcher publication have separate state; DATEV transmission receipts and
import acknowledgements are not yet implemented here. New outbox manifests use
schema 2 with client identity and source file hashes. The SSH reader rejects old
schema-1 packets; reconcile any real deliveries before migrating such packets.

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

The original Windows 11 receiver was added on 2026-10-10, using DATEV
Belegtransfer 5.5. DATEV/SmartLogin sessions require user interaction; this is
not claimed to be a permanently unattended DATEV login. Belegtransfer requires
login before a target directory can be created. The receiver stays in staging
mode until that directory and the agreed test are ready.

### Restricted Linux reader

Install `kivitendo-datev-serve.py` root-owned, mode 0644, next to the preparer.
Use a dedicated system account with no password authentication or general
shell access, a root-owned home/authorized_keys, and `restrict` on its key.
The forced command is fixed by root-owned sshd configuration, for example:

```text
Match User datev-transfer
    AuthenticationMethods publickey
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile /var/lib/datev-transfer/.ssh/authorized_keys
    ForceCommand /usr/bin/python3 /usr/local/lib/kivitendo-datev-handover/kivitendo-datev-serve.py --config /etc/kivitendo/datev-reader.json
    DisableForwarding yes
    PermitTTY no
    PermitUserRC no
    MaxSessions 2
Match all
```

Validate with `sshd -t` before reloading ssh. Adapt the reader example JSON;
it contains only the output root and client identity, no database credentials.
Grant this account traversal only through otherwise-private parent directories,
read access to its reader config and `status.json`, and read/traverse access to
`outbox/`. Never add it to the web application's general access group or grant
sudo. Set `reader_user` in the preparer config so newly replaced status files
and newly queued packets receive read-only ACLs through `setfacl`.

The only SSH requests are `index` and `get YYYY-MM BASENAME`. Arbitrary shell,
SCP/SFTP, path traversal and file writes are rejected. The reader refuses
delivery if preparation failed, queued periods changed or the successful
preparation is over 48 hours old. A file is limited to 64 MiB. No extra network
listener is installed; Windows uses existing SSH connectivity (LAN/VPN).

### Windows reception

Create a private root in the user's LocalAppData, outside cloud-synchronized
folders, granting access only to that user, SYSTEM and Administrators. Create
`Config`, `Keys`, `Scripts`, `Staging`, `Received`, `Belegtransfer`, `Kanzlei`,
and `Logs`. Keep the entire root on one local volume for atomic renames.
Create a dedicated SSH key **on Windows**; install only its public key on Linux.
The scheduled key has no passphrase, so protect the private file with the root's
restricted ACL and device/disk security. Do not reuse a privileged SSH key.

Configure an SSH alias named `datev-handover` with the correct server/user,
dedicated IdentityFile, pinned UserKnownHostsFile, `StrictHostKeyChecking yes`,
`IdentitiesOnly yes`, `BatchMode yes`, `PasswordAuthentication no`,
`KbdInteractiveAuthentication no`, `RequestTTY no`, `ClearAllForwardings yes`,
and `ConnectTimeout 10`. Obtain the host public key/fingerprint through the
existing trusted management connection; do not accept an unverified key.
Use a dedicated `-F` config so unrelated SSH settings cannot alter the route.

Install `Receive-KivitendoDatev.ps1` in `Scripts` and adapt the receiver example
JSON in `Config`. Start with `publish_enabled: false`. Run it explicitly:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned `
  -File "$root\Scripts\Receive-KivitendoDatev.ps1" `
  -Config "$root\Config\receiver.json"
```

`RemoteSigned` applies only to this process; no persistent execution policy is
changed. Domain/group policy remains authoritative. The receiver restores the
real OS ProgramData/COMPUTERNAME environment values only for its SSH child,
because some remote-agent sessions omit them and Win32 OpenSSH then exits 255.

Schedule that command in Task Scheduler under the desktop user's interactive
token with **limited privileges**, at logon and every 30 minutes. Do not save
the user's password. Enable start-when-available and network-required, allow
battery operation, ignore overlapping runs and limit a run to ten minutes.
The PC must be awake, the user logged in, and the server reachable over LAN/VPN.
DATEV login is independent of this scheduled fetch.

- `Received/YYYY-MM/`: immutable verified original packet, including manifest.
- `Kanzlei/YYYY-MM/`: CSV and an explicit note that import is unconfirmed.
- `Belegtransfer/`: only the XML ZIP, once publication is enabled.
- `state.json`: persistent per-period packet hash and publication status.
- `status.json`: last fetch attempt; `Logs/receiver-last-run.log`: latest run.

The first verified download is recorded as `staged`. After enabling publication,
the ZIP is copied to Staging and atomically renamed into the watched directory
with its period/snapshot in the filename. The receiver records
`published_to_local_watcher` and never recreates a consumed file. If a crash
leaves `publish_pending` but the watched file is absent, it **stops**: check
DATEV's own transfer history before deciding whether it was consumed or never
placed. Do not reset state.json or republish blindly. `published` never means
successful DATEV upload, and the CSV is never imported by this receiver.

Set `watch_subdirectory` to the actual adviser/client/document-type directory
created by Belegtransfer, relative to `Belegtransfer` (for example
`1001-1\\ohne Belegtyp`). The setting permits only relative directory segments;
the receiver rejects reparse points before publication. Belegtransfer 5 detects
XML ZIP packages without the old separate XML directory-type option; document
types are specified in the generated XML. Verify the actual target in its UI.
Keep its uploaded-file archive in a separate private local directory, outside
the watched tree and any default cloud-synchronized Documents folder.
Point Belegtransfer only at the dedicated directory for the verified client.
Do not monitor Staging,
Received, Kanzlei, Tests or the whole root. Leave `publish_enabled` false until
the target is verified. Only explicitly queued periods are fetched; neither
daily preparation nor Windows polling automatically queues a new month.

Disable the Windows task to pause fetching; set `publish_enabled` false to stop
new watcher publication (this cannot recall a ZIP already in the watcher).
To revoke this machine's server access, remove its authorized key and disable
the dedicated SSH account/configuration after checking for other consumers.

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
restrictions. Windows receiver validation and DATEV target import are separate;
do not infer target acceptance from local tests.

`test-kivitendo-datev-serve.py` uses synthetic temporary data and no network.
`Test-KivitendoDatevReceiver.ps1 -Config ...` tests the real read-only connection
and isolated copies under a unique private `Tests` subdirectory. It exercises
publication/deduplication only in an **unwatched test directory**. It retains
copies for inspection; those contain financial data and need the same privacy
and retention treatment as Received. No actual DATEV upload occurs in the tests.

Verified on the original Windows 11 / PowerShell 5.1 host: pinned SSH receipt,
all six isolated receiver scenarios, and an actual scheduled run under the
limited interactive user succeeded. The reader's six synthetic test methods
passed, and the dedicated account could neither execute an arbitrary command,
write the outbox nor read the application's private configuration/snapshots.
The existing handover regression tests and the hardened Linux service passed
again after adding schema-2 manifests and publication ACLs. This validation
does not establish acceptance of any booking batch in DATEV Rechnungswesen.
