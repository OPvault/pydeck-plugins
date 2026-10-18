"""Showcase — deliberately handler-free.

There is no ``on_press``, ``on_release`` or ``on_poll`` here, and that is the
whole point of the plugin: a showcase button is decoration, so pressing it must
do nothing at all. Without a poll handler the core never dispatches an event
for these buttons either, so they cost nothing between renders.

The face is built entirely from the button's own display in
``src/functions/showcase/template.xml`` — ``{_button_image}``,
``{_button_gradient}`` and ``<buttonlabel>`` — which is also what keeps two
showcase buttons independent. See ``src/shared.css`` for why.
"""

from __future__ import annotations
