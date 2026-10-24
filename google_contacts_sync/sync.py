"""Two-way sync between Frappe Contacts and Google Contacts (People API).

Google -> Frappe: `pull_all` runs every 5 minutes. Google has no push notifications
                  for contacts, so polling with a sync token is the only option.
Frappe -> Google: saving or deleting a Contact queues `push_contact` / `delete_in_google`.

A contact is linked to a Google person by `google_contacts_id` (the person's resourceName).
When a person is deleted in Google, the contact is kept and unlinked, never deleted.
"""

import frappe
from frappe import _
from frappe.integrations.doctype.google_contacts.google_contacts import get_google_contacts_object
from googleapiclient.errors import HttpError

from google_contacts_sync.mapping import NAME_FIELDS, from_contact, from_google, to_google

PERSON_FIELDS = "names,emailAddresses,phoneNumbers,organizations"


# Google -> Frappe


def pull_all():
	"""Scheduler entry point."""
	accounts = frappe.get_all("Google Contacts", {"enable": 1, "pull_from_google_contacts": 1}, pluck="name")
	for account in accounts:
		enqueue_pull(account)


@frappe.whitelist()
def sync(g_contact: str):
	"""Replaces the built-in "Sync Contacts" button, which only imports (and duplicates)."""
	frappe.has_permission("Google Contacts", "write", g_contact, throw=True)
	enqueue_pull(g_contact)
	return _("Sync started. Changes will appear in a minute.")


def enqueue_pull(account: str):
	# job_id + deduplicate: never run two pulls for the same account at once.
	frappe.enqueue(
		pull, queue="long", job_id=f"google_contacts_sync:pull:{account}", deduplicate=True, account=account
	)


def pull(account: str):
	service = get_google_contacts_object(account)[0]
	sync_token = frappe.db.get_value("Google Contacts", account, "google_sync_token")

	try:
		people, next_sync_token = _list_people(service, sync_token)
	except HttpError as e:
		if b"EXPIRED_SYNC_TOKEN" not in e.content:
			raise
		# Google expires sync tokens after 7 days. Start over with a full sync.
		sync_token = None
		people, next_sync_token = _list_people(service, None)

	for person in people:
		try:
			apply_person(account, person)
		except Exception:
			frappe.log_error(f"Google Contacts sync failed for {person.get('resourceName')}")

	if not sync_token and people:  # an empty answer is more likely a glitch than "everyone deleted"
		# A full sync lists only existing people: a linked contact missing from it was deleted in Google.
		seen = {person["resourceName"] for person in people}
		linked = frappe.get_all(
			"Contact",
			{"google_contacts": account, "google_contacts_id": ["is", "set"]},
			["name", "google_contacts_id"],
		)
		for contact in linked:
			if contact.google_contacts_id not in seen:
				unlink(contact.name)

	frappe.db.set_value(
		"Google Contacts", account, "google_sync_token", next_sync_token, update_modified=False
	)


def _list_people(service, sync_token: str | None) -> tuple[list[dict], str]:
	"""All people changed since `sync_token`, or everyone when there is no token."""
	people, page_token = [], None
	while True:
		response = (
			service.people()
			.connections()
			.list(
				resourceName="people/me",
				personFields=PERSON_FIELDS,
				pageSize=1000,
				requestSyncToken=True,
				syncToken=sync_token,
				pageToken=page_token,
			)
			.execute()
		)
		people += response.get("connections", [])
		page_token = response.get("nextPageToken")
		if not page_token:
			return people, response.get("nextSyncToken")


def apply_person(account: str, person: dict):
	resource_name = person["resourceName"]
	name = frappe.db.get_value("Contact", {"google_contacts_id": resource_name})

	if person.get("metadata", {}).get("deleted"):
		if name:
			unlink(name)
		return

	values = from_google(person)
	if not name and (existing := _find_unlinked_contact(values["emails"])):
		link_existing_contact(existing, account, resource_name, values)
		return

	if name:
		doc = frappe.get_doc("Contact", name)
	else:
		doc = frappe.new_doc("Contact", pulled_from_google_contacts=1)

	if doc.get("skip_google_sync") or from_contact(doc) == values:
		return

	# Google wins: overwrite the synced fields. The first email/phone is the primary one.
	doc.update({field: values[field] for field in NAME_FIELDS})
	emails = [{"email_id": email, "is_primary": i == 0} for i, email in enumerate(values["emails"])]
	# The primary number is also the primary mobile number, so `mobile_no` stays filled for CRM and Telephony.
	phones = [
		{"phone": phone, "is_primary_phone": i == 0, "is_primary_mobile_no": i == 0}
		for i, phone in enumerate(values["phones"])
	]
	doc.set("email_ids", emails)
	doc.set("phone_nos", phones)
	doc.google_contacts = account
	doc.google_contacts_id = resource_name
	doc.flags.from_google = True  # don't push this change back to Google
	doc.save(ignore_permissions=True)


