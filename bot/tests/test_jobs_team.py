from __future__ import annotations

from jarvis.jobs.team import GH_LOGIN_TO_DISCORD, mention


def test_known_login_returns_discord_mention():
    assert "MeetDigrajkar" in GH_LOGIN_TO_DISCORD
    assert mention("MeetDigrajkar") == f"<@{GH_LOGIN_TO_DISCORD['MeetDigrajkar']}>"


def test_unknown_login_returns_code_login():
    assert mention("ghost-user") == "`ghost-user`"


def test_none_login_returns_unassigned():
    assert mention(None) == "_(unassigned)_"


def test_empty_login_returns_unassigned():
    assert mention("") == "_(unassigned)_"
