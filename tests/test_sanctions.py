from app.compliance.sanctions import screen_entity, screen_transaction


def test_clean_entity():
    result = screen_entity("Pranav Pujara")
    assert result["matched"] is False
    assert result["risk"] == "CLEAR"


def test_exact_sanctions_match():
    result = screen_entity("Dawood Ibrahim Kaskar")
    assert result["matched"] is True
    assert result["risk"] == "HIGH"
    assert result["score"] >= 85


def test_fuzzy_sanctions_match():
    # Variation in name — should still catch it
    result = screen_entity("Dawood Ibrahim")
    assert result["risk"] in ("HIGH", "MEDIUM")
    assert result["score"] >= 70


def test_known_entity_match():
    result = screen_entity("Lashkar e Taiba")
    assert result["matched"] is True
    assert result["risk"] == "HIGH"


def test_blank_entity():
    result = screen_entity("")
    assert result["matched"] is False
    assert result["risk"] == "CLEAR"


def test_screen_transaction_clean():
    result = screen_transaction("normal.user@okaxis", "merchant@ybl")
    assert result["flagged"] is False
    assert result["risk"] == "CLEAR"


def test_screen_transaction_flagged_sender():
    result = screen_transaction("Dawood Ibrahim Kaskar", "merchant@ybl")
    assert result["flagged"] is True
    assert result["risk"] == "HIGH"
