# Tenant setup — where we got to

Working notes from the live Microsoft 365 hookup (azure-setup.md), last
updated **2026-08-15**. Delete this file once `manage.py checkgraph` is green
— azure-setup.md is the permanent record.

## Decisions made during setup

- **Read-only first.** Stage one grants `Application Mail.Read` only; sending
  and Outlook tagging wait for stage two. See decisions.md ("The app goes
  live read-only") and azure-setup.md Part 4c.
- **Scope by group, not by list.** The management scope filters on membership
  of the mail-enabled security group `Service_and_sales_queue@expertsvc.com`
  (directory name `Service Sales Queue20260809234033`). Monitored mailboxes
  must be **direct** members — nesting silently drops them from scope — and
  *only* the monitored mailboxes may be members, because membership IS the
  scope.
- **The monitored set is three mailboxes: `craigz@`, `megank@`, `joyce@`**
  (2026-08-15, confirmed by Brad). The brief's list didn't survive contact
  with the tenant: `megan@` is really `megank@`; `casey@` and `info@` don't
  exist; `queue@` was never created and the forwarding channel is deferred
  (`FORWARD_MAILBOX` stays empty). See decisions.md ("Three mailboxes are
  monitored").

## Checklist

- [x] Parts 1–3 — app registration, client secret, enterprise-app IDs.
      The IDs and secret are in Brad's notes, never in this repo.
- [x] Part 4a — `New-ServicePrincipal`.
- [x] Part 4b — management scope `Expert Inbox Queue Mailboxes` created with
      `MemberOfGroup -eq '<group DN>'`. (First attempts failed on a
      `Set-` vs `New-` mixup and a paste that embedded line breaks in the DN
      — build the filter from `(Get-Group ...).DistinguishedName` instead.)
- [x] Part 4c stage one — `Application Mail.Read` granted 2026-08-15, scoped
      to `Expert Inbox Queue Mailboxes`, verified with
      `Get-ManagementRoleAssignment`. (The 2026-08-12 blocker was real: the
      admin account needed **explicit** membership in the **Organization
      Management** role group — the implicit Entra mapping doesn't pass the
      delegating-assignment check. Added via `Add-RoleGroupMember` from a
      second Global Admin account, then disconnect/reconnect. Portal note:
      that role group only exists in the **Exchange** admin center's Roles
      page, not the M365 admin center's.)
- [x] Scoping group pruned to the three mailboxes (2026-08-15). The group had
      EIGHT members — five extras (`margaret.greer@` shared mailbox,
      `kasiew@`, `jordanj@`, `olivia@`, `oswaldov@`) the app should not read.
      Plain `Remove-DistributionGroupMember` fails with *"only … a manager of
      the group"* — **`-BypassSecurityGroupManagerCheck`** (allowed by the
      Organization Management membership from 4c) is the fix.
- [x] Part 5 — verified 2026-08-15: `InScope True` for `craigz@`, `megank@`,
      `joyce@`; `False` for `kasiew@` (freshly pruned, so it doubles as proof
      the scope tracks group membership live). NB: `Couldn't find object` =
      the address isn't a recipient in the tenant at all, a different failure
      than `False`.
- [ ] Part 6 — **skipped on purpose** while read-only.
- [ ] **Part 7 — `.env` on the machine that runs the worker. ← RESUME HERE.**
      (`OUTLOOK_CATEGORY` and `FORWARD_MAILBOX` stay empty,
      `MONITORED_MAILBOXES` = the three addresses), then
      `python manage.py checkgraph` from `backend/` — every mailbox should
      say `ok`.
- [ ] First real run: `python -m app.worker`, watch mail land in the queue.

## Resume commands

The Exchange side is finished. What's left runs on the worker machine:

```powershell
# 1. Copy .env.example to .env in the repo root; fill MS_TENANT_ID,
#    MS_CLIENT_ID, MS_CLIENT_SECRET from Brad's notes. MONITORED_MAILBOXES is
#    already correct in the example; leave FORWARD_MAILBOX and
#    OUTLOOK_CATEGORY empty.

# 2. Prove the connection read-only — every mailbox should say ok
cd backend
python manage.py checkgraph

# 3. First real run — watch mail land in the queue
python -m app.worker
```

For the record, the Exchange state as verified 2026-08-15:

- Role assignment `Application Mail.Read-1346ab79-432a-4c99-915e-965976f674e4`,
  scope `Expert Inbox Queue Mailboxes`, assignee type `ServicePrincipal`.
- Scope filter: `MemberOfGroup` on `Service_and_sales_queue@expertsvc.com`,
  whose only members are `craigz@`, `megank@`, `joyce@`.
- `Test-ServicePrincipalAuthorization`: `True` for those three, `False` for
  `kasiew@` (out-of-group).
