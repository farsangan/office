"""Convert between Google People API persons and Frappe Contacts.

No Frappe imports here, so these functions are easy to read and test.
Both sides are reduced to the same "values" dict, with the primary email/phone first:

    {"first_name": "Ali", "middle_name": "", "last_name": "Saburi",
     "company_name": "Nexstone", "designation": "Sales",
     "emails": ["ali@example.com"], "phones": ["+49 151 000000"]}
"""

NAME_FIELDS = ("first_name", "middle_name", "last_name", "company_name", "designation")


def from_google(person: dict) -> dict:
	name = _first(person.get("names"))
	organization = _first(person.get("organizations"))
	values = {
		"first_name": name.get("givenName", ""),
		"middle_name": name.get("middleName", ""),
		"last_name": name.get("familyName", ""),
		"company_name": organization.get("name", ""),
		"designation": organization.get("title", ""),
		"emails": _google_values(person.get("emailAddresses")),
		"phones": _google_values(person.get("phoneNumbers")),
	}

	if not (values["first_name"] or values["middle_name"] or values["last_name"] or values["company_name"]):
		# Frappe names a contact after its name or company, so it needs one of them.
		values["first_name"] = name.get("displayName") or next(iter(values["emails"] + values["phones"]), "")

	return values


def from_contact(contact) -> dict:
	"""`contact` is a Contact document, or a dict shaped like one."""
	values = {field: contact.get(field) or "" for field in NAME_FIELDS}
	values["emails"] = _frappe_values(contact.get("email_ids"), "email_id", "is_primary")
	values["phones"] = _frappe_values(contact.get("phone_nos"), "phone", "is_primary_phone")
	return values


def to_google(values: dict, existing_person: dict | None = None) -> dict:
	"""Body for createContact / updateContact.

	`existing_person` is the current Google person; the type (home, work, mobile…)
	of emails and phones that still exist is kept.
	"""
	existing_person = existing_person or {}

	organizations = []
	if values["company_name"] or values["designation"]:
		organizations = [{"name": values["company_name"], "title": values["designation"]}]

	return {
		"names": [
			{
				"givenName": values["first_name"],
				"middleName": values["middle_name"],
				"familyName": values["last_name"],
			}
		],
		"organizations": organizations,
		"emailAddresses": _google_entries(values["emails"], existing_person.get("emailAddresses")),
		"phoneNumbers": _google_entries(values["phones"], existing_person.get("phoneNumbers")),
	}


def _first(items: list | None) -> dict:
	return (items or [{}])[0]


def _google_values(entries: list | None) -> list[str]:
	entries = sorted(entries or [], key=lambda entry: not entry.get("metadata", {}).get("primary"))
	return [entry["value"] for entry in entries if entry.get("value")]


def _frappe_values(rows: list | None, field: str, primary_flag: str) -> list[str]:
	rows = sorted(rows or [], key=lambda row: not row.get(primary_flag))
	return [row.get(field) for row in rows if row.get(field)]


def _google_entries(values: list[str], existing_entries: list | None) -> list[dict]:
	types = {entry.get("value"): entry.get("type") for entry in existing_entries or []}
	entries = []
	for index, value in enumerate(values):
		entry = {"value": value}
		if types.get(value):
			entry["type"] = types[value]
		if index == 0:
			entry["metadata"] = {"sourcePrimary": True}
		entries.append(entry)
	return entries
