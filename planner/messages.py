"""Rule based coach messages (CLAUDE.md §8.6).

No randomness: the variant is picked from the week and the user id, so the same week shows the same message.
Tone: "sen" language, short sentences, no blame, no big promises.
"""

TIERS = (
    (90, [
        "Muhteşem bir hafta! Planının %{p}'ini yaptın. Bu tempoyla rotandasın. 🚀",
        "Harika bir hafta geçirdin: planının %{p}'ini tamamladın. Böyle devam! 🚀",
    ]),
    (70, [
        "Güzel bir hafta geçirdin, planının %{p}'ini yaptın. Küçük bir adım daha, tam yoldayız. 💪",
        "Planının %{p}'ini yaptın, bu çok iyi. Küçük bir adım daha ve tam yoldasın. 💪",
    ]),
    (50, [
        "Bu hafta biraz yoğundu galiba, planının %{p}'ini yapabildin. Sorun değil; kaçırdıklarını önümüzdeki günlere yaydım.",
        "Planının %{p}'ini yapabildin. Her hafta aynı olmuyor, sorun değil; kaçırdıkların önümüzdeki günlere yayıldı.",
    ]),
    (0, [
        "Zor bir hafta olmuş. Kendine yüklenme; her gün küçük bir adım bile çok şey değiştirir. Hadi bu hafta birlikte yeniden başlayalım. 🌱",
        "Bu hafta planın pek yürümedi, olur. Her gün küçük bir adım bile çok şey değiştirir; bu hafta yeniden başlıyoruz. 🌱",
    ]),
)


def pick(options, week_start, user_id):
    """Deterministic choice: the same user sees the same message for the same week."""
    return options[(week_start.toordinal() + user_id) % len(options)]


def weekly_message(percent, week_start, user_id, improved=None, focus=()):
    """Coach message for a finished week.

    percent:  share of the planned minutes that was done (0-100)
    improved: (topic name, change in percentage points) or None
    focus:    names of next week's focus subjects
    """
    for minimum, options in TIERS:
        if percent >= minimum:
            text = pick(options, week_start, user_id).replace("%{p}", f"%{percent}")
            break
    parts = [text]
    if improved:
        name, points = improved
        parts.append(f"{name} doğruluğun %{points} arttı 👏")
    if focus:
        parts.append("Gelecek hafta odak derslerin: " + ", ".join(focus) + ".")
    return " ".join(parts)
