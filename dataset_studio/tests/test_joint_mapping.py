import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa

from backend.joint_mapping import (
    CANONICAL_JOINTS,
    build_joint_contract,
    contract_from_names,
    reorder_vectors,
    validate_joint_mapping,
)


class JointMappingTests(unittest.TestCase):
    def test_proposes_canonical_positions_for_standard_and_main_aliases(self):
        contract = contract_from_names(
            [
                "main_shoulder_pan",
                "main_shoulder_lift",
                "main_elbow_flex",
                "main_wrist_flex",
                "main_wrist_roll",
                "main_gripper",
            ],
            list(CANONICAL_JOINTS),
        )

        self.assertEqual(contract.proposal["action"]["shoulder_pan.pos"], 0)
        self.assertEqual(contract.proposal["action"]["gripper.pos"], 5)
        self.assertEqual(contract.proposal["observation.state"]["wrist_roll.pos"], 4)
        self.assertTrue(contract.compatible)

    def test_reads_contract_from_info_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "meta").mkdir()
            (root / "meta/info.json").write_text(
                json.dumps(
                    {
                        "features": {
                            "action": {"shape": [6], "names": list(CANONICAL_JOINTS)},
                            "observation.state": {"shape": [6], "names": list(CANONICAL_JOINTS)},
                        }
                    }
                )
            )

            contract = build_joint_contract(root)

            self.assertEqual(contract.action_shape, (6,))
            self.assertEqual(contract.state_names, CANONICAL_JOINTS)
            self.assertEqual(contract.to_dict()["canonical_joints"], list(CANONICAL_JOINTS))

    def test_rejects_7d_action_and_incomplete_or_duplicate_mapping(self):
        contract = contract_from_names(
            ["delta_eef.x", "delta_eef.y", "delta_eef.z", "delta_eef.rx", "delta_eef.ry", "delta_eef.rz", "gripper_open"],
            list(CANONICAL_JOINTS),
        )
        mapping = {
            "action": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
            "observation.state": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
        }

        errors = validate_joint_mapping(mapping, contract)

        self.assertTrue(any("7 positions" in error for error in errors))

        six = contract_from_names(list(CANONICAL_JOINTS), list(CANONICAL_JOINTS))
        mapping["action"].pop("gripper.pos")
        mapping["observation.state"]["gripper.pos"] = 4
        errors = validate_joint_mapping(mapping, six)
        self.assertTrue(any("action" in error and "missing" in error for error in errors))
        self.assertTrue(any("observation.state" in error and "duplicate" in error for error in errors))

    def test_reorders_vectors_to_canonical_order_as_float32(self):
        values = pa.chunked_array(
            [pa.array([[10, 20, 30, 40, 50, 60]], type=pa.list_(pa.float64(), 6))]
        )
        mapping = {
            name: index
            for name, index in zip(CANONICAL_JOINTS, [5, 4, 3, 2, 1, 0])
        }

        output = reorder_vectors(values, mapping)

        self.assertEqual(output.to_pylist(), [[60, 50, 40, 30, 20, 10]])
        self.assertEqual(output.type, pa.list_(pa.float32(), 6))


if __name__ == "__main__":
    unittest.main()
