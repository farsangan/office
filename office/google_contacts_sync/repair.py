"""Repair contacts blanked by an earlier bug: a person deleted in Google was read as an empty person
and its contact overwritten with empty values."""

import frappe
from frappe.integrations.doctype.google_contacts.google_contacts import get_google_contacts_object
from frappe.utils import cint
from googleapiclient.errors import HttpError

from office.google_contacts_sync.mapping import NAME_FIELDS, from_contact
from office.google_contacts_sync.sync import unlink

ROW_FIELDS = {
	"email_ids": ("email_id", "is_primary"),
	"phone_nos": ("phone", "is_primary_phone", "is_primary_mobile_no"),
}


@frappe.whitelist()
def restore_wiped_contacts(dry_run: bool = True):
	"""Restore blanked contacts from their Version history, without pushing to Google."""
	frappe.only_for("System Manager")
	dry_run = cint(dry_run)
	restored, unlinked, no_history = [], [], []

	for name in frappe.get_all("Contact", {"google_contacts": ["is", "set"]}, pluck="name"):
		doc = frappe.get_doc("Contact", name)
		if any(from_contact(doc).values()):
			continue  # not blanked
		lost = _lost_values(name)
		if not lost:
			no_history.append(name)
			continue

		restored.append(name)
		gone = doc.google_contacts_id and not _exists_in_google(doc)
		if gone:
			unlinked.append(name)
		if dry_run:
			continue

		fields, rows = lost
		doc.update(fields)
		for table, row in rows:
			doc.append(table, {field: row.get(field) for field in ROW_FIELDS[table]})
		doc.flags.from_google = True  # a restore, not a change to push
		doc.save(ignore_permissions=True)
		if gone:
			unlink(name)

	return {
		"dry_run": bool(dry_run),
		"restored": restored,
		"unlinked": unlinked,
		"no_history": no_history,
		"contact_tracks_changes": bool(frappe.get_meta("Contact").track_changes),
	}


def _lost_values(contact: str) -> tuple[dict, list] | None:
	"""Synced fields and rows the latest blanking save removed, read from the contact's Version history."""
	for data in frappe.get_all(
		"Version", {"ref_doctype": "Contact", "docname": contact}, pluck="data", order_by="creation desc"
	):
		data = frappe.parse_json(data or "{}")
		fields = {
			change[0]: change[1]
			for change in data.get("changed", [])
			if change[0] in NAME_FIELDS and change[1] and not change[2]
		}
		rows = [(table, row) for table, row in data.get("removed", []) if table in ROW_FIELDS]
		if fields or rows:
			return fields, rows
	return None


def _exists_in_google(doc) -> bool:
	people = get_google_contacts_object(doc.google_contacts)[0].people()
	try:
		people.get(resourceName=doc.google_contacts_id, personFields="metadata").execute()
	except HttpError as e:
		if e.resp.status == 404:
			return False
		raise
	return True
