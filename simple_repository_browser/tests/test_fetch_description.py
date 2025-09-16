import pkginfo
import pytest

from ..fetch_description import _enhance_author_maintainer_info


@pytest.mark.parametrize(
    [
        "author",
        "author_email",
        "maintainer",
        "maintainer_email",
        "expected_author",
        "expected_maintainer",
    ],
    [
        # Test extracting author from email when no author
        (None, "John Doe <john@example.com>", None, None, "John Doe", None),
        # Test extracting maintainer from email when no maintainer
        (None, None, None, "Jane Smith <jane@example.com>", None, "Jane Smith"),
        # Test extracting both author and maintainer
        (
            None,
            "John Doe <john@example.com>",
            None,
            "Jane Smith <jane@example.com>",
            "John Doe",
            "Jane Smith",
        ),
        # Test preserving existing author name
        (
            "Existing Author",
            "John Doe <john@example.com>",
            None,
            None,
            "Existing Author",
            None,
        ),
        # Test preserving existing maintainer name
        (
            None,
            None,
            "Existing Maintainer",
            "Jane Smith <jane@example.com>",
            None,
            "Existing Maintainer",
        ),
        # Test handling empty author email
        (None, "", None, None, None, None),
        # Test handling None author email
        (None, None, None, None, None, None),
        # Test handling multiple emails
        (
            None,
            "John Doe <john@example.com>, Jane Smith <jane@example.com>",
            None,
            None,
            "John Doe, Jane Smith",
            None,
        ),
        # Test handling email without display name
        (None, "john@example.com", None, None, "", None),
        # Test handling mixed email formats
        (
            None,
            "John Doe <john@example.com>, jane@example.com",
            None,
            None,
            "John Doe, ",
            None,
        ),
        # Test handling empty string author (should be treated as missing)
        ("", "John Doe <john@example.com>", None, None, "John Doe", None),
        # Test handling empty string maintainer (should be treated as missing)
        (None, None, "", "Jane Smith <jane@example.com>", None, "Jane Smith"),
        # Test complex real-world scenario
        (
            "",
            "John Doe <john@example.com>, Support Team <support@example.com>",
            "",
            "Jane Smith <jane@example.com>",
            "John Doe, Support Team",
            "Jane Smith",
        ),
        # Test whitespace in emails
        (None, " John Doe <john@example.com> ", None, None, "John Doe", None),
        # Test no changes needed
        (
            "John Doe",
            "john@example.com",
            "Jane Smith",
            "jane@example.com",
            "John Doe",
            "Jane Smith",
        ),
    ],
)
def test_enhance_author_maintainer_info(
    author,
    author_email,
    maintainer,
    maintainer_email,
    expected_author,
    expected_maintainer,
):
    """Test _enhance_author_maintainer_info with various email and name combinations."""
    # Create a real pkginfo.Distribution instance
    info = pkginfo.Distribution()
    info.name = "test-package"
    info.author = author
    info.author_email = author_email
    info.maintainer = maintainer
    info.maintainer_email = maintainer_email

    _enhance_author_maintainer_info(info)

    assert info.author == expected_author
    assert info.maintainer == expected_maintainer
