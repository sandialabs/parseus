"""
Defines some global variables for the test scripts
"""

from os import environ

from parseus.datastore.client import DataStore

DATASTORE_HOST_URL = environ.get("DATASTORE_HOST_URL", "http://localhost:9200")
DATASTORE_TYPE = environ.get("DATASTORE_TYPE", "elasticsearch")
DATASTORE_AUTH_EXISTS = environ.get("DATASTORE_AUTH_EXISTS", "").lower() in {
    "1",
    "true",
    "yes",
}
DATASTORE_USERNAME = environ.get("DATASTORE_USERNAME", "test-user")
DATASTORE_PASSWORD = environ.get("DATASTORE_PASSWORD", "test-password")

TEST_AUTH = (DATASTORE_USERNAME, DATASTORE_PASSWORD)

if DATASTORE_AUTH_EXISTS:
    DATASTORE = DataStore(DATASTORE_HOST_URL, basic_auth=TEST_AUTH, base=DATASTORE_TYPE)
else:
    DATASTORE = DataStore(DATASTORE_HOST_URL, base=DATASTORE_TYPE)
