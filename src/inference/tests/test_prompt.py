from inference.prompt import build_prompt


def test_builds_prompt_in_specified_order() -> None:
    prompt = build_prompt(
        "You are helpful.",
        [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ],
        "How are you?",
    )

    assert prompt == (
        "You are helpful.\n\n"
        "あなたは以下の会話履歴を参考にして、\n"
        "文脈を維持した回答をしてください。\n\n"
        "## 会話履歴\n\n"
        "[User]\nHello\n\n"
        "[Assistant]\nHi\n\n"
        "## ユーザーの入力\n\n"
        "How are you?"
    )


def test_omits_history_section_when_history_is_empty() -> None:
    prompt = build_prompt("System instructions", [], "Current input")

    assert "会話履歴" not in prompt
    assert prompt == (
        "System instructions\n\n"
        "## ユーザーの入力\n\n"
        "Current input"
    )


def test_preserves_order_of_multiple_history_turns() -> None:
    prompt = build_prompt(
        "System",
        [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
            {"role": "assistant", "content": "Second answer"},
        ],
        "Current question",
    )

    assert prompt.index("[User]\nFirst question") < prompt.index(
        "[Assistant]\nFirst answer"
    )
    assert prompt.index("[Assistant]\nFirst answer") < prompt.index(
        "[User]\nSecond question"
    )
    assert prompt.index("[Assistant]\nSecond answer") < prompt.index(
        "## ユーザーの入力"
    )


def test_keeps_current_input_out_of_history() -> None:
    prompt = build_prompt(
        "System",
        [{"role": "user", "content": "Previous question"}],
        "Current question",
    )

    assert prompt.count("Current question") == 1
    assert prompt.endswith("## ユーザーの入力\n\nCurrent question")
