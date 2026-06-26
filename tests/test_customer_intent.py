from vacancy_monitor.customer_intent import CustomerIntent, classify_customer_messages


def test_classify_customer_messages_detects_revision_request():
    result = classify_customer_messages(["Не работает кнопка оплаты, исправьте пожалуйста."])

    assert result.intent == CustomerIntent.REVISION_REQUEST
    assert "правки" in result.reason_ru


def test_classify_customer_messages_detects_payment_signal():
    result = classify_customer_messages(["Оплатил по СБП, проверьте поступление."])

    assert result.intent == CustomerIntent.PAYMENT_SIGNAL
    assert result.requires_payment_confirmation is True


def test_classify_customer_messages_detects_acceptance():
    result = classify_customer_messages(["Все отлично, работу принимаю."])

    assert result.intent == CustomerIntent.ACCEPTANCE


def test_classify_customer_messages_detects_dangerous_request():
    result = classify_customer_messages(["Нужно обойти лимиты и сделать массовую рассылку по аккаунтам."])

    assert result.intent == CustomerIntent.RISKY_REQUEST
    assert result.should_auto_reply is False
