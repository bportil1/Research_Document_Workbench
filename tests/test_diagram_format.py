import unittest

from diagram_format import (
    DiagramSyntaxError,
    diagram_to_mermaid,
    parse_diagram,
    serialize_diagram,
)


FARMBOT = """Modified FarmBot Web Interface [interface]
  -> Local FarmBot Web App [service]

Local FarmBot Web App
  -> Rails API [service]
  -> Database [database]

Rails API
  -> Message Broker [service]

Message Broker
  -> FarmBot OS / Raspberry Pi 4 [hardware]

FarmBot OS / Raspberry Pi 4
  -> Custom Experiments [custom]
  -> Farmduino [hardware]

Custom Experiments
  -> Physical FarmBot [hardware]

Farmduino
  -> Physical FarmBot

Physical FarmBot
  :: Motors / Camera
"""


class DiagramFormatTests(unittest.TestCase):
    def test_farmbot_example_parses(self):
        document = parse_diagram(FARMBOT)
        self.assertEqual(len(document.nodes), 9)
        self.assertEqual(len(document.edges), 9)
        self.assertEqual(document.nodes["Database"].kind, "database")
        self.assertEqual(document.nodes["Physical FarmBot"].note, "Motors / Camera")

    def test_inline_edges_are_supported(self):
        document = parse_diagram("A [service] -> B [database]\n")
        self.assertEqual([edge.to_dict() for edge in document.edges], [{"source": "A", "target": "B"}])
        self.assertEqual(document.nodes["B"].kind, "database")

    def test_conflicting_types_are_rejected(self):
        with self.assertRaises(DiagramSyntaxError):
            parse_diagram("A [service]\nA [hardware]\n")

    def test_note_requires_a_node(self):
        with self.assertRaises(DiagramSyntaxError):
            parse_diagram(":: orphan note\n")

    def test_round_trip(self):
        document = parse_diagram(FARMBOT)
        serialized = serialize_diagram(document)
        reparsed = parse_diagram(serialized)
        self.assertEqual(document.to_dict(), reparsed.to_dict())

    def test_mermaid_generation(self):
        document = parse_diagram("A [service]\n  -> Data [database]\n")
        mermaid = diagram_to_mermaid(document)
        self.assertIn("flowchart TB", mermaid)
        self.assertIn('n2[("Data")]', mermaid)
        self.assertIn("n1 --> n2", mermaid)


if __name__ == "__main__":
    unittest.main()

class DiagramBuilderOptionTests(unittest.TestCase):
    def test_direction_and_preset_directives_parse(self):
        document = parse_diagram(
            "@direction LR\n@preset research\n\nA [service]\n  -> B [database]\n"
        )
        self.assertEqual(document.direction, "LR")
        self.assertEqual(document.preset, "research")

    def test_options_are_serialized(self):
        document = parse_diagram("@direction RL\n@preset minimal\n\nA -> B\n")
        serialized = serialize_diagram(document)
        self.assertTrue(serialized.startswith("@direction RL\n\n@preset minimal\n"))

    def test_mermaid_uses_selected_direction_and_style(self):
        document = parse_diagram(
            "@direction LR\n@preset pipeline\n\nA [interface] -> B [hardware]\n"
        )
        mermaid = diagram_to_mermaid(document)
        self.assertIn("flowchart LR", mermaid)
        self.assertIn("class n1 interface;", mermaid)
        self.assertIn("class n2 hardware;", mermaid)
        self.assertIn("classDef interface", mermaid)
        self.assertIn("linkStyle default", mermaid)

    def test_mermaid_builder_overrides_do_not_require_source_changes(self):
        document = parse_diagram("A -> B\n")
        mermaid = diagram_to_mermaid(document, direction="BT", preset="minimal")
        self.assertIn("flowchart BT", mermaid)
        self.assertIn("fill:#ffffff", mermaid)

