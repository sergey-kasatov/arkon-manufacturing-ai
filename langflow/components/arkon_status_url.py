"""One node owns the incident status URL, and all three attempts read it from here.

The retry is unrolled into three request nodes, because a graph cycle does not
execute on this Langflow build. Three request nodes means three places to change
the endpoint, and the third one always gets forgotten. This node holds the URL
once and feeds every consumer, so the canvas has a single answer to "where does
this flow call".

It also gives the request chain a root that sits downstream of the Chat Input, and
it is the flow's ONLY consumer of that input, which is not a stylistic choice:
`sort_chat_inputs_first` places a chat input that feeds two branches into two
layers and then refuses the graph with "Only one chat input is allowed in the
graph". So the operator's request enters here and leaves again unchanged on the
Request output, and everything else reads it from there.
"""

from lfx.custom.custom_component.component import Component
from lfx.io import MessageInput, MessageTextInput
from lfx.schema.message import Message
from lfx.template.field.base import Output

DEFAULT_URL = "http://n8n.arkon.internal:5678/webhook/arkon-incident-status?limit=500"


class ArkonStatusUrl(Component):
    display_name = "Status API URL"
    description = "Hold the incident status endpoint once and hand it to every attempt."
    icon = "link"
    name = "ArkonStatusUrl"

    inputs = [
        MessageInput(
            name="trigger",
            display_name="Trigger",
            info="The briefing request. Only its arrival is used, never its content.",
        ),
        MessageTextInput(
            name="url",
            display_name="URL",
            info="The incident status API, with the query the briefing needs.",
            value=DEFAULT_URL,
        ),
    ]

    outputs = [
        Output(display_name="URL", name="endpoint", method="endpoint_output", types=["Message"]),
        Output(display_name="Request", name="request", method="request_output", types=["Message"]),
    ]

    def endpoint_output(self) -> Message:
        self.status = self.url
        return Message(text=self.url)

    def request_output(self) -> Message:
        """The operator's request, unchanged, so the chat input needs only one edge."""
        value = self.trigger
        text = value.text if isinstance(value, Message) else (value or "")
        return Message(text=text or "")
