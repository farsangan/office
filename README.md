# Office

Farsangan's custom features for Frappe, as one Frappe app. Each feature is a module
(listed in `office/modules.txt`, code in `office/<module>/`):

- [Google Contacts Sync](#google-contacts-sync): two-way sync between Frappe Contacts and Google Contacts

## Install (frappe_docker)

1. Push this folder to a git repository.
2. Add it to the same `apps.json` you used for hrms, crm, helpdesk…, rebuild the image and
   restart the containers:
   ```json
   { "url": "https://github.com/<you>/office", "branch": "main" }
   ```
3. Install it on the site (in the backend container):
   ```bash
   bench --site <site> install-app office
   bench --site <site> enable-scheduler
   ```

## Tests

```bash
bench --site <test-site> set-config allow_tests true
bench --site <test-site> run-tests --app office
```

`office/google_contacts_sync/test_mapping.py` needs no database and also runs with
`python -m unittest office.google_contacts_sync.test_mapping`.

## Google Contacts Sync

Two-way sync between Frappe **Contacts** and **Google Contacts**, built on Frappe's own
Google Contacts integration (same OAuth setup, same "Google Contacts" accounts).

| Change in…         | Result                                                         | When              |
|--------------------|----------------------------------------------------------------|-------------------|
| Google: create     | New Frappe contact (or linked to an existing one, see below)   | within ~5 minutes |
| Google: update     | Same Frappe contact updated, no duplicate                      | within ~5 minutes |
| Google: delete     | Frappe contact **kept**, unlinked, "Skip Google Sync" ticked   | within ~5 minutes |
| Frappe: create/update | Pushed to Google                                            | seconds (background job) |
| Frappe: delete     | Deleted in Google                                              | seconds (background job) |

Google has no push notifications for contacts, so Google → Frappe is polled every 5 minutes.

Synced fields: first, middle and last name, company, designation, emails, phone numbers
(primary first). Other Google fields (addresses, birthdays, notes…) are left untouched.
If both sides change the same contact within 5 minutes, the last write wins.

Installing the app adds a **Skip Google Sync** checkbox to Contact and hides Frappe's own
"Sync with Google Contacts" checkbox (this module replaces that push).

### Set up

On each **Google Contacts** account (already authorized): tick **Enable**,
**Pull from Google Contacts** and **Push to Google Contacts**, then save.
The **Sync Contacts** button starts a pull right away.

New Frappe contacts go to the account set in their "Google Contacts" field, or else to the
oldest enabled account with Push ticked.

### Before the first sync

- The first pull links each Google person to an existing Frappe contact with the same email,
  keeping the Frappe data and adding what only Google has. No duplicates for those.
- Clean up the duplicates Frappe's built-in "Sync Contacts" created (Contact list, filter
  **Pulled from Google Contacts = Yes**). The first pull links only one contact per email;
  leftover copies would be pushed to Google as new people the next time they are saved.
- Existing Frappe contacts that are not in Google are pushed the next time they are saved.

### Good to know

- Every saved contact is pushed, including ones Helpdesk and CRM create from emails.
  Tick **Skip Google Sync** on a contact to keep it out of Google.
- Failed syncs are listed in **Error Log**.
- Updating to this version clears the sync tokens (patch `reset_google_sync_tokens`), so the next
  pull is one full sync. Linked contacts missing from Google are unlinked then.
- Contacts blanked by the old delete bug can be restored from their Version history (only if
  Contact tracks changes on your site). Check first with a dry run, then run it with `dry_run: 0`:
  ```bash
  bench --site <site> execute office.google_contacts_sync.repair.restore_wiped_contacts --kwargs "{'dry_run': 1}"
  ```
  `no_history` lists blanked contacts it can't restore; restore those from a backup.
