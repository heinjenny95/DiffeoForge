"""Explain verified pilot state and refer to the actions already offered by the UI."""

import re

TOPICS = ("next", "keep", "controls", "iterations", "alignment", "review", "compare",
          "atlas", "other")
_WORDS = {
    "keep": (r"zurück|behalt|bewahr|retain|go back|keep|vorherig|früher|anknüpf|"
             r"\b(?:two|zwei|2)\b.{0,45}(?:stellen|areas)|\b(?:letzte|remaining)\b.{0,24}"
             r"(?:stelle|punkt|area|spot)"),
    "controls": r"\bcp\b|kontrollpunkt|control.point|dichter|denser",
    "iterations": r"iteration|konverg|converg|\+\s*300|toleran|solver.{0,16}block",
    "alignment": r"ausricht|align|template|vorlage|landmark|\bgpa\b|rotier|verdreht|rotat",
    "review": r"feedback|freigab|suitable|needs improvement|review|bewert|geeignet|prüf",
    "compare": r"vergleich|compare|unterschied|schlechter|worse|besser|better",
    "atlas": r"atlas|common|joint|gemeinsam",
    "next": (r"weiter|nächste|next|jetzt|\bklick|\bclick|fortsetz|continue|"
             r"was.{0,18}(?:tun|machen)|what.{0,14}(?:do|try)"),
}


def _topic(message):
    if re.search(r"\b(?:test|trial)\s*#?\s*\d+\b", message) and re.search(
            r"öffn|open|wähl|choose|work|arbeiten|verwenden|\buse\b", message):
        return "keep"
    return next((topic for topic, pattern in _WORDS.items() if re.search(pattern, message)), None)


def _language(message, history, default):
    for phrase in (message, *(question.lower() for question, _ in reversed(history))):
        if re.search(r"[äöüß]|\b(ich|was|wie|warum|kann|soll|der|die|das|und|noch|schon)\b",
                     phrase):
            return "de"
        if re.search(r"\b(i|what|how|why|can|should|the|and|which|only|both|open)\b", phrase):
            return "en"
    return default


