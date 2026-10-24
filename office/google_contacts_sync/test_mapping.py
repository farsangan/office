"""Plain unit tests, no database needed.

Run with bench:  bench --site <site> run-tests --module office.google_contacts_sync.test_mapping
or directly:     python -m unittest office.google_contacts_sync.test_mapping
"""

import unittest

from office.google_contacts_sync.mapping import from_contact, from_google, to_google

PERSON = {
	"resourceName": "people/c1",
	"etag": "etag-1",
	"names": [{"givenName": "Ali", "familyName": "Amini", "displayName": "Ali Amini"}],
	"organizations": [{"name": "Farsangan", "title": "Sales"}],
	"emailAddresses": [
		{"value": "ali@home.example", "type": "home"},
		{"value": "ali@farsangan.example", "type": "work", "metadata": {"primary": True}},
	],
	"phoneNumbers": [{"value": "+49 151 000000", "type": "mobile", "metadata": {"primary": True}}],
}

VALUES = {
	"first_name": "Ali",
	"middle_name": "",
	"last_name": "Amini",
	"company_name": "Farsangan",
	"designation": "Sales",
	"emails": ["ali@farsangan.example", "ali@home.example"],
	"phones": ["+49 151 000000"],
}


class TestFromGoogle(unittest.TestCase):
	def test_maps_fields_with_primary_first(self):
		self.assertEqual(from_google(PERSON), VALUES)

	def test_person_without_name_or_company_falls_back_to_email(self):
		values = from_google({"emailAddresses": [{"value": "x@example.com"}]})
		self.assertEqual(values["first_name"], "x@example.com")

	def test_person_without_synced_fields_maps_to_empty_values(self):
		# e.g. a deleted person: sync guards on this so it never blanks a contact
		values = from_google({"resourceName": "people/c1", "metadata": {"deleted": True}})
		self.assertFalse(any(values.values()))

	def test_company_only_person_keeps_empty_first_name(self):
		values = from_google({"organizations": [{"name": "Farsangan"}]})
		self.assertEqual(values["first_name"], "")


class TestFromContact(unittest.TestCase):
	def test_matches_the_google_shape(self):
		contact = {
			"first_name": "Ali",
			"last_name": "Amini",
			"company_name": "Farsangan",
			"designation": "Sales",
			"email_ids": [
				{"email_id": "ali@home.example", "is_primary": 0},
				{"email_id": "ali@farsangan.example", "is_primary": 1},
			],
			"phone_nos": [{"phone": "+49 151 000000", "is_primary_phone": 1}],
		}
		self.assertEqual(from_contact(contact), VALUES)


class TestToGoogle(unittest.TestCase):
	def test_keeps_types_and_marks_primary(self):
		body = to_google(VALUES, PERSON)
		self.assertEqual(
			body["emailAddresses"],
			[
				{"value": "ali@farsangan.example", "type": "work", "metadata": {"sourcePrimary": True}},
				{"value": "ali@home.example", "type": "home"},
			],
		)
		self.assertEqual(body["organizations"], [{"name": "Farsangan", "title": "Sales"}])

	def test_round_trip_is_stable(self):
		# What we send to Google must read back as the same values, or the sync would never settle.
		body = to_google(VALUES)
		for field in ("emailAddresses", "phoneNumbers"):
			for entry in body[field]:
				entry["metadata"] = {"primary": entry.get("metadata", {}).get("sourcePrimary", False)}
		self.assertEqual(from_google(body), VALUES)

	def test_no_company_clears_organizations(self):
		self.assertEqual(to_google({**VALUES, "company_name": "", "designation": ""})["organizations"], [])
