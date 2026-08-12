# Tenant setup — where we got to

Working notes from the live Microsoft 365 hookup (azure-setup.md), last
updated **2026-08-12**. Delete this file once `manage.py checkgraph` is green
— azure-setup.md is the permanent record.

## Decisions made during setup

- **Read-only first.** Stage one grants `Application Mail.Read` only; sending
  and Outlook tagging wait for stage two. See decisions.md ("The app goes
  live read-only") and azure-setup.md Part 4c.
- **Scope by group, not by list.** The management scope filters on membership
  of the mail-enabled security group `Service_and_sales_queue@expertsvc.com`
  (directory name `Service Sales Queue20260809234033`). All six mailboxes
  must be **direct** members — nesting silently drops them from scope.

## Checklist

- [x] Parts 1–3 — app registration, client secret, enterprise-app IDs.
      The IDs and secret are in Brad's notes, never in this repo.
- [x] Part 4a — `New-ServicePrincipal`.
- [x] Part 4b — management scope `Expert Inbox Queue Mailboxes` created with
      `MemberOfGroup -eq '<group DN>'`. (First attempts failed on a
      `Set-` vs `New-` mixup and a paste that embedded line breaks in the DN
      — build the filter from `(Get-Group ...).DistinguishedName` instead.)
- [ ] **Part 4c stage one — `Application Mail.Read`. ← RESUME HERE.**
      Blocked on: *"You must be assigned a delegating role assignment…"* —
      Brad's admin account needs **explicit** membership in the
      **Organization Management** role group (the implicit Entra mapping
      doesn't pass this check), then disconnect/reconnect PowerShell.
      Details in azure-setup.md Troubleshooting.
- [ ] Part 5 — `Test-ServicePrincipalAuthorization`: `InScope True` for the
      six mailboxes, `False` for anything else.
- [ ] Part 6 — **skipped on purpose** while read-only.
- [ ] Part 7 — `.env` on the machine that runs the worker
      (`OUTLOOK_CATEGORY` stays empty), then `python manage.py checkgraph`
      from `backend/` — every mailbox should say `ok`.
- [ ] First real run: `python -m app.worker`, watch mail land in the queue.

## Resume commands

```powershell
Connect-ExchangeOnline

# Sanity: the scope and the group membership survived
Get-ManagementScope "Expert Inbox Queue Mailboxes" | Format-List Name,RecipientFilter
Get-DistributionGroupMember -Identity "Service_and_sales_queue@expertsvc.com" | Format-Table Name,PrimarySmtpAddress

# The blocked step (after the Organization Management fix)
New-ManagementRoleAssignment -App "<Application ID>" -Role "Application Mail.Read" -CustomResourceScope "Expert Inbox Queue Mailboxes"

# Part 5
Test-ServicePrincipalAuthorization -Identity "<Application ID>" -Resource "craigz@expertsvc.com" | Format-Table
Test-ServicePrincipalAuthorization -Identity "<Application ID>" -Resource "<a mailbox NOT in the group>" | Format-Table
```

If the role assignment still refuses after the fix and a reconnect, this
shows who actually holds the delegating grant:

```powershell
Get-ManagementRoleAssignment -Role "Application Mail.Read" -Delegating | Format-Table Name,RoleAssignee,RoleAssignmentDelegationType
```
