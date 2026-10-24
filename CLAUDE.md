# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`office` is a Frappe app (installed via bench / frappe_docker) that holds Farsangan's custom features, one Frappe module per feature. It follows the `bench new-app` layout: `office/` is the app package (`hooks.py`, `modules.txt`, `patches.txt`, `public/`), and each module is a folder under it with a `.frappe` marker, listed in `modules.txt`. A new feature means a new module folder plus a `modules.txt` line, with its hooks added to `hooks.py` (`after_install` is a list so each module can add its own setup).

The only module so far is **Google Contacts Sync** (`office/google_contacts_sync/`), a two-way sync between Frappe **Contact** and Google Contacts (People API). It reuses Frappe's built-in Google Contacts integration: the same OAuth setup and the same `Google Contacts` doctype accounts (`get_google_contacts_object(account)` returns the API client). It has no doctypes of its own. Its schema changes are custom fields and property setters created in its `install.py`.

## Commands

```bash
# Unit tests for mapping (no Frappe/database needed), run from the repo root
python -m unittest office.google_contacts_sync.test_mapping
python -m unittest office.google_contacts_sync.test_mapping.TestToGoogle.test_round_trip_is_stable

# Full suite (needs a bench site; test_sync.py is an IntegrationTestCase with Google mocked)
bench --site <test-site> set-config allow_tests true
bench --site <test-site> run-tests --app office
bench --site <test-site> run-tests --module office.google_contacts_sync.test_sync

# Lint / format (config in pyproject.toml: line length 110, tab indentation, py314)
ruff check . && ruff format .
```

`frappe` and `google-api-python-client` come from the bench environment and are not declared as dependencies.

## Google Contacts Sync architecture

- **`mapping.py`**: pure functions with no Frappe imports. Both sides are reduced to one "values" dict (`NAME_FIELDS` + `emails` + `phones`, primary first). `from_google` / `from_contact` produce it, and `to_google` builds the People API body, keeping existing Google entry types (home/work/mobile). The sync code compares values dicts to skip no-op writes in both directions.
- **`sync.py`**: both directions.
  - Google → Frappe is polled. `pull_all` (cron every 5 min) enqueues one `pull` per account on the `long` queue, deduplicated by `job_id`. `pull` uses a People API sync token stored in the hidden custom field `Google Contacts.google_sync_token`. On `EXPIRED_SYNC_TOKEN` it falls back to a full sync. Only a full sync detects deletions, by finding linked contacts that are missing from the result.
  - Frappe → Google is event-driven. The `on_update` / `after_delete` doc_events enqueue `push_contact` / `delete_in_google` on the `short` queue with `enqueue_after_commit=True`. `push_contact` locks the row (`for_update`) so it can't create the same person twice.
  - **Loop prevention**: saves from a pull set `doc.flags.from_google = True`, and `on_contact_update` ignores those saves. Writes that must not trigger a push (setting the Google id, unlinking) use `frappe.db.set_value` instead of `doc.save`.
  - The link key is `Contact.google_contacts_id` (the person's `resourceName`). A deletion in Google never deletes the Frappe contact. `unlink` clears the id, ticks `skip_google_sync` and adds a comment.
  - On the first pull, a Google person is matched to an existing unlinked contact by email (`_find_unlinked_contact` / `link_existing_contact`), so no duplicate is created.
  - Push target account: the contact's own `google_contacts`, or else the oldest enabled account with push ticked (`_push_account`).
- **`hooks.py`**: besides the doc_events and cron entry, it overrides Frappe's whitelisted `google_contacts.sync` (the "Sync Contacts" button) to run this module's pull instead.
- **`install.py`** (`after_install`): adds `Contact.skip_google_sync` and `Google Contacts.google_sync_token`, and hides and clears Frappe's own `sync_with_google_contacts` checkbox so contacts aren't pushed twice.

Synced fields are limited to names, company, designation, emails and phones (`PERSON_FIELDS`). Other Google fields must be left untouched on update.
