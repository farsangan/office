app_name = "google_contacts_sync"
app_title = "Google Contacts Sync"
app_publisher = "Nexstone"
app_description = "Two-way sync between Frappe Contacts and Google Contacts"
app_email = "farsangan@gmail.com"
app_license = "MIT"

after_install = "google_contacts_sync.install.after_install"

doc_events = {
	"Contact": {
		"on_update": "google_contacts_sync.sync.on_contact_update",
		"after_delete": "google_contacts_sync.sync.on_contact_delete",
	}
}

scheduler_events = {
	"cron": {
		"*/5 * * * *": ["google_contacts_sync.sync.pull_all"],
	}
}

# The "Sync Contacts" button on Google Contacts now runs this app's sync.
override_whitelisted_methods = {
	"frappe.integrations.doctype.google_contacts.google_contacts.sync": "google_contacts_sync.sync.sync",
}
