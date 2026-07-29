from llm_chat.frontends.theme import Colors, application_style, conversation_list_style


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.03928
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_vermilion_theme_uses_warm_surfaces_and_red_primary_actions():
    background = tuple(
        int(Colors.BACKGROUND[index : index + 2], 16)
        for index in (1, 3, 5)
    )

    assert background[0] >= background[1] >= background[2]
    assert Colors.ACTION_BG == Colors.PRIMARY
    assert Colors.SIDEBAR_ACTIVE == Colors.PRIMARY_SOFT
    assert Colors.PRIMARY in application_style()
    assert Colors.PRIMARY_DARK in conversation_list_style()


def test_vermilion_theme_keeps_primary_text_and_actions_accessible():
    assert _contrast_ratio(Colors.TEXT_PRIMARY, Colors.BACKGROUND) >= 4.5
    assert _contrast_ratio(Colors.ACTION_TEXT, Colors.ACTION_BG) >= 4.5
