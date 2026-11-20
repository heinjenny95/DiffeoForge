"""A PC shape plate with the observed scores on the same model score axis."""

from PIL import Image, ImageDraw


def shape_plate(pc, scores, coordinates, labels, frames, font, *, standard_deviation):
    """Draw all saved scores and mark the three actual model shape positions."""
    observed_min, observed_max = float(min(scores)), float(max(scores))
    left = min(observed_min, -2 * standard_deviation)
    right = max(observed_max, 2 * standard_deviation)
    width = right - left
    width = width if width else 1.0
    image = Image.new("RGB", (1260, 590), "white")
    draw = ImageDraw.Draw(image)
    ink, accent, warning = "#243c47", "#1a756b", "#a74619"
    draw.text((28, 12), f"PC{pc} · {labels[0]} / {labels[1]} / {labels[2]}",
              font=font, fill=ink)
    draw.text(
        (28, 47),
        f"Observed PC scores · {len(scores)} specimens · "
        f"{observed_min:.5g} to {observed_max:.5g}",
        font=font,
        fill=ink,
    )

    def x(score):
        return 52 + 1156 * (float(score) - left) / width

    draw.line((52, 108, 1208, 108), fill="#ccd9dd", width=2)
    draw.line((x(observed_min), 108, x(observed_max), 108), fill="#81b7af", width=2)
    for score in scores:
        center = x(score)
        draw.ellipse((center - 4, 104, center + 4, 112), fill=accent)
    for index, (score, label, frame) in enumerate(zip(coordinates, labels, frames, strict=True)):
        outside = score < observed_min or score > observed_max
        color = warning if outside else ink
        draw.line((x(score), 94, x(score), 124), fill=color, width=2)
        draw.text((210 + 420 * index, 156), f"{label} · score {score:.5g}",
                  font=font, fill=color, anchor="mt")
        if outside:
            draw.text((210 + 420 * index, 184), "Outside observed range",
                      font=font, fill=warning, anchor="mt")
        image.paste(frame, (420 * index, 216), frame)
    draw.text((28, 125), "Dots: observed specimens. Ticks: displayed model shapes.",
              font=font, fill=ink)
    return image
