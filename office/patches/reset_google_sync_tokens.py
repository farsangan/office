import frappe


def execute():
	# Pulls now request `metadata` too, and Google rejects a sync token from a request with other parameters.
	# Clearing the tokens makes the next pull a full sync.
	frappe.db.set_value(
		"Google Contacts",
		{"google_sync_token": ["is", "set"]},
		"google_sync_token",
		None,
		update_modified=False,
	)