def reply(context, message, history=()):
    """Interpret a question, then compose an answer from the current evidence only."""
    from diffeoforge.pilot_assistant_marks import advice
    from diffeoforge.pilot_assistant_model import classify

    question = message.casefold().strip()
    german = _language(question, history, context.get("assistant_language", "en")) == "de"
    if instructions := advice(question, german):
        return {"message": instructions, "actions": ()}
    facts = context["facts"]
    topic = _topic(question)
    short_follow_up = len(question.split()) < 6 and re.search(
        r"\b(und|and|that|dieser|warum|why|wieso)\b", question)
    if topic in {None, "next"} and short_follow_up:
        previous_topics = (_topic(prior.casefold()) for prior, _ in reversed(history))
        topic = next(filter(None, previous_topics), topic)
    model_topic = None
    if topic is None and not facts.get("running"):
        model_topic = classify(message, tuple(question for question, _ in history[-2:]))
        topic = model_topic or "other"

    def say(de, en):
        return de if german else en

    def answer(body, *actions):
        offered = context["assistant_actions"]
        actions = (facts.get("next_action") if action == "next" else action for action in actions)
        available = tuple(dict.fromkeys(a for a in actions if a in offered))
        result = {"message": body, "actions": available}
        if model_topic:
            result["status"] = say("Frage lokal interpretiert", "Question interpreted locally")
        return result

    next_label = facts.get("next_label")
    next_text = (say(f"Wähle jetzt „{next_label}“.", f"Choose “{next_label}” next.")
                 if next_label else "")
    source = facts.get("working_label")
    working_action = facts.get("working_action")
    if topic == "keep":
        named = re.search(r"\b(?:test|trial)\s*#?\s*(\d+)\b", question)
        if named:
            matches = facts["saved_tests"].get(int(named[1]), ())
            if len(matches) == 1:
                source, working_action = matches[0]
            else:
                return answer(say("Diesen Test kann ich hier nicht eindeutig als Ausgangsfit "
                                  "zuordnen. Öffne die Liste der gespeicherten Fits.",
                                  "I can’t identify a unique starting fit for that test here. "
                                  "Open the saved-fit list."), "history")
        rule = say(
            "Markiere die guten Stellen im Editor bei Bedarf erneut und setze sie auf "
            "„Retain this area in place“. "
            "Lass nur die offene Stelle auf „Improve“ und speichere den Ausgangsfit. "
            "Danach prüft der Pilot, ob er einen geschützten lokalen Test vorbereiten kann.",
            "Mark the good areas again if needed and set them to ‘Retain this area in place’. "
            "Keep the remaining area "
            "on ‘Improve’ and save the starting fit. The pilot then checks whether a "
            "protected local test can be prepared.",
        )
        warning = facts.get("working_quality_warning")
        if warning and working_action == facts.get("working_action"):
            rule += say(" Für diesen Fit liegen numerische Qualitätswarnungen vor. "
                        f"DF meldet „{warning}“.", f" {warning}")
        if source and working_action:
            return answer(say(f"Öffne {source} als Ausgangsfit. ",
                              f"Open {source} as the starting fit. ") + rule, working_action)
        return answer(say("Wähle den gespeicherten Fit, in dem die guten Stellen stimmen. ",
                          "Choose the saved fit that preserves the good areas. ") + rule,
                      "history", "review")

    if topic == "controls":
        counts = facts.get("density_counts")
        if facts.get("density_rejected"):
            prefix = say("Beide Kontrollpunkt-Fits sind als ungeeignet bewertet. ",
                         "Both control-point fits were marked unsuitable. ")
            if facts.get("density_worse"):
                prefix = say("Beide Kontrollpunkt-Fits wurden als schlechter gespeichert. ",
                             "Both control-point fits were recorded as worse. ")
            return answer(prefix + (next_text or say("Öffne den früheren Fit und prüfe die "
                "noch offenen Stellen.", "Open the earlier fit and check the remaining areas.")),
                "next", working_action, "history" if not working_action else None)
        prefix = (say(f"Dieser Vergleich testet {counts[0]} und {counts[1]} Kontrollpunkte. ",
                      f"This comparison tests {counts[0]} and {counts[1]} control points. ")
                  if counts else "")
        return answer(prefix + say("Mehr Kontrollpunkte erlauben feinere lokale Bewegungen. "
                                   "Die Wirkung zeigt der Vergleich am selben Ausgangsfit. ",
                                   "More control points allow finer local movements. Compare "
                                   "the results from the same starting fit to see their effect. ")
                      + next_text, "next")

    if topic == "iterations":
        reached = facts.get("iteration_limit")
        prefix = (say("Der gespeicherte Versuch hat das Iterationslimit erreicht. Die "
                      "numerische Konvergenz ist offen. ", "The saved fit reached its iteration "
                      "limit. Numerical convergence is unconfirmed. ") if reached else "")
        return answer(prefix + say("Mehr Iterationen sind sinnvoll, wenn dieselbe Einstellung "
                                   "an der noch offenen Stelle sichtbar Fortschritt macht. "
                                   "Prüfe zuerst die letzte Rekonstruktion und die markierten "
                                   "Bereiche. ", "More iterations can help when the same setup "
                                   "is still visibly improving the remaining area. Check the "
                                   "latest reconstruction and the marked areas first. ")
                      + next_text, "review", "next")

    if topic == "alignment":
        return answer(say("Vergleiche Originalmesh und Starttemplate in ihrer gespeicherten "
                          "Ausrichtung. Prüfe, ob die betroffene Struktur auf beiden Formen "
                          "an vergleichbarer Stelle liegt. Bei einer falschen Lage gehst du "
                          "zurück zu „Data & engine“.", "Compare the original mesh and starting "
                          "template in their saved alignment. Check where the affected "
                          "structures sit on both shapes. If the pose is wrong, return to "
                          "‘Data & engine’."), "inputs")

    if topic == "review":
        return answer(say("„Save feedback“ speichert, was sich gegenüber dem Ausgangsfit "
                          "verändert hat. Wenn ein wichtiges Detail noch fehlt, wähle „Needs "
                          "improvement“. „Suitable fit“ ist die Freigabe für diese Form. ",
                          "‘Save feedback’ records what changed relative to the starting fit. "
                          "If an important detail is missing, choose ‘Needs improvement’. "
                          "‘Suitable fit’ approves this form. ") + next_text, "review", "next")

    if topic == "atlas":
        progress = facts.get("coverage")
        count = (say(f"Gemeinsame Einstellungen geprüft für {progress[0]} von {progress[1]} "
                     "Pilotformen. ", f"Shared settings checked on {progress[0]} of {progress[1]} "
                     "pilot forms. ") if progress else "")
        return answer(count + say("Die Freigabe des Einzelfits gilt für diese Form. Danach "
                                  "prüft der Pilot die gemeinsamen Einstellungen, den Joint "
                                  "Fit und die Zeitauflösung. ", "Individual approval covers "
                                  "this form. The pilot then checks the shared settings, the "
                                  "joint fit and time resolution. ") + next_text, "next", "review")

    if topic == "compare":
        if model_topic and "compare" not in context["assistant_actions"]:
            return answer(say("Möchtest du zwei bestimmte Fits vergleichen, oder suchst du die "
                              "passende Anweisung für eine markierte Stelle?",
                              "Do you want to compare two specific fits, or choose the right "
                              "instruction for a marked area?"))
        return answer(say("Vergleiche die gespeicherten Fits am selben Ausschnitt. Prüfe die "
                          "offene Stelle und die Stellen, die schon gut waren.",
                          "Compare the saved fits in the same view. Check the remaining gap "
                          "and the areas that already looked good."), "compare",
                      working_action, "history" if not working_action else None)

    if facts.get("running"):
        return answer(say("Der Pilot rechnet gerade. Sobald das Ergebnis vorliegt, kannst du "
                          "die markierten Stellen im fit prüfen.", "The pilot is computing. "
                          "You can review the marked areas once the fit is ready."))
    if next_text and topic == "next":
        return answer(next_text, "next", "review")
    return answer(say("Welche Stelle oder Entscheidung meinst du? Ich kann den aktuellen Fit, "
                      "frühere Versuche, die Markierungen und die nächsten Pilotaktionen "
                      "erklären.", "Which area or decision do you mean? I can explain the "
                      "current fit, earlier attempts, the marked areas and the next pilot "
                      "actions."), "history")
