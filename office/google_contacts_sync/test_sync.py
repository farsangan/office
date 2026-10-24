"""Integration tests against a real site, with Google replaced by a mock.

Run on a test site:  bench --site <test-site> run-tests --app office
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase
from googleapiclient.errors import HttpError

from office.google_contacts_sync import sync

ACCOUNT_EMAIL = "gcs-test@example.com"
EMAIL = "ali.gcs-test@example.com"
RESOURCE = "people/gcs-test-1"


def person(resource_name=RESOURCE, given="Ali", email=EMAIL):
	return {
		"resourceName": resource_name,
		"etag": "etag-1",
		"metadata": {"sources": [{"type": "CONTACT", "id": "1", "etag": "etag-1"}]},
		"names": [{"givenName": given}],
		"emailAddresses": [{"value": email, "metadata": {"primary": True}}],
	}


class TestGoogleContactsSync(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(frappe.db.rollback)
		frappe.db.set_single_value("Google Settings", "enable", 1)
		account = frappe.get_doc(
			{
				"doctype": "Google Contacts",
				"email_id": ACCOUNT_EMAIL,
				"enable": 1,
				"pull_from_google_contacts": 1,
				"push_to_google_contacts": 1,
			}
		)
		self.account = account.insert().name

		self.service = MagicMock()
		self.people = self.service.people.return_value
		patch(
			"office.google_contacts_sync.sync.get_google_contacts_object",
			return_value=(self.service, None),
		).start()
		self.enqueue = patch("frappe.enqueue").start()
		self.addCleanup(patch.stopall)

	# helpers

	def google_returns(self, *responses):
		self.people.connections.return_value.list.return_value.execute.side_effect = responses

	def pull(self, *people):
		self.google_returns({"connections": list(people), "nextSyncToken": "next-token"})
		sync.pull(self.account)

	def contact(self, resource_name=RESOURCE):
		return frappe.get_doc("Contact", {"google_contacts_id": resource_name})

	def make_contact(self, **fields):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Ali",
				"email_ids": [{"email_id": EMAIL, "is_primary": 1}],
				"google_contacts": self.account,
				**fields,
			}
		).insert()

	def queued(self, method):
		"""Keyword arguments of every frappe.enqueue call for `method`."""
		return [c.kwargs for c in self.enqueue.call_args_list if c.args and c.args[0] is method]

	# Google -> Frappe

	def test_scheduler_queues_a_pull_per_account(self):
		sync.pull_all()
		self.assertIn(self.account, [kwargs["account"] for kwargs in self.queued(sync.pull)])

	def test_pull_creates_a_linked_contact(self):
		self.pull(person())

		contact = self.contact()
		self.assertEqual(contact.first_name, "Ali")
		self.assertEqual(contact.email_id, EMAIL)
		self.assertEqual(contact.google_contacts, self.account)

	def test_pull_updates_instead_of_duplicating(self):
		self.pull(person())
		self.pull(person(given="Reza"))

		self.assertEqual(frappe.db.count("Contact", {"google_contacts_id": RESOURCE}), 1)
		self.assertEqual(self.contact().first_name, "Reza")
		list_call = self.people.connections.return_value.list.call_args
		self.assertEqual(list_call.kwargs["syncToken"], "next-token")

	def test_pulled_changes_are_not_pushed_back(self):
		self.pull(person())
		self.assertEqual(self.queued(sync.push_contact), [])

	def test_unchanged_person_is_not_saved_again(self):
		self.pull(person())
		modified = self.contact().modified
		self.pull(person())
		self.assertEqual(self.contact().modified, modified)

	def test_deleted_person_unlinks_the_contact(self):
		self.pull(person())
		name = self.contact().name

		self.pull({"resourceName": RESOURCE, "metadata": {"deleted": True}})

		contact = frappe.get_doc("Contact", name)
		self.assertFalse(contact.google_contacts_id)
		self.assertTrue(contact.skip_google_sync)

	def test_existing_contact_with_same_email_is_merged_not_duplicated(self):
		existing = self.make_contact(company_name="Farsangan")
		self.enqueue.reset_mock()
		google_person = {**person(), "phoneNumbers": [{"value": "+49 151 000000"}]}

		self.pull(google_person)

		contact = self.contact()
		self.assertEqual(contact.name, existing.name)
		self.assertEqual(contact.company_name, "Farsangan")  # Frappe data kept
		self.assertEqual(contact.phone_nos[0].phone, "+49 151 000000")  # Google data added
		self.assertEqual(
			self.queued(sync.push_contact)[0]["contact"], existing.name
		)  # merged result goes back

	def test_expired_sync_token_falls_back_to_a_full_sync(self):
		self.pull(person(), person("people/gcs-test-2", email="reza.gcs-test@example.com"))
		gone = self.contact("people/gcs-test-2").name

		expired = HttpError(
			MagicMock(status=400, reason="Bad Request"),
			b'{"error": {"code": 400, "message": "Sync token is expired.",'
			b' "details": [{"reason": "EXPIRED_SYNC_TOKEN"}]}}',
		)
		self.google_returns(expired, {"connections": [person()], "nextSyncToken": "new-token"})
		sync.pull(self.account)

		# gcs-test-2 is missing from the full list, so it was deleted in Google
		self.assertTrue(frappe.db.get_value("Contact", gone, "skip_google_sync"))
		self.assertEqual(
			frappe.db.get_value("Google Contacts", self.account, "google_sync_token"), "new-token"
		)

	# Frappe -> Google

	def test_saving_a_contact_queues_a_push(self):
		contact = self.make_contact()
		self.assertEqual(self.queued(sync.push_contact)[0]["contact"], contact.name)

	def test_skipped_contact_is_not_pushed(self):
		self.make_contact(skip_google_sync=1)
		self.assertEqual(self.queued(sync.push_contact), [])

	def test_push_creates_the_person_and_stores_its_id(self):
		contact = self.make_contact()
		self.people.createContact.return_value.execute.return_value = {"resourceName": "people/gcs-test-9"}

		sync.push_contact(contact.name, self.account)

		body = self.people.createContact.call_args.kwargs["body"]
		self.assertEqual(body["emailAddresses"][0]["value"], EMAIL)
		self.assertEqual(
			frappe.db.get_value("Contact", contact.name, "google_contacts_id"), "people/gcs-test-9"
		)

	def test_push_updates_the_linked_person(self):
		self.pull(person())
		contact = self.contact()
		contact.first_name = "Reza"
		contact.save()
		self.people.get.return_value.execute.return_value = person()

		sync.push_contact(contact.name, self.account)

		kwargs = self.people.updateContact.call_args.kwargs
		self.assertEqual(kwargs["resourceName"], RESOURCE)
		self.assertEqual(kwargs["body"]["etag"], "etag-1")
		self.assertEqual(kwargs["body"]["metadata"], person()["metadata"])
		self.assertEqual(kwargs["body"]["names"][0]["givenName"], "Reza")

	def test_push_skips_when_google_already_matches(self):
		self.pull(person())
		self.people.get.return_value.execute.return_value = person()

		sync.push_contact(self.contact().name, self.account)

		self.people.updateContact.assert_not_called()

	def test_deleting_a_linked_contact_queues_delete_in_google(self):
		self.pull(person())
		frappe.delete_doc("Contact", self.contact().name)
		self.assertEqual(self.queued(sync.delete_in_google)[0]["resource_name"], RESOURCE)
