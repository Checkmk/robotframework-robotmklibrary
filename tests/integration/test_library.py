"""The library as Robot Framework itself loads it."""

from robot.libdoc import LibraryDocumentation


def test_the_library_lists_the_runtime_keyword() -> None:
    """Library RobotmkLibrary exposes exactly the keyword monitoring keyword.

    libdoc loads the package as Robot Framework does. Outcome: the keyword list
    is Monitor Subsequent Keyword Runtime only.
    """
    assert [
        keyword.name for keyword in LibraryDocumentation("RobotmkLibrary").keywords
    ] == ["Monitor Subsequent Keyword Runtime"]