def link_existing_contact(name: str, account: str, resource_name: str, values: dict):
	"""A Frappe contact that is not linked yet has the same email as a Google person (usually on the
	first sync). Keep the Frappe data, add what only Google has, and push the result back to Google."""
	doc = frappe.get_doc("Contact", name)
	for field in NAME_FIELDS:
		doc.set(field, doc.get(field) or values[field])
	emails = {row.email_id for row in doc.email_ids}
	phones = {row.phone for row in doc.phone_nos}
	for email in values["emails"]:
		if email not in emails:
			doc.append("email_ids", {"email_id": email})
	for phone in values["phones"]:
		if phone not in phones:
			doc.append("phone_nos", {"phone": phone})
	doc.google_contacts = account
	doc.google_contacts_id = resource_name
	doc.save(ignore_permissions=True)  # no `from_google` flag: the merged contact is pushed to Google


def _find_unlinked_contact(emails: list[str]) -> str | None:
	"""A contact with the same email that isn't linked to Google yet."""
	if not emails:
		return None
	found = frappe.get_all(
		"Contact",
		filters=[
			["Contact Email", "email_id", "in", emails],
			["Contact", "google_contacts_id", "is", "not set"],
			["Contact", "skip_google_sync", "=", 0],
		],
		pluck="name",
		limit=1,
	)
	return found[0] if found else None


def unlink(contact: str):
	"""The person was deleted in Google: keep the contact, stop syncing it."""
	frappe.db.set_value("Contact", contact, {"google_contacts_id": None, "skip_google_sync": 1})
	frappe.get_doc("Contact", contact).add_comment(
		"Comment", _("Deleted in Google Contacts. Google sync is stopped for this contact.")
	)


# Frappe -> Google


def on_contact_update(doc, method=None):
	"""Contact `on_update` hook (runs on insert too)."""
	if doc.flags.from_google or doc.get("skip_google_sync"):
		return
	if account := _push_account(doc):
		frappe.enqueue(
			push_contact, queue="short", enqueue_after_commit=True, contact=doc.name, account=account
		)


def on_contact_delete(doc, method=None):
	"""Contact `after_delete` hook."""
	if not doc.google_contacts_id or doc.get("skip_google_sync"):
		return
	if account := _push_account(doc):
		frappe.enqueue(
			delete_in_google,
			queue="short",
			enqueue_after_commit=True,
			account=account,
			resource_name=doc.google_contacts_id,
		)


def _push_account(doc) -> str | None:
	"""The contact's own account, or else the oldest enabled one with "Push to Google Contacts" ticked."""
	filters = {"enable": 1, "push_to_google_contacts": 1}
	if doc.google_contacts:
		filters["name"] = doc.google_contacts
	return frappe.db.get_value("Google Contacts", filters, "name", order_by="creation asc")


def push_contact(contact: str, account: str):
	if not frappe.db.exists("Contact", contact):
		return  # deleted in the meantime

	# Lock the row, so two quick saves can't both create the person in Google.
	doc = frappe.get_doc("Contact", contact, for_update=True)
	values = from_contact(doc)
	people = get_google_contacts_object(account)[0].people()

	if not doc.google_contacts_id:
		person = people.createContact(body=to_google(values)).execute()
		frappe.db.set_value(
			"Contact",
			contact,
			{"google_contacts": account, "google_contacts_id": person["resourceName"]},
			update_modified=False,
		)
		return

	person = people.get(resourceName=doc.google_contacts_id, personFields=PERSON_FIELDS).execute()
	if from_google(person) == values:
		return  # nothing Google cares about changed

	body = to_google(values, person)
	# Google identifies the contact (and rejects stale writes) by these.
	body["etag"] = person["etag"]
	body["metadata"] = person["metadata"]
	people.updateContact(
		resourceName=doc.google_contacts_id, updatePersonFields=PERSON_FIELDS, body=body
	).execute()


def delete_in_google(account: str, resource_name: str):
	people = get_google_contacts_object(account)[0].people()
	try:
		people.deleteContact(resourceName=resource_name).execute()
	except HttpError as e:
		if e.resp.status != 404:  # 404: already deleted in Google
			raise
