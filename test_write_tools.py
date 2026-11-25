from agent.tools import update_crm_record, get_account_details

ACCOUNT_ID = "ACC-001"
ORIGINAL_WEBSITE = "capitalextrusi.in"
TEST_WEBSITE = "https://write-test.invalid"

print("\n1. Checking original account data...")
account = get_account_details(ACCOUNT_ID)

if not account.get("success"):
    print("FAILED:", account)
    raise SystemExit(1)

original = account["account"].get("website")
print("Original website:", original)

if original != ORIGINAL_WEBSITE:
    print("STOPPED: Website does not match the expected original value.")
    print("No changes made.")
    raise SystemExit(1)

print("\n2. Testing database update...")
result = update_crm_record(
    record_type="account",
    record_id=ACCOUNT_ID,
    field="website",
    value=TEST_WEBSITE
)
print(result)

if not result.get("success"):
    print("UPDATE FAILED. Original value should remain unchanged.")
    raise SystemExit(1)

try:
    print("\n3. Verifying temporary value...")
    check = get_account_details(ACCOUNT_ID)
    actual = check["account"].get("website")

    if actual != TEST_WEBSITE:
        raise RuntimeError("Temporary website verification failed.")

    print("SUCCESS: Temporary value verified:", actual)

finally:
    print("\n4. Restoring original website...")
    restore = update_crm_record(
        record_type="account",
        record_id=ACCOUNT_ID,
        field="website",
        value=ORIGINAL_WEBSITE
    )
    print(restore)

    final_check = get_account_details(ACCOUNT_ID)
    restored = final_check["account"].get("website")

    print("\n5. Final verification:")
    print("Website:", restored)

    if restored != ORIGINAL_WEBSITE:
        raise RuntimeError(
            "IMPORTANT: Original website was not restored. "
            "Check the database immediately."
        )

    print("\nALL TESTS PASSED. Original website restored.")
