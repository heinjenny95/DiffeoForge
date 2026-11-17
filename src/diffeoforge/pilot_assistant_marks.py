"""Explain marking instructions before proposing a trial or opening a fit."""

import re

from diffeoforge.pilot_regions import SYMPTOMS

_SURFACE = r"hohlraum|hohlräum|öffnung|\bloch|\blöch|innenwand|cavit|opening|\bhole|surface|fläche"
_EXTRA = (r"zusätz|überzählig|\bextra\b|spurious|phantom|zu viel|erfunden|"
          r"im original(?:mesh)?[^.!?]{0,55}(?:nicht|\bkein)|"
          r"(?:absent|missing) from the original|(?:doesn.t|isn.t) exist in the original")
_BRIDGE = (r"überbrück|zugedeckt|überdeckt|verschlossen|zugesetzt|\bbrück|"
           r"bridg|\bsealed|filled in|covered over|(?:separat|isoliert|disconnected).{0,25}"
           r"(?:stück|stückchen|fläche|piece|surface|patch)")
_DEFORM = r"wölb|falt(?:et|e|en)|beul|bulg|fold|dents?\b|buckl"


def advice(question, german):
    def say(de, en):
        return de if german else en

    def label(symptom):
        return say(f"„{SYMPTOMS[symptom]}“", f"“{SYMPTOMS[symptom]}”")

    marked = re.search(r"markier|\bmark(?:ed|ing)\b|instruction for selected point", question)
    surface = re.search(_SURFACE, question)
    extra = re.search(_EXTRA, question)
    bridge = re.search(_BRIDGE, question)
    deform = re.search(_DEFORM, question)
    detail = SYMPTOMS["detail"].casefold() in question
    if (surface or marked) and (extra or bridge or deform):
        topology, distortion = label("topology"), label("distortion")
        if deform and not bridge:
            body = say(f"Wenn die Öffnung frei bleibt und sich dieselbe Wand nach innen wölbt "
                       f"oder faltet, wähle {distortion}.",
                       f"If the opening stays clear and the same wall bends or folds inward, "
                       f"choose {distortion}.")
        else:
            body = say(
                f"Überbrückt die zusätzliche Fläche eine Öffnung oder liegt sie als separates "
                f"Stück im Hohlraum? Dann wähle {topology}. Bleibt die Öffnung frei und wölbt "
                f"sich dieselbe Wand nach innen, wähle {distortion}.",
                f"If the extra surface bridges an opening or forms a separate piece, choose "
                f"{topology}. If the opening stays clear and the same wall bulges inward, "
                f"choose {distortion}.",
            )
        if detail:
            body += " " + _missing_detail(say, label("detail"))
        return body + say(
            " Wähle deinen markierten Punkt und ändere die Anweisung unter „Instruction for "
            "selected point“. Klicke auf „Save all marked areas“. Wenn der Fehler für die "
            "Form wichtig ist, speichere die Bewertung mit „Needs improvement“.",
            " Select your marked point, change ‘Instruction for selected point’, then click "
            "‘Save all marked areas’. If the defect matters to the shape, record the review "
            "with ‘Needs improvement’.",
        )
    if detail:
        return _missing_detail(say, label("detail")) + say(
            f" Für einen größeren Abschnitt der Originaloberfläche, den der Fit verfehlt, "
            f"gibt es {label('missing')}.",
            f" For a larger area of the original surface that the fit missed, use "
            f"{label('missing')}.",
        )
    return None


def _missing_detail(say, detail):
    return say(f"{detail} passt, wenn ein Detail im Original vorhanden ist und in der Reco fehlt.",
               f"{detail} applies when a detail exists in the original and is absent from the fit.")
