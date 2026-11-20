"""Keep trial scope in the same A/B/C order as the owner's point editor."""


def label(index):
    return chr(65 + index) if index < 26 else str(index + 1)


def summary(plan):
    from diffeoforge.regional_fit import instruction_regions

    regions = instruction_regions(plan)
    active, fixed, shaped, waiting = [], [], [], []
    for index, region in enumerate(regions):
        name = label(index)
        purpose = region.get('purpose', 'problem')
        if purpose == 'fixed':
            fixed.append(name)
        elif purpose == 'preserve':
            shaped.append(name)
        elif region in plan.get('focus_regions', []):
            active.append(name)
        else:
            waiting.append(name)
    if not active and not shaped:
        return None
    parts = []
    if active:
        parts.append('improve '+', '.join(active))
    if fixed:
        parts.append('keep '+', '.join(fixed)+' in place')
    if shaped:
        parts.append('retain the shape of '+', '.join(shaped))
    text = 'This trial: '+'; '.join(parts)+'.'
    if waiting:
        text += ' Other improvement marks stay saved for a later step: '+', '.join(waiting)+'.'
    return dict(active=active, fixed=fixed, shape=shaped, waiting=waiting, text=text)
