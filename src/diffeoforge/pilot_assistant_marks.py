"""Explain the real marking instructions before suggesting another fit."""

import re

from diffeoforge.pilot_regions import SYMPTOMS

_SURFACE = (r"hohlraum|hohlräum|öffnung|\bloch|\blöch|innenwand|cavit|recess|opening|\bhole|"
            r"surface|fläche")
_EXTRA = (r"zusätz|überzählig|\bextra\b|spurious|phantom|zu viel|erfunden|"
          r"im original(?:mesh)?[^.!?]{0,55}(?:nicht|\bkein)|"
          r"(?:absent|missing) from the original|(?:doesn.t|isn.t) exist in the original")
_BRIDGE = (r"überbrück|zugedeckt|überdeckt|verschlossen|zugesetzt|\bbrück|"
           r"spannt.{0,32}(?:fläche|haut).{0,14}(?:darüber|drüber)|"
           r"(?:grew|grown|has) a lid|bridg|\bsealed|filled in|covered over|"
           r"(?:separat|isoliert|disconnected).{0,25}"
           r"(?:stück|stückchen|fläche|piece|surface|patch)")
_DEFORM = r"wölb|falt(?:et|e|en)|beul|bulg|fold|dents?\b|buckl"


def advice(question):
    marked = re.search(r"markier|\bmark(?:ed|ing)\b|instruction for selected point", question)
    surface = re.search(_SURFACE, question)
    extra = re.search(_EXTRA, question)
    bridge = re.search(_BRIDGE, question)
    deform = re.search(_DEFORM, question)
    detail = SYMPTOMS["detail"].casefold() in question
    missing_detail = (f'“{SYMPTOMS["detail"]}” applies when a detail exists in the original '
                      'and is absent from the fit.')
    if (surface or marked) and (extra or bridge or deform):
        wall = ("If the opening stays clear and the same wall bends or folds inward, choose "
                f'“{SYMPTOMS["distortion"]}”.')
        opening = ("If the extra surface bridges an opening or forms a separate piece, choose "
                   f'“{SYMPTOMS["topology"]}”. ')
        body = wall if deform and not bridge else opening + wall
        if detail:
            body += " " + missing_detail
        return (body + " Select your marked point, change ‘Instruction for selected point’, "
                "then click ‘Save all marked areas’. If the defect matters to the shape, "
                "record the review with ‘Needs improvement’.")
    if detail:
        return (missing_detail + " For a larger area of the original surface that the fit missed, "
                f'use “{SYMPTOMS["missing"]}”.')
    return None
