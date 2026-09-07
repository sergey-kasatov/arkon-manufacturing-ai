"""Count attempts inside the status retry loop, in the flow's own state.

One node, one job: every time the loop comes back here, the attempt number goes
up by one and is emitted as text so a Conditional Router can compare it.

**Read the counter from the thing that does the counting.** Both shipped course
canvases update their ``retry_count`` from the Condition Agent's output instead
of from the function that increments it, so the value written back is whatever
the router emitted and the counter never actually advances. The loop there is
bounded by the platform's iteration cap, not by the counter drawn on the canvas.
The state is written here, in the same call that computes it, and the router
downstream only reads it.

``_pre_run_setup`` resets the count, so a second run of the same flow starts at
attempt 1 rather than inheriting the previous run's total.

The node sits ON the retry path rather than beside it: the URL for the next
attempt passes through it. That is deliberate. A counter whose only output feeds
nothing is a counter the graph has no reason to build, and it would sit on the
canvas looking like it counts while never running.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput
from lfx.schema.message import Message
from lfx.template.field.base import Output


class ArkonRetryCounter(Component):
    display_name = "Retry Counter"
    description = "Increment the attempt counter in flow state and emit it as text."
    icon = "repeat"
    name = "ArkonRetryCounter"

    inputs = [
        MessageInput(
            name="trigger",
            display_name="Trigger",
            info="The failure branch's message, which carries the URL for the next attempt.",
        ),
    ]

    # group_outputs=True renders BOTH outputs as handles. Without it the UI draws only the
    # selected (first) output and, on its next save, deletes every edge that left the other one:
    # the deployed sub-flow lost three such edges when it was opened on 2026-09-07 at 16:03.
    outputs = [
        Output(display_name="Attempt", name="attempt", method="attempt_output", types=["Message"], group_outputs=True),
        Output(display_name="Passthrough", name="passthrough", method="passthrough_output", types=["Message"], group_outputs=True),
    ]

    def _pre_run_setup(self):
        self.update_ctx({"%s_attempts" % self._id: 0})

    def attempt_output(self) -> Message:
        key = "%s_attempts" % self._id
        attempts = int(self.ctx.get(key, 0)) + 1
        self.update_ctx({key: attempts})
        self.status = "attempt %d" % attempts
        return Message(text=str(attempts))

    def passthrough_output(self) -> Message:
        """Hand the trigger on unchanged, so the next attempt depends on this node."""
        value = self.trigger
        text = value.text if isinstance(value, Message) else (value or "")
        return Message(text=text or "")
