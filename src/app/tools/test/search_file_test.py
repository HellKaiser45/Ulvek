import os
import shutil
from pathlib import Path
from typing import NamedTuple, List
import asyncio
from src.app.tools.search_files import search_files

THIS_FILE = Path(__file__).resolve()
TEST_DIR = THIS_FILE.parent  # → src/app/tools/test/
TEST_FILES_DIR = TEST_DIR / "test_files"

# Save original CWD (project root, probably)
ORIGINAL_CWD = Path.cwd()


class TestCase(NamedTuple):
    name: str
    query: str
    paths: List[str] | None
    expected_count: int
    literal: bool = False


def setup_test_files():
    """Create comprehensive test files with edge cases."""
    if TEST_FILES_DIR.exists():
        shutil.rmtree(TEST_FILES_DIR)
    TEST_FILES_DIR.mkdir()

    # Create directory structure
    (TEST_FILES_DIR / "src").mkdir(parents=True)
    (TEST_FILES_DIR / "src" / "utils").mkdir()
    (TEST_FILES_DIR / "src" / "Models").mkdir()
    (TEST_FILES_DIR / "tests").mkdir()
    (TEST_FILES_DIR / "docs").mkdir()
    (TEST_FILES_DIR / "config").mkdir()

    # Create files with various edge cases
    (TEST_FILES_DIR / "src" / "auth.py").write_text("""
def validate_user(email, password):
    return email.endswith("@test.com")

class AuthManager:
    def login(self, email, password):
        return validate_user(email, password)
""")

    (TEST_FILES_DIR / "tests" / "test_auth.py").write_text("""
def test_validate_user():
    assert validate_user("user@test.com", "pass")
    
def test_auth_manager():
    auth = AuthManager()
    assert auth.login("user@test.com", "pass")
""")

    (TEST_FILES_DIR / "src" / "utils" / "helpers.py").write_text("""
# This comment contains validate_user
def helper_function():
    return "helper"

# validate_user appears here too
""")

    (TEST_FILES_DIR / "src" / "Models" / "User.py").write_text("""
class User:
    def __init__(self, email):
        self.email = email

    def validate(self):
        # validate_user is called here
        return validate_user(self.email, "password")
""")

    (TEST_FILES_DIR / "src" / "config.ini").write_text("""
[auth]
user = validate_user
""")

    (TEST_FILES_DIR / "docs" / "README.md").write_text("""
# Project
This project uses validate_user function.
""")

    (TEST_FILES_DIR / "config" / "space file.txt").write_text(
        "This file has a space in the name and contains: validate_user"
    )

    # Hidden file (should be skipped by ripgrep)
    (TEST_FILES_DIR / ".hidden_file.py").write_text("""
def hidden_function():
    return "hidden"
""")

    # Binary-like file (but text content)
    (TEST_FILES_DIR / "binary.dat").write_text("validate_user\x00binary\x01data")

    # File with regex special characters
    (TEST_FILES_DIR / "src" / "regex_special.py").write_text("""
def validate_user$():
    return True
    
def validate_user_123():
    return False
""")


async def run_tests():
    """Run comprehensive search tests with assertions."""

    results = []

    try:
        setup_test_files()
        os.chdir(TEST_FILES_DIR)

        print(f"=== SEARCH TESTS (Working Dir: {Path.cwd()}) ===\n")

        test_cases = [
            # Positive tests
            TestCase(
                "1. Function definition in src/", "def validate_user", ["src/"], 3
            ),
            TestCase(
                "2. All 'validate_user' references",
                "validate_user",
                ["."],
                13,
            ),
            TestCase("3. In specific subdirectory", "validate_user", ["src/utils/"], 2),
            TestCase(
                "5. File with space in name",
                "validate_user",
                ["config/space file.txt"],
                1,
            ),
            TestCase(
                "6. Regex pattern (end of line)",
                "validate_user$",
                ["."],
                3,
                literal=False,
            ),
            TestCase(
                "7. Literal search with regex chars",
                "validate_user$",
                ["."],
                1,
                literal=True,
            ),
            TestCase(
                "8. Case insensitivity",
                "VALIDATE_USER",
                ["."],
                13,
                literal=False,
            ),
            TestCase(
                "9. Non-existent string",
                "non_existent_string",
                ["."],
                0,
            ),
            TestCase(
                "10. Outside working directory",
                "validate_user",
                ["../non_existent"],
                0,
            ),
            TestCase(
                "11. Hidden file",
                "hidden_function",
                ["."],
                1,
            ),
            TestCase(
                "12. Non-existent directory",
                "validate_user",
                ["non_existent_dir/"],
                0,
            ),
            TestCase(
                "13. Non-existent file",
                "validate_user",
                ["non_existent_file.py"],
                0,
            ),
            TestCase(
                "14. Binary file (skipped by ripgrep)",
                "validate_user",
                ["binary.dat"],
                0,
            ),
            TestCase(
                "15. File with wrong extension",
                "validate_user",
                ["docs/README.md"],
                1,
            ),
            TestCase(
                "16. Alternation with OR",
                "validate_user|helper_function|hidden_function",
                ["."],
                15,
                literal=False,
            ),
            TestCase(
                "17. Grouping with OR",
                "validate_(user|auth)",
                ["."],
                13,
                literal=False,
            ),
            TestCase(
                "18. Beginning-of-line anchor",
                "^def validate_user",
                ["src/auth.py", "src/regex_special.py"],
                3,
                literal=False,
            ),
            # Regex end-of-line anchor (with spaces before comment)
            TestCase(
                "19. End-of-line anchor with comment",
                "validate_user.*$",
                ["src/utils/helpers.py"],
                2,  # both comments in helpers.py
                literal=False,
            ),
            # Regex with optional parts
            TestCase(
                "20. Optional part",
                "validate_user_123?",
                ["src/regex_special.py"],
                1,
                literal=False,
            ),
        ]

        for case in test_cases:
            try:
                matches = await search_files(
                    case.query, case.paths, literal=case.literal
                )
                count = len(matches)
                expected = case.expected_count

                # Determine pass/fail
                passed = count == expected
                emoji = "✅" if passed else "❌"
                status = "PASSED" if passed else "FAILED"

                # Add to results
                results.append(
                    (emoji, f"{case.name}: Found {count}/{expected} matches", status)
                )

                # Print detailed failure info
                if not passed:
                    print(f"\n{emoji} {case.name} ({status})")
                    print(f"  Query: '{case.query}' | Paths: {case.paths}")
                    print(f"  Expected: {expected} | Found: {count}")
                    if matches:
                        print("  First match:")
                        print(
                            f"    {matches[0].file_path}:{matches[0].line_number} | {matches[0].line_content.strip()}"
                        )

            except Exception as e:
                results.append(("💥", f"{case.name}: Exception - {str(e)}", "CRASHED"))

        # Print summary
        print("\n=== RESULTS SUMMARY ===")
        for emoji, message, status in results:
            print(f"{emoji} {message}")

        # Final verdict
        passed = all(status == "PASSED" for _, _, status in results)
        print(f"\n{'🎉 ALL TESTS PASSED!' if passed else '🚨 TESTS FAILED!'}")

        if not passed:
            failed = sum(1 for _, _, status in results if status != "PASSED")
            print(f"  {failed} test(s) failed out of {len(results)}")

    finally:
        # Cleanup
        os.chdir(ORIGINAL_CWD)
        if TEST_FILES_DIR.exists():
            shutil.rmtree(TEST_FILES_DIR)


if __name__ == "__main__":
    asyncio.run(run_tests())
