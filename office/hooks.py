app_name = "office"
app_title = "Office"
app_publisher = "Farsangan"
app_description = "Farsangan's custom features for Frappe"
app_email = "farsangan@gmail.com"
app_license = "MIT"

# Each module (see modules.txt) adds its own entries below.

after_install = [
	"office.google_contacts_sync.install.after_install",
]

doc_events = {
	"Contact": {
		"on_update": "office.google_contacts_sync.sync.on_contact_update",
		"after_delete": "office.google_contacts_sync.sync.on_contact_delete",
	}
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": ["office.google_contacts_sync.sync.pull_all"],
	}
}

override_whitelisted_methods = {
	# The "Sync Contacts" button on Google Contacts now runs this app's sync.
	"frappe.integrations.doctype.google_contacts.google_contacts.sync": (
		"office.google_contacts_sync.sync.sync"
	),
}
