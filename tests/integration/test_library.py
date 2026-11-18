"""The library as Robot Framework itself loads it."""

from robot.libdoc import LibraryDocumentation


def test_the_library_lists_the_runtime_keyword() -> None:
    assert [
        keyword.name for keyword in LibraryDocumentation("RobotmkLibrary").keywords
    ] == ["Monitor Subsequent Keyword Runtime"]
