"""The editor's preview places insets with the renderer's own numbers, and insets are drawn
above cutaways whatever their start times."""

from app.services.visuals.compositor import drawing_order
from tests.media_fixtures import requires_ffmpeg
from tests.test_clip_edit_api import sign_up
from tests.test_visual_render import RED, YELLOW, close, layer, pixel, render, solid_image


def test_the_layout_is_published_to_signed_in_users(client):
    assert client.get("/visual-layout").status_code == 401
    sign_up(client)
    layout = client.get("/visual-layout").json()
    assert layout["output"] == {"width": 1080, "height": 1920}
    assert layout["margins"] == {"top": 192, "bottom": 422, "left": 97, "right": 97}
    assert layout["inset_width_fraction"] == {
        "small": 0.34,
        "medium": 0.44,
        "large": 0.56,
        "full": 1.0,
    }
    assert layout["inset_max_aspect"] == 1.25 and layout["pip_border"] == 6
    assert layout["background"] == "#111113"


def test_cutaways_are_drawn_first_then_insets(tmp_path):
    pip = layer(tmp_path / "p.png", mode="pip", start_seconds=0.5, end_seconds=2.5)
    cut = layer(tmp_path / "c.png", start_seconds=1.0, end_seconds=2.0)
    late_pip = layer(tmp_path / "q.png", mode="overlay", start_seconds=2.6, end_seconds=3.2)
    assert drawing_order([pip, late_pip, cut]) == [cut, pip, late_pip]


@requires_ffmpeg
def test_an_inset_stays_visible_over_a_later_cutaway(tmp_path):
    out = render(tmp_path, [
        layer(solid_image(tmp_path / "y.png", size=(300, 300), colour=YELLOW), mode="pip",
              size=(300, 300), position="bottom_left", start_seconds=0.5, end_seconds=2.5),
        layer(solid_image(tmp_path / "red.png"), start_seconds=1.0, end_seconds=2.0),
    ])  # fmt: skip
    assert close(pixel(out, 341, 1254, t=1.5), YELLOW)  # the PiP, on top of the cutaway
    assert close(pixel(out, 540, 400, t=1.5), RED)
