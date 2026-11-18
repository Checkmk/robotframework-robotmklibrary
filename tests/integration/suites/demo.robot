*** Settings ***
Documentation    Suite used by the listener tests.

*** Keywords ***
Greet
    [Arguments]    ${name}
    Log    Hello ${name}
    Log    <b>bold</b>    html=True

*** Test Cases ***
Passes
    Greet    world
    Log    careful    WARN

Fails
    Should Be Equal    500    200

Skips
    Skip    not today
