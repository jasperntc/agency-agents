"""c006 -- signed session token. Acceptance suite.

The stated checks hold the module to the contract the brief writes down, so
they require ValueError exactly as specified. The implied checks are about the
security property -- not accepted -- so any exception counts as a rejection
there. Refusing sloppily is still refusing.
"""
# Both are 45 characters. The first draft used the bare 28-character
# passphrase, and one condition refused it for being under a 32-byte minimum --
# a correct policy the fixture was punishing. OTHER differs from SECRET only in
# the final character, so `wrong secret` also exercises a near miss.
SECRET = "correct-horse-battery-staple-9f3a1c7e5b2d8406"
OTHER = "correct-horse-battery-staple-9f3a1c7e5b2d8407"
NOW = 1_700_000_000

CHECKS = [
    {"id": "s_round_trip_returns_the_subject", "kind": "stated",
     "what": "verify of a fresh token returns the subject it was issued for.",
     "why": "The brief defines verify as returning the subject."},
    {"id": "s_wrong_secret_raises", "kind": "stated",
     "what": "A token checked against a different secret raises ValueError.",
     "why": "The brief says verify raises ValueError when a token is not "
            "valid."},
    {"id": "s_tampered_token_raises", "kind": "stated",
     "what": "Changing a character in the token makes verify raise "
             "ValueError.",
     "why": "A signed token that accepts edits is not signed."},
    {"id": "s_expired_token_raises", "kind": "stated",
     "what": "A token checked after its ttl has elapsed raises ValueError.",
     "why": "The brief says tokens are short-lived and ttl is how long they "
            "stay valid."},

    {"id": "i_ttl_is_carried_by_the_token", "kind": "implied",
     "what": "A ttl=10 token is dead at now+60 while a ttl=100000 token "
             "issued at the same moment is still good.",
     "why": "A hardcoded lifetime satisfies every stated check as long as the "
            "default is used. The parameter is then decorative, and the "
            "10-second admin token quietly lasts fifteen minutes."},
    {"id": "i_secret_never_appears_in_the_token", "kind": "implied",
     "what": "The secret is not a substring of the issued token.",
     "why": "Tokens end up in logs, referrers and support tickets. Nothing "
            "in the brief says the token is public, and everything about "
            "what it is for means it is."},
    {"id": "i_no_prefix_of_a_token_verifies", "kind": "implied",
     "what": "Every truncation of a valid token is rejected.",
     "why": "Catches the two classic comparison bugs at once -- a signature "
            "checked with startswith or a prefix slice, and an empty "
            "signature treated as falsy and skipped."},
    {"id": "i_signature_covers_the_whole_token", "kind": "implied",
     "what": "No single-digit edit and no splice of two users' tokens ever "
             "verifies.",
     "why": "This is what a signature is FOR, and it is the one thing the "
            "brief cannot say without giving the answer. Signing only the "
            "subject leaves the expiry editable -- bump a digit and the "
            "session never ends. Signing only the expiry lets the subject be "
            "swapped for someone else's. Both round-trip perfectly and both "
            "survive a flipped trailing character."},
]


def _rejects(m, token, secret=SECRET, now=NOW, strict=False):
    """True when verify refuses. strict=True demands the documented ValueError."""
    try:
        m.verify(token, secret, now)
    except ValueError:
        return True
    except Exception:
        return not strict
    return False


def check_s_round_trip_returns_the_subject(m):
    token = m.issue("alice", SECRET, NOW)
    assert isinstance(token, str), f"issue returned {type(token).__name__}"
    assert m.verify(token, SECRET, NOW) == "alice"


def check_s_wrong_secret_raises(m):
    token = m.issue("alice", SECRET, NOW)
    assert _rejects(m, token, secret=OTHER, strict=True)


def check_s_tampered_token_raises(m):
    token = m.issue("alice", SECRET, NOW)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert _rejects(m, flipped, strict=True)


def check_s_expired_token_raises(m):
    token = m.issue("alice", SECRET, NOW, 60)
    assert _rejects(m, token, now=NOW + 61, strict=True)


def check_i_ttl_is_carried_by_the_token(m):
    # Both lifetimes are ordinary. An earlier draft used ttl=100000 for the
    # long one, which also punished any module enforcing a sane maximum
    # lifetime -- a defensible policy that has nothing to do with the property
    # under test. One check, one property.
    short = m.issue("alice", SECRET, NOW, 10)
    hour = m.issue("alice", SECRET, NOW, 3600)
    assert _rejects(m, short, now=NOW + 60), "ttl=10 token still valid a minute on"
    assert m.verify(hour, SECRET, NOW + 60) == "alice", "ttl=3600 token died early"


def check_i_secret_never_appears_in_the_token(m):
    token = m.issue("alice", SECRET, NOW)
    assert SECRET not in token, "the signing secret is embedded in the token"


def check_i_no_prefix_of_a_token_verifies(m):
    token = m.issue("alice", SECRET, NOW)
    for cut in range(len(token)):
        assert _rejects(m, token[:cut]), f"prefix of length {cut} verified"


def check_i_signature_covers_the_whole_token(m):
    alice = m.issue("alice", SECRET, NOW)
    bob = m.issue("robert", SECRET, NOW)

    # Digits are where the expiry lives in every hand-rolled format. If one can
    # be edited and the token still verifies, the lifetime is advisory.
    for i, char in enumerate(alice):
        if not char.isdigit():
            continue
        bumped = alice[:i] + str((int(char) + 1) % 10) + alice[i + 1:]
        assert _rejects(m, bumped), \
            f"editing the digit at {i} still verified: {bumped!r}"

    for cut in range(1, min(len(alice), len(bob))):
        spliced = alice[:cut] + bob[cut:]
        if spliced in (alice, bob):
            continue
        assert _rejects(m, spliced), f"splice at {cut} verified: {spliced!r}"
