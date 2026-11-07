def build_prompt(
    system_prompt: str,
    history: list[dict[str, str]],
    user_input: str,
) -> str:
    parts = [system_prompt]

    if history:
        messages = []
        for message in history:
            role = {"user": "User", "assistant": "Assistant"}[message["role"]]
            messages.append(f"[{role}]\n{message['content']}")

        parts.append(
            "あなたは以下の会話履歴を参考にして、\n"
            "文脈を維持した回答をしてください。\n\n"
            "## 会話履歴\n\n"
            + "\n\n".join(messages)
        )

    parts.append(f"## ユーザーの入力\n\n{user_input}")
    return "\n\n".join(parts)
