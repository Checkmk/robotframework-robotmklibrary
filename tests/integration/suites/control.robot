*** Settings ***
Documentation    Control structures, setup and teardown for the listener tests.
Suite Setup    Log    suite setup
Test Teardown    Log    test teardown

*** Test Cases ***
Control Structures
    FOR    ${i}    IN RANGE    1
        Log    loop
    END
    IF    True
        Log    if branch
    ELSE
        Log    else branch
    END
