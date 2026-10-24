import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def after_install():
	create_custom_fields(
		{
			"Contact": [
				{
					"fieldname": "skip_google_sync",
					"label": "Skip Google Sync",
					"fieldtype": "Check",
					"insert_after": "google_contacts_id",
					"description": "Ticked automatically when the person is deleted in Google.",
				}
			],
			"Google Contacts": [
				{
					"fieldname": "google_sync_token",
					"label": "Sync Token",
					"fieldtype": "Small Text",
					"insert_after": "push_to_google_contacts",
					"hidden": 1,
					"read_only": 1,
				}
			],
		}
	)

	# Frappe's built-in push runs for contacts with "Sync with Google Contacts" ticked.
	# This app replaces it, so hide and clear that checkbox to avoid pushing twice.
	make_property_setter("Contact", "sync_with_google_contacts", "hidden", 1, "Check")
	frappe.db.set_value(
		"Contact", {"sync_with_google_contacts": 1}, "sync_with_google_contacts", 0, update_modified=False
	)

	# Always show the "Google Contacts" section (account, Google id, Skip Google Sync).
	make_property_setter("Contact", "sb_00", "depends_on", "", "Data")
