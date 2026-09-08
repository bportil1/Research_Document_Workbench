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



class DiagramGroupTests(unittest.TestCase):
    def test_group_block_parses_members(self):
        document = parse_diagram(
            "@direction TB\n\n"
            "group Code Analysis Lab\n"
            "  Code Analyzer [service]\n"
            "  pyPIQUE [service]\n"
            "end\n"
            "Code Analyzer -> pyPIQUE\n"
        )
        self.assertEqual(len(document.groups), 1)
        self.assertEqual(document.groups[0].label, "Code Analysis Lab")
        self.assertEqual(document.groups[0].members, ["Code Analyzer", "pyPIQUE"])
        self.assertEqual(document.to_dict()["groups"], [
            {
                "label": "Code Analysis Lab",
                "members": ["Code Analyzer", "pyPIQUE"],
            }
        ])

    def test_group_mermaid_generation_uses_subgraphs_and_order_links(self):
        document = parse_diagram(
            "@direction TB\n"
            "group Code Analysis Lab\n"
            "  Code Analyzer [service]\n"
            "end\n"
            "group ML Lab\n"
            "  Model Selector [service]\n"
            "end\n"
        )
        mermaid = diagram_to_mermaid(document)
        self.assertIn('subgraph g1["Code Analysis Lab"]', mermaid)
        self.assertIn('subgraph g2["ML Lab"]', mermaid)
        self.assertIn("    direction TB", mermaid)
        self.assertIn("  g1 ~~~ g2", mermaid)

    def test_group_round_trip_preserves_membership_and_cross_group_edges(self):
        source = (
            "@direction TB\n"
            "@preset architecture\n\n"
            "group Code Analysis Lab\n"
            "  Code Analyzer [service]\n"
            "  pyPIQUE [service]\n"
            "end\n\n"
            "group ML Lab\n"
            "  Model Selector [service]\n"
            "end\n\n"
            "pyPIQUE -> Model Selector\n"
        )
        document = parse_diagram(source)
        serialized = serialize_diagram(document)
        reparsed = parse_diagram(serialized)
        self.assertEqual(document.to_dict(), reparsed.to_dict())

    def test_existing_node_can_be_explicitly_assigned_to_group(self):
        document = parse_diagram(
            "Shared Module [service]\n"
            "group ML Lab\n"
            "  Shared Module\n"
            "end\n"
        )
        self.assertEqual(document.groups[0].members, ["Shared Module"])

    def test_node_cannot_belong_to_two_groups(self):
        with self.assertRaises(DiagramSyntaxError) as ctx:
            parse_diagram(
                "group First\n"
                "  Shared [service]\n"
                "end\n"
                "group Second\n"
                "  Shared\n"
                "end\n"
            )
        self.assertIn("can belong to only one group", str(ctx.exception))

    def test_nested_and_unclosed_groups_are_rejected(self):
        with self.assertRaises(DiagramSyntaxError) as nested:
            parse_diagram("group Outer\n  A\n  group Inner\n  B\nend\n")
        self.assertIn("nested groups are not supported", str(nested.exception))

        with self.assertRaises(DiagramSyntaxError) as unclosed:
            parse_diagram("group Open\n  A\n")
        self.assertIn("Unclosed group", str(unclosed.exception))
