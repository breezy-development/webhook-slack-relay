from slack_relay.signature import sign, verify


def test_matches_githubs_documented_example():
    # Example from GitHub's "Validating webhook deliveries" docs.
    assert (
        sign("It's a Secret to Everybody", b"Hello, World!")
        == "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    )


def test_verify_accepts_valid_and_rejects_everything_else():
    body = b'{"zen": "Keep it logically awesome."}'
    good = sign("s3cret", body)
    assert verify("s3cret", body, good)
    assert not verify("other", body, good)
    assert not verify("s3cret", body + b" ", good)
    assert not verify("s3cret", body, None)
    assert not verify("s3cret", body, "")
    assert not verify("s3cret", body, good.replace("sha256=", "sha1="))
