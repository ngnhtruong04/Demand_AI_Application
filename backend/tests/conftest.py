import os

# Unit tests for endpoints that do not access RDS still need valid settings at
# application import time. If running integration tests, do not mock with invalid endpoints.
if os.environ.get("RUN_RDS_INTEGRATION_TESTS") != "1" and os.environ.get("RUN_RDS_CORE_INTEGRATION_TESTS") != "1":
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("RDS_ENDPOINT", "example.invalid")
    os.environ.setdefault("RDS_DATABASE", "test_database")
    os.environ.setdefault("RDS_MASTER_USERNAME", "test_master_user")
    os.environ.setdefault("RDS_MASTER_PASSWORD", "test_master_password")
    os.environ.setdefault("RDS_API_USERNAME", "test_api_user")
    os.environ.setdefault("RDS_API_PASSWORD", "test_api_password")
